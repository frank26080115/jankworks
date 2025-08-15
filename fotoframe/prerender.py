import sys, os, io, gc, random, time, datetime, subprocess, glob
from enum import Enum
import threading

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFilter

import fotophrame

FRAME_DELAY = 1
ALPHA_STEP  = 1.1 / 15.1

class PreRenderer(object):

    def __init__(self, parent):
        self.parent = parent
        self.prev_ready  = False
        self.next_ready  = False
        self.new_ready   = False
        self.wake_ready  = False
        self.all_ready   = False
        self.next_is_new = False
        self.stop_event = threading.Event()
        self.t = None
        self.pilimg_this = None
        self.pilimg_new  = None
        self.pilimg_next = None
        self.pilimg_prev = None
        self.pilimg_this_small = None
        self.pilimg_new_small  = None
        self.pilimg_next_small = None
        self.pilimg_prev_small = None

    def history_add_new_file(self, fp):
        self.parent.remove_file_from_history(fp)
        self.parent.history.append(fp)
        self.parent.history_idx = len(self.parent.history) - 1
        #print("pre-renderer shoved in file \"%s\"" % fp)

    def history_roll_next_file(self):
        fi = self.parent.history_idx + 1
        while True:
            fi = self.parent.history_idx + 1
            if fi < len(self.parent.history):
                fp = self.parent.history[fi]
                if os.path.exists(fp):
                    print("pre-renderer fwd file %s" % fp, flush=True)
                    self.parent.history_idx = fi
                    return
                else:
                    print("pre-renderer fwd file %s missing" % fp, flush=True)
                    self.parent.history.pop(fi)
            else:
                print("pre-renderer fwd file failed", flush=True)
                break
        self.parent.history_idx = len(self.parent.history) - 1

    def history_roll_prev_file(self):
        while len(self.parent.history) > 0:
            if self.parent.history_idx <= 0:
                break
            self.parent.history_idx -= 1
            if self.parent.history_idx < len(self.parent.history):
                fp = self.parent.history[self.parent.history_idx]
                if os.path.exists(fp):
                    return
                else:
                    print("prev file missing from filesystem %s" % fp, flush=True)
                    self.parent.remove_file_from_history(fp)

    def show_wake(self):
        for i in self.wake_buffer:
            cv2.imshow(self.parent.wndname, i)
            if self.parent.handle_key(cv2.waitKey(FRAME_DELAY), interrupt = True):
                print("animation interrupted")
                cv2.imshow(self.parent.wndname, self.wake_buffer[-1])
                cv2.waitKey(1)
                break
        self.parent.prerender_fade_done(self.pilimg_this, self.pilimg_this_small)

    def show_new(self, autostart = True):
        self.new_ready  = False
        self.next_ready = False
        self.prev_ready = False
        self.wake_ready = False
        self.all_ready  = False
        for i in self.future_buffer:
            cv2.imshow(self.parent.wndname, i)
            if self.parent.handle_key(cv2.waitKey(FRAME_DELAY), interrupt = True):
                print("animation interrupted")
                cv2.imshow(self.parent.wndname, self.future_buffer[-1])
                cv2.waitKey(1)
                break
        self.history_add_new_file(self.new_fp)
        self.parent.prerender_fade_done(self.pilimg_new, self.pilimg_new_small)
        if autostart:
            self.start()

    def show_next(self, autostart = True):
        self.new_ready  = False
        self.next_ready = False
        self.prev_ready = False
        self.wake_ready = False
        self.all_ready  = False
        for i in self.forward_buffer:
            cv2.imshow(self.parent.wndname, i)
            if self.parent.handle_key(cv2.waitKey(FRAME_DELAY), interrupt = True):
                print("animation interrupted")
                cv2.imshow(self.parent.wndname, self.forward_buffer[-1])
                cv2.waitKey(1)
                break
        if self.next_is_new:
            self.history_add_new_file(self.new_fp)
        else:
            self.history_roll_next_file()
        self.parent.prerender_fade_done(self.pilimg_next, self.pilimg_next_small)
        if autostart:
            self.start()

    def show_prev(self, autostart = True):
        self.new_ready  = False
        self.next_ready = False
        self.prev_ready = False
        self.wake_ready = False
        self.all_ready  = False
        for i in self.reverse_buffer:
            cv2.imshow(self.parent.wndname, i)
            if self.parent.handle_key(cv2.waitKey(FRAME_DELAY), interrupt = True):
                print("animation interrupted")
                cv2.imshow(self.parent.wndname, self.reverse_buffer[-1])
                cv2.waitKey(1)
                break
        self.history_roll_prev_file()
        self.parent.prerender_fade_done(self.pilimg_prev, self.pilimg_prev_small)
        if autostart:
            self.start()

    def blend(self, img1_big, img1_small, img2_big, img2_small, stepsize = ALPHA_STEP):
        alpha = 0
        buff = []
        done = False
        while not done and not self.stop_event.is_set():
            if alpha <= 0.0:
                res = img1_big
            elif alpha >= 1.0:
                res = img2_big
                done = True
            else:
                res = Image.blend(img1_small, img2_small, alpha=alpha)
                #res = Image.blend(img1_big, img2_big, alpha=alpha)
            res = cv2.cvtColor(np.array(res, dtype=np.uint8), cv2.COLOR_RGBA2BGR)
            buff.append(res)
            alpha += stepsize
        return buff

    def halt(self):
        self.stop_event.set()

    def start(self):
        self.new_ready  = False
        self.next_ready = False
        self.prev_ready = False
        self.wake_ready = False
        gc.collect()
        if self.t is not None:
            self.stop_event.set()
            if self.t.is_alive():
                print("waiting for pre-renderer thread to end", flush=True)
                self.t.join()
        print("pre-renderer thread starting", flush=True)
        self.t = threading.Thread(target = self.task)
        self.stop_event = threading.Event()
        self.t.start()

    def task(self):
        img_large = None
        if self.parent.img is not None:
            img_large = self.parent.img.copy()
            self.pilimg_this = img_large
        self.new_ready = False
        self.next_ready = False
        self.future_buffer = []
        self.forward_buffer = []
        ret = False
        while ret == False:
            if self.stop_event.is_set():
                print("pre-renderer got halt signal", flush=True)
                return
            self.new_fp = self.parent.peek_new_file()
            print("pre-renderer loading new file \"%s\"" % self.new_fp, flush=True)
            img_new, img_new_small, ret = self.parent.load_img_file(self.new_fp)
            if ret == False:
                print("pre-renderer failed loading new file \"%s\"" % self.new_fp, flush=True)
        self.pilimg_new = img_new
        self.pilimg_new_small = img_new_small

        if self.stop_event.is_set():
            print("pre-renderer got halt signal", flush=True)
            return

        if img_large is None:
            img_large = self.parent.blank_img.copy()
        self.pilimg_this = img_large
        if self.stop_event.is_set():
            print("pre-renderer got halt signal", flush=True)
            return
        img_small = img_large.resize((int(round(self.parent.screen_width / fotophrame.SMALL_IMG_DIV)), int(round(self.parent.screen_height / fotophrame.SMALL_IMG_DIV))))
        self.pilimg_this_small = img_small
        if self.stop_event.is_set():
            print("pre-renderer got halt signal", flush=True)
            return

        if ret and img_new_small is not None:
            self.future_buffer = self.blend(img_large, img_small, img_new, img_new_small)
            if self.stop_event.is_set():
                print("pre-renderer got halt signal", flush=True)
                return
            self.new_ready = True

        self.wake_buffer = self.blend(self.parent.blank_img.copy(), self.parent.blank_img_small.copy(), img_large, img_small, stepsize = ALPHA_STEP * 1.5)
        if self.stop_event.is_set():
            print("pre-renderer got halt signal", flush=True)
            return
        self.wake_ready = True

        if self.parent.history_idx >= (len(self.parent.history) - 1):
            print("pre-renderer re-using new file fade for next file fade", flush=True)
            self.next_is_new       = True
            self.pilimg_next       = self.pilimg_new
            self.pilimg_next_small = self.pilimg_new_small
            for i in self.future_buffer:
                if self.stop_event.is_set():
                    return
                self.forward_buffer.append(i.copy())
            if self.stop_event.is_set():
                print("pre-renderer got halt signal", flush=True)
                return
            self.next_ready = True
        else:
            self.next_is_new = False
            self.next_fp = self.parent.peek_next_file()
            print("pre-renderer loading next file \"%s\"" % self.next_fp, flush=True)
            img_next, img_next_small, ret = self.parent.load_img_file(self.next_fp)
            if ret:
                self.pilimg_next       = img_next
                self.pilimg_next_small = img_next_small
                self.forward_buffer = self.blend(img_large, img_small, img_next, img_next_small)
                if self.stop_event.is_set():
                    print("pre-renderer got halt signal", flush=True)
                    return
                self.next_ready = True

        self.prev_fp = self.parent.peek_prev_file()
        print("pre-renderer loading prev file \"%s\"" % self.prev_fp, flush=True)
        ret = False
        if self.prev_fp is not None:
            img_prev, img_prev_small, ret = self.parent.load_img_file(self.prev_fp)
        if ret and self.prev_fp is not None:
            self.pilimg_prev       = img_prev
            self.pilimg_prev_small = img_prev_small
            self.reverse_buffer = self.blend(img_large, img_small, img_prev, img_prev_small)
            if self.stop_event.is_set():
                print("pre-renderer got halt signal", flush=True)
                return
            self.prev_ready = True

        print("pre-renderer all done", flush=True)
        self.all_ready = True
