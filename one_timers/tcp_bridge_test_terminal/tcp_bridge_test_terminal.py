#!/usr/bin/env python3
"""Simple TCP terminal for testing a TCP-to-UART bridge echo loop."""

from __future__ import annotations

import argparse
import queue
import socket
import sys
import threading
import time
from datetime import datetime


DEFAULT_IP = "10.0.0.1"
DEFAULT_PORT = 65102
RECONNECT_DELAY_SECONDS = 5.0
RECV_POLL_SECONDS = 1.0
SOCKET_TIMEOUT_SECONDS = 1.0


def timestamp() -> str:
    return datetime.now().strftime("%H:%M:%S.%f")[:-5]


def log(message: str) -> None:
    print(f"{timestamp()}: {message}", flush=True)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="TCP terminal for testing a Wi-Fi TCP-to-UART bridge."
    )
    parser.add_argument(
        "remote_ip",
        nargs="?",
        default=DEFAULT_IP,
        help=f"Remote IP address to connect to. Default: {DEFAULT_IP}",
    )
    parser.add_argument(
        "port",
        nargs="?",
        type=int,
        default=DEFAULT_PORT,
        help=f"Remote TCP port. Default: {DEFAULT_PORT}",
    )
    return parser.parse_args()


def stdin_reader(
    outgoing: queue.Queue[str | None], stop_event: threading.Event
) -> None:
    while not stop_event.is_set():
        try:
            line = sys.stdin.readline()
        except KeyboardInterrupt:
            stop_event.set()
            outgoing.put(None)
            return
        except Exception as exc:
            log(f"stdin read error: {exc}")
            stop_event.set()
            outgoing.put(None)
            return

        if line == "":
            log("stdin closed; exiting")
            stop_event.set()
            outgoing.put(None)
            return

        outgoing.put(line)


def wait_or_stop(stop_event: threading.Event, seconds: float) -> bool:
    return stop_event.wait(seconds)


def connect(remote_ip: str, port: int, stop_event: threading.Event) -> socket.socket | None:
    while not stop_event.is_set():
        try:
            log(f"connecting to {remote_ip}:{port}")
            sock = socket.create_connection((remote_ip, port), timeout=SOCKET_TIMEOUT_SECONDS)
            sock.settimeout(SOCKET_TIMEOUT_SECONDS)
            log(f"connected to {remote_ip}:{port}")
            return sock
        except KeyboardInterrupt:
            stop_event.set()
            return None
        except Exception as exc:
            log(
                f"connection failed: {exc}; retrying in "
                f"{RECONNECT_DELAY_SECONDS:.0f} seconds"
            )
            if wait_or_stop(stop_event, RECONNECT_DELAY_SECONDS):
                return None

    return None


def send_pending(sock: socket.socket, outgoing: queue.Queue[str | None]) -> None:
    while True:
        try:
            line = outgoing.get_nowait()
        except queue.Empty:
            return

        if line is None:
            return

        sock.sendall(line.encode("ascii"))


def receive_once(sock: socket.socket) -> None:
    try:
        data = sock.recv(4096)
    except socket.timeout:
        return

    if data == b"":
        raise ConnectionError("remote closed the connection")

    text = data.decode("ascii", errors="replace").rstrip("\r\n")
    log(f"RX: {text}")


def terminal_loop(
    remote_ip: str,
    port: int,
    outgoing: queue.Queue[str | None],
    stop_event: threading.Event,
) -> None:
    sock: socket.socket | None = None

    while not stop_event.is_set():
        if sock is None:
            sock = connect(remote_ip, port, stop_event)
            if sock is None:
                continue

        try:
            send_pending(sock, outgoing)
            receive_once(sock)
        except KeyboardInterrupt:
            stop_event.set()
        except Exception as exc:
            log(f"connection lost: {exc}")
            try:
                sock.close()
            except Exception:
                pass
            sock = None
            if not stop_event.is_set():
                log(f"reconnecting in {RECONNECT_DELAY_SECONDS:.0f} seconds")
                wait_or_stop(stop_event, RECONNECT_DELAY_SECONDS)

    if sock is not None:
        try:
            sock.close()
        except Exception:
            pass


def main() -> int:
    args = parse_args()
    outgoing: queue.Queue[str | None] = queue.Queue()
    stop_event = threading.Event()
    reader = threading.Thread(
        target=stdin_reader,
        args=(outgoing, stop_event),
        daemon=True,
    )

    log("press CTRL-C to exit")
    reader.start()

    try:
        terminal_loop(args.remote_ip, args.port, outgoing, stop_event)
    except KeyboardInterrupt:
        stop_event.set()
    except Exception as exc:
        log(f"fatal error: {exc}")
        return 1
    finally:
        stop_event.set()
        log("exiting")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
