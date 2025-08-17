#!/usr/bin/env python3

import sys, os, io, gc, random, time, datetime, subprocess, glob
from enum import Enum

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFilter
from screeninfo import get_monitors

import myutils
import prerender, clock_draw, colour_correction
import hdmi_ctrl

# time between photos
FRAME_INTERVAL = 60

# time to sleep monitor
TIME_TO_SLEEP = 300


FADE_ALPHA_STEP  = 1
FADE_ALPHA_LIMIT = 9
SMALL_IMG_DIV    = 4

class FadeState(Enum):
    Idle        = 0
    FadeIn      = 1
    FadeOutNext = 2
    FadeOutNew  = 3
    FadeOutPrev = 4
    MonitorOff  = 5

class FotoPhrame(object):

    def __init__(self, dirpath = './Pictures', enable_blur_border = 0.6, stay_on = False):
        os.environ['DISPLAY'] = ":0.0" # required for launching a window out of a SSH session
        screen = get_monitors()[0]
        self.screen_width  = screen.width
        self.screen_height = screen.height
        self.screen_aspect = float(self.screen_width) / float(self.screen_height)
        self.hdmi_ctrler = hdmi_ctrl.HdmiCtrl(self, time_to_sleep = TIME_TO_SLEEP if not stay_on else 0)
        self.hdmi_ctrler.hide_mouse()
        self.hdmi_ctrler.force_on()
        self.hdmi_ctrler.set_timer()
        print("window %u x %u aspect %.4f" % (self.screen_width, self.screen_height, self.screen_aspect))
        self.regen_blanks()
        self.wndname = 'frame'
        cv2.namedWindow      (self.wndname, cv2.WND_PROP_FULLSCREEN)
        cv2.setWindowProperty(self.wndname, cv2.WND_PROP_FULLSCREEN, cv2.WINDOW_FULLSCREEN)
        cv2.imshow           (self.wndname, np.array(self.blank_img))
        #cv2.setWindowProperty(self.wndname, cv2.WND_PROP_TOPMOST, 1) # the version of OpenCV I have doesn't support this
        cv2.waitKey(1)
        print("window launched")

        self.dirpath = dirpath
        self.enable_blur_border = enable_blur_border
        self.stay_on = stay_on

        self.edit_mode  = False
        self.last_key   = 0
        self.fade_state = FadeState.Idle
        self.fade_alpha = 0
        self.prev_frame_time = datetime.datetime.now()
        self.prev_activity_time = datetime.datetime.now()
        self.history = []
        self.history_idx = -1
        self.is_blank = True

        # even though we already called imshow, it takes quite a bit of time for the window to take over the screen
        # we use this time to do useful things

        self.prerenderer = prerender.PreRenderer(self)
        self.prerenderer.start()
        print("waiting for pre-renderer to generate first fade, while clock fonts are loading")
        self.clock_draw = clock_draw.ClockDraw(self)
        while not self.prerenderer.all_ready:
            self.handle_key(cv2.waitKey(1), all = False)
        self.prerenderer.show_new()
        print("init complete")

    def regen_blanks(self):
        # this function exists just in case of a MemoryError
        # truthfully, investigation shows that this doesn't help
        self.blank_img = Image.new('RGBA', (self.screen_width, self.screen_height))
        self.blank_img_small = Image.new('RGBA', (int(round(self.screen_width / SMALL_IMG_DIV)), int(round(self.screen_height / SMALL_IMG_DIV))))
        self.blank_img.putalpha(255)
        self.blank_img_small.putalpha(255)
        self.blank_tiny = np.zeros([9,16,4], dtype=np.uint8)
        self.img = self.blank_img.copy()
        self.img_small = self.blank_img_small.copy()

    def keyhdl_left(self):
        print("key-press left")
        if self.fade_state == FadeState.MonitorOff:
            #self.wake_up()
            pass
        else:
            self.prev_photo()

    def keyhdl_right(self):
        print("key-press right")
        if self.fade_state == FadeState.MonitorOff:
            #self.wake_up()
            pass
        else:
            self.next_photo()

    def keyhdl_up(self):
        print("key-press up")
        #self.wake_up()

    def wake_up(self):
        self.hdmi_ctrler.poke(force = True)
        if self.fade_state == FadeState.MonitorOff: # prevent repetition
            if self.prerenderer.wake_ready:
                print("pre-rendered wake")
                self.prerenderer.show_wake()
            else:
                self.fade_alpha = 0
                self.fade_state = FadeState.FadeIn

    def handle_key(self, key, all = True, interrupt = False):
        if key is None:
            return False
        if key == -1:
            return False
        if key == 0xFF:
            return False
        last_key = self.last_key
        self.last_key = key
        if (key & 0x7F) == 27:
            print('quit using ESC')
            self.prerenderer.halt()
            sys.exit()
            return True
        self.prev_activity_time = datetime.datetime.now()
        if not all:
            return False
        if interrupt and key != 0x52:
            # animation can be interrupted but not by motion
            return True
        if self.stay_on == False and key != 0x71:
            self.hdmi_ctrler.poke(force = True)
        if key == 0x51:
            self.keyhdl_left()
        elif key == 0x53:
            self.keyhdl_right()
        elif key == 0x52:
            self.keyhdl_up()
        elif key == 0x54:
            print('key-press down')
            if last_key == key:
                print("toggle IP on image")
                self.clock_draw.show_ip()
        elif key == ord('e'):
            print('E key, edit mode')
            if self.edit_mode == False:
                cv2.setMouseCallback(self.wndname, mouse_clicked)
            self.edit_mode = True
        elif (key == ord('-') or key == ord('+') or key == ord('f') or key == ord('s')) and self.edit_mode:
            self.prev_frame_time = datetime.datetime.now()
            if key == ord('-'):
                print("clock edit corner")
                self.clock_draw.change_corner()
            elif key == ord('+'):
                print("clock edit size")
                self.clock_draw.change_size()
            elif key == ord('f'):
                print("clock edit font")
                self.clock_draw.change_font()
            elif key == ord('s'):
                print("clock edit shadow")
                self.clock_draw.change_shadow()
        elif key == 0x74 and self.edit_mode:
            print("opening text editor for colour correction")
            colour_correction.open_editor(self.curr_file_path())
        elif key == 0x71:
            print("key-press Q")
            self.hdmi_ctrler.force_off()
        else:
            print('key-press unknown 0x%08X' % key)
            return False

    def new_photo(self):
        if self.prerenderer.new_ready:
            print("pre-rendered new photo fade")
            self.prerenderer.show_new()
        else:
            self.prerenderer.halt()
            if self.fade_state == FadeState.FadeIn:
                self.fade_alpha = FADE_ALPHA_LIMIT
                return
            self.fade_alpha = 0 if self.fade_state == FadeState.FadeOutNew else FADE_ALPHA_LIMIT
            self.fade_state = FadeState.FadeOutNew

    def next_photo(self):
        if self.prerenderer.next_ready:
            print("pre-rendered next photo fade")
            self.prerenderer.show_next()
        else:
            self.prerenderer.halt()
            if self.fade_state == FadeState.FadeIn:
                self.fade_alpha = FADE_ALPHA_LIMIT
                return
            self.fade_alpha = 0 if self.fade_state == FadeState.FadeOutNext else FADE_ALPHA_LIMIT
            self.fade_state = FadeState.FadeOutNext

    def prev_photo(self):
        if self.prerenderer.prev_ready:
            print("pre-rendered prev photo fade")
            self.prerenderer.show_prev()
        else:
            self.prerenderer.halt()
            if self.fade_state == FadeState.FadeIn:
                self.fade_alpha = FADE_ALPHA_LIMIT
                return
            self.fade_alpha = 0 if self.fade_state == FadeState.FadeOutPrev else FADE_ALPHA_LIMIT
            self.fade_state = FadeState.FadeOutPrev

    def error_report(self, err, txt = ''):
        if len(txt) > 0:
            txt += '\n'
        msgstr = txt + str(err)
        print("error report: " + msgstr)

    def show_img(self, img = None, wait = 1, alpha = None):
        if img is None:
            img = self.img
        if img is None:
            img = self.blank_img.copy()
        if 'PIL' in str(type(img)):
            try:
                nimg = np.array(img)
            except MemoryError:
                print("MemoryError in show_img")
                gc.collect()
                self.regen_blanks()
                nimg = self.blank_tiny
            img = cv2.cvtColor(nimg, cv2.COLOR_RGBA2BGR)
        if alpha is not None:
            if alpha >= FADE_ALPHA_LIMIT:
                alpha = 1
            else:
                alpha = FADE_ALPHA_LIMIT - alpha
            if alpha > 1:
                img = cv2.divide(img, (alpha, alpha, alpha, alpha))
            elif alpha == 0:
                img = self.blank_tiny
        cv2.imshow(self.wndname, img)
        self.handle_key(cv2.waitKey(wait))

    def get_faded_img(self, img = None, alpha = None):
        if alpha is None:
            alpha = self.fade_alpha
        alpha = int(round(alpha))
        if img is None:
            img = self.img_small
        if 'PIL' in str(type(img)):
            try:
                nimg = np.array(img)
            except MemoryError:
                print("MemoryError in get_faded_img")
                gc.collect()
                self.regen_blanks()
                nimg = self.blank_tiny
        img = cv2.cvtColor(nimg, cv2.COLOR_RGBA2BGR)
        if alpha >= FADE_ALPHA_LIMIT:
            alpha = 1
        else:
            alpha = FADE_ALPHA_LIMIT - alpha
        if alpha > 1:
            img = cv2.divide(img, (alpha, alpha, alpha, alpha))
        elif alpha == 0:
            img = self.blank_tiny
        return img

    def draw_clock(self, img = None):
        if img is None:
            img = self.img
        img = img.copy()
        self.clock_draw.draw(img)
        return img

    def load_img_file(self, fp):
        bg = self.blank_img.copy()
        if fp is None:
            return bg, self.blank_img_small, False
        try:
            img = Image.open(fp)
        except Exception as ex:
            self.error_report(ex, txt = 'trying to open ' + fp)
            return bg, self.blank_img_small, False
        img_aspect = float(img.width) / float(img.height);
        print('img open "%s" (%u , %u , %.4f)' % (fp, img.width, img.height, img_aspect))

        img = colour_correction.image_correct(img, fp)

        # resize image to fit the screen while respecting aspect ratio
        # I am avoiding the usage of the thumbnail function
        if img_aspect >= self.screen_aspect:
            wpercent = float(self.screen_width) / float(img.width)
            dstheight = float(img.height) * wpercent
            topoffset = int(round(float(self.screen_height - dstheight) / float(2)))
            img = img.resize((self.screen_width, int(round(dstheight))))
            pos = (0, topoffset)
            if self.enable_blur_border > 0 and topoffset < int(round(dstheight / float(3))):
                bg.paste(img, (0, 0))
                bg.paste(img, (0, bg.height - img.height))
                bg = bg.filter(ImageFilter.GaussianBlur(20))
                #bg.putalpha(64 * 3)
                bg = bg.point(lambda p: p * self.enable_blur_border)
        else:
            hpercent = float(self.screen_height) / float(img.height)
            dstwidth = float(img.width) * hpercent
            leftoffset = int(round(float(self.screen_width - dstwidth) / float(2)))
            img = img.resize((int(round(dstwidth)), self.screen_height))
            pos = (leftoffset, 0)
            if self.enable_blur_border > 0 and leftoffset < int(round(dstwidth / float(3))):
                bg.paste(img, (0                   , 0))
                bg.paste(img, (bg.width - img.width, 0))
                bg = bg.filter(ImageFilter.GaussianBlur(20))
                #bg.putalpha(64 * 3)
                bg = bg.point(lambda p: p * self.enable_blur_border)
        bg.paste(img, pos)
        img_small = bg.resize((int(round(self.screen_width / SMALL_IMG_DIV)), int(round(self.screen_height / SMALL_IMG_DIV))))
        return bg, img_small, True

    def curr_file_path(self):
        if self.history_idx < 0:
            return None
        while self.history_idx >= len(self.history):
            self.history_idx -= 1
        return self.history[self.history_idx]

    def peek_next_file(self):
        if self.history_idx + 1 <= (len(self.history) - 1):
            fp = self.history[self.history_idx + 1]
            return fp
        return self.peek_new_file()

    def peek_new_file(self):
        allfiles = myutils.get_all_files(self.dirpath, ['*.jpg', '*.png'])
        if len(allfiles) <= 0:
            print("no files found")
            return None # self.load_img_file(None)

        # if we are editing the clock position, then try to show only images without set clock positions
        if self.edit_mode:
            allfiles2 = []
            for i in allfiles:
                if os.path.exists(i) and not os.path.exists(i + clock_draw.CLOCKPOS_FILE_SUFFIX):
                    allfiles2.append(i)
            if len(allfiles2) > 0:
                allfiles = allfiles2

        rndlim = int(round(max(5, len(allfiles)) / 3))
        print("files count %u" % len(allfiles))
        fp = None
        retries = 0
        while fp is None:
            # pick a random file out of the list
            # check if it was recently displayed
            repeat = False
            r = random.randint(0, len(allfiles) - 1)
            x = os.path.abspath(allfiles[r])
            i = len(self.history) - 1
            if i < 0:
                fp = x
                break
            j = 0
            while i >= 0 and j <= rndlim and repeat == False:
                if self.history[i].lower() == x.lower():
                    repeat = True
                i -= 1
                j += 1
            if not repeat or retries > 10:
                fp = x
            retries += 1
        return fp

    def peek_prev_file(self):
        if len(self.history) <= 0:
            return None
        hi = max(0, self.history_idx - 1)
        return self.history[hi]

    def get_next_file(self, force_new):
        if force_new:
            while self.history_idx >= 0 and self.history_idx < (len(self.history) - 1):
                self.history.pop()
        else:
            while self.history_idx >= 0 and self.history_idx < (len(self.history) - 1):
                fp = self.history[self.history_idx + 1];
                if os.path.exists(fp):
                    print("fwd file %s" % fp)
                    img, img_small, ret = self.load_img_file(fp)
                    if ret:
                        self.history_idx += 1
                        return img, img_small, ret
                    else:
                        self.history.pop(self.history_idx + 1)
                        continue
                else:
                    self.history.pop(self.history_idx + 1)
                    continue
        fp = self.peek_new_file()
        if fp is not None:
            print("new file %s" % fp)
            self.remove_file_from_history(fp)
            self.history.append(fp)
            self.history_idx = len(self.history) - 1
            return self.load_img_file(fp)
        return self.load_img_file(None)

    def get_prev_file(self):
        print("rev file")
        while len(self.history) > 0:
            if self.history_idx <= 0:
                return self.get_next_file(False)
            self.history_idx -= 1
            if self.history_idx < len(self.history):
                fp = self.history[self.history_idx]
                if os.path.exists(fp):
                    img, img_small, ret = self.load_img_file(fp)
                    if ret:
                        return img, img_small, ret
                    else:
                        print("prev file failed to load %s" % fp)
                        self.remove_file_from_history(fp)
                else:
                    print("prev file missing from filesystem %s" % fp)
                    self.remove_file_from_history(fp)
        return self.get_next_file(False)

    def remove_file_from_history(self, fp):
        while fp in self.history:
            rmv = self.history.index(fp)
            if rmv < self.history_idx:
                self.history_idx -= 1
            self.history.pop(rmv)

    def prerender_fade_done(self, img, img_small):
        self.fade_alpha      = FADE_ALPHA_LIMIT
        self.fade_state      = FadeState.Idle
        self.prev_frame_time = datetime.datetime.now()
        self.img             = img       if img       is not None else self.img
        self.img_small       = img_small if img_small is not None else self.img_small
        self.is_blank        = False
        self.clock_draw.new_img(self.curr_file_path())

    def tick(self):
        now = datetime.datetime.now()
        if self.fade_state == FadeState.FadeIn:
            if self.img is None or self.is_blank:
                print("getting next file for fade in")
                self.img, self.img_small, ret = self.get_next_file(True)
                self.is_blank = not ret
            if self.img is not None and not self.is_blank:
                if self.fade_alpha <= FADE_ALPHA_LIMIT:
                    self.fade_alpha += FADE_ALPHA_STEP
                    faded_img = self.get_faded_img()
                    self.show_img(faded_img)
                    if self.fade_alpha >= FADE_ALPHA_LIMIT:
                        print("finished fade in")
                        self.fade_state = FadeState.Idle
                        self.prev_frame_time = now
                        self.prerenderer.start()
                else:
                    print("skipped fade in")
                    self.show_img()
                    self.fade_state = FadeState.Idle
                    self.prev_frame_time = now
                    self.prerenderer.start()
            else:
                print("fade in attempted without image")
                self.show_img(None)
        elif self.fade_state == FadeState.FadeOutNew or self.fade_state == FadeState.FadeOutNext or self.fade_state == FadeState.FadeOutPrev:
            if self.img is not None and not self.is_blank:
                if self.fade_alpha <= FADE_ALPHA_LIMIT:
                    self.fade_alpha -= FADE_ALPHA_STEP
                    faded_img = self.get_faded_img()
                    self.show_img(faded_img)
                else:
                    print("skipped fade out")
                    self.fade_alpha = 0
            else:
                print("trying to fade out without an image")
                self.fade_alpha = 0
            if self.fade_alpha <= 0:
                self.fade_alpha = 0
                print("finished fade out")
                if self.fade_state == FadeState.FadeOutPrev:
                    self.img, self.img_small, ret = self.get_prev_file()
                    self.is_blank = not ret
                else:
                    self.img, self.img_small, ret = self.get_next_file(True if self.fade_state == FadeState.FadeOutNew else False)
                    self.is_blank = not ret
                self.fade_state = FadeState.FadeIn
                self.clock_draw.new_img(self.curr_file_path())
                print("start fade in")
        elif self.fade_state == FadeState.Idle:
            gc.collect()
            span = now - self.prev_frame_time
            if span.total_seconds() >= FRAME_INTERVAL and self.prerenderer.all_ready:
                if self.stay_on and self.edit_mode == False:
                    self.hdmi_ctrler.poke()
                print("time for new photo")
                if self.prerenderer.new_ready:
                    print("pre-rendered new fade")
                    self.prerenderer.show_new()
                else:
                    self.new_photo()
            elif self.img is None or self.is_blank:
                print("idle with no photo")
                self.new_photo()
            else:
                img = self.draw_clock()
                self.show_img(img, wait = 500 if not self.edit_mode else 10)
            if self.edit_mode == False:
                time.sleep(5)
            if self.hdmi_ctrler.is_monitor_on() == False:
                print("monitor turned off")
                self.hdmi_ctrler.log()
                gc.collect()
                self.show_img(self.blank_tiny, wait = 100)
                if self.hdmi_ctrler.is_monitor_on() == False:
                    self.fade_alpha = 0
                    self.fade_state = FadeState.MonitorOff
        elif self.fade_state == FadeState.MonitorOff:
            self.show_img(self.blank_tiny, wait = 100)
            time.sleep(5)
            if self.hdmi_ctrler.is_monitor_on():
                print("monitor turned on")
                self.hdmi_ctrler.log()
                if self.fade_state == FadeState.MonitorOff:
                    self.wake_up()
        else:
            print("ERROR: unknown fade state %s" % self.fade_state)
            self.fade_state = FadeState.Idle

    def main_loop(self):
        print("main loop running")
        while True:
            try:
                self.tick()
            except KeyboardInterrupt:
                if self.fade_state == FadeState.MonitorOff:
                    print("\nwakingfrom KeyboardInterrupt")
                    self.show_img(self.blank_tiny, wait = 100)
                    self.hdmi_ctrler.poke(force = True)
                    self.fade_alpha = 0
                    self.fade_state = FadeState.FadeIn
                    if self.prerenderer.wake_ready:
                        print("pre-rendered wake")
                        self.prerenderer.show_wake()
                    else:
                        print("slow-render wake")
                else:
                    print("\nquitting from KeyboardInterrupt")
                    self.prerenderer.halt()
                    sys.exit()

root = None

def mouse_clicked(event, x, y, flags, param):
    global root
    if event == cv2.EVENT_LBUTTONDBLCLK:
        print("dbl-click event (%u , %u)" % (x, y))
        root.clock_draw.change_xy(x, y)

def main():
    global root
    root = FotoPhrame()
    root.main_loop()
    return 0

if __name__ == '__main__':
    main()