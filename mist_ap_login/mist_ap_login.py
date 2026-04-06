import argparse
import time
import requests
import urllib.parse
import socket
import subprocess
import platform
import re

# -----------------------------
# Config
# -----------------------------
CHECK_URL = "http://www.msftconnecttest.com/connecttest.txt"
CHECK_EXPECT = "Microsoft Connect Test"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/122.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Connection": "keep-alive",
}

SLEEP_IDLE = 300  # 5 minutes
RETRY_COUNT = 3
RETRY_DELAY = 10


# -----------------------------
# Helpers
# -----------------------------
def has_internet():
    try:
        print("[*] Checking internet connectivity...")
        r = requests.get(CHECK_URL, timeout=5, headers=HEADERS)
        if r.status_code == 200 and CHECK_EXPECT in r.text:
            print("[+] Internet is working")
            return True
    except Exception as e:
        print(f"[!] Connectivity check failed: {e}")
    return False


def get_local_ip():
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        print(f"[*] Local IP detected: {ip}")
        return ip
    except Exception as e:
        print(f"[!] Could not determine local IP: {e}")
        return None


def get_default_gateways():
    gateways = set()

    try:
        system = platform.system().lower()

        if "windows" in system:
            print("[*] Detecting gateway via ipconfig...")
            output = subprocess.check_output("ipconfig", text=True, stderr=subprocess.DEVNULL)

            # Matches: Default Gateway . . . . . . . . . : 192.168.1.1
            matches = re.findall(r"Default Gateway[ .:]*([\d\.]+)", output)
            for m in matches:
                if m.strip():
                    gateways.add(m.strip())

        else:
            print("[*] Detecting gateway via ip route...")
            output = subprocess.check_output(["ip", "route"], text=True, stderr=subprocess.DEVNULL)

            # Matches: default via 192.168.1.1 dev wlan0
            matches = re.findall(r"default via ([\d\.]+)", output)
            for m in matches:
                gateways.add(m.strip())

    except Exception as e:
        print(f"[!] Gateway detection failed: {e}")

    # Fallback (your old guessing, but now as backup only)
    if not gateways:
        print("[!] Falling back to common gateway guesses")
        gateways.update([
            "192.168.1.1",
            "192.168.0.1",
            "10.0.0.1",
            "172.16.0.1",
        ])

    print(f"[*] Gateways found: {list(gateways)}")
    return list(gateways)


def parse_query(url):
    parsed = urllib.parse.urlparse(url)
    qs = urllib.parse.parse_qs(parsed.query)
    return {k: v[0] for k, v in qs.items()}


def attempt_portal_flow(session, gateway_ip):
    try:
        print(f"[*] Trying gateway: {gateway_ip}")
        url = f"http://{gateway_ip}"

        # Step 1: hit gateway
        r = session.get(url, timeout=5, headers=HEADERS, allow_redirects=True)

        if not r.history:
            print("[!] No redirect detected")
            return False

        redirect_url = r.url
        print(f"[+] Redirected to: {redirect_url}")

        params = parse_query(redirect_url)
        print(f"[*] Parsed params: {params}")

        # Step 2: replay GET
        session.get(redirect_url, headers=HEADERS, timeout=5)

        # Step 3: construct POST
        base_url = redirect_url.split("?")[0]

        post_params = {
            "ap_mac": params.get("ap_mac", ""),
            "client_mac": params.get("client_mac", ""),
            "lang": "default",
            "url": params.get("url", ""),
            "wlan_id": params.get("wlan_id", ""),
        }

        post_url = base_url + "?" + urllib.parse.urlencode(post_params)

        payload = {
            "ap_mac": params.get("ap_mac", ""),
            "client_mac": params.get("client_mac", ""),
            "wlan_id": params.get("wlan_id", ""),
            "url": params.get("url", ""),
            "tos": "true",
            "auth_method": "passphrase",
        }

        print(f"[*] Sending POST to: {post_url}")
        r2 = session.post(
            post_url,
            headers={**HEADERS, "Content-Type": "application/x-www-form-urlencoded"},
            data=payload,
            timeout=5,
            allow_redirects=False,
        )

        if r2.status_code in (301, 302):
            print("[+] Portal accepted, verifying internet...")
            return has_internet()

        print(f"[!] Unexpected response: {r2.status_code}")
        return False

    except Exception as e:
        print(f"[!] Portal flow error: {e}")
        return False


def try_login():
    for attempt in range(RETRY_COUNT):
        print(f"[*] Attempt {attempt + 1}/{RETRY_COUNT}")

        try:
            session = requests.Session()

            local_ip = get_local_ip()
            gateways = build_gateway_candidates(local_ip)

            for gw in gateways:
                if attempt_portal_flow(session, gw):
                    print("[+] Login successful!")
                    return True

        except Exception as e:
            print(f"[!] Unexpected error: {e}")

        print(f"[*] Retry in {RETRY_DELAY} seconds...")
        time.sleep(RETRY_DELAY)

    print("[!] All attempts failed")
    return False


# -----------------------------
# Main loop
# -----------------------------
def main(run_once=False):
    while True:
        try:
            if not has_internet():
                print("[*] No internet, attempting login...")
                try_login()
            else:
                print("[*] Nothing to do, sleeping...")

        except Exception as e:
            print(f"[!] Top-level error caught: {e}")

        if run_once:
            break

        time.sleep(SLEEP_IDLE)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Captive portal auto-login helper")
    parser.add_argument("--once", action="store_true", help="Run only once")
    args = parser.parse_args()

    main(run_once=args.once)
