import random, datetime, os, string

from PIL import Image, ImageDraw, ImageFont

import myutils

CLOCKPOS_FILE_SUFFIX = ".clockpos.txt"

class ClockDraw(object):

    def __init__(self, parent):
        self.fontpairs = []
        self.fontpairs.append(make_font_fit("./fonts/corsiva.ttf"))
        self.fontpairs.append(make_font_fit("./fonts/corsiva.ttf", mainsize = 300, maxheight = 300, datescale = 0.4, linespace = 0.15, margin = 6))
        self.fontpairs.append(make_font_fit("./fonts/corsiva.ttf", datescale = 0))
        self.fontpairs.append(make_font_fit("./fonts/corsiva.ttf", mainsize = 300, maxheight = 300, datescale = 0, margin = 6))
        self.cur_pos        = [0, 0, 0, 0, 0]
        self.cur_imgfp      = None
        self.enable_ip_time = None

    def new_img(self, imgfp):
        print("clock prep for %s" % imgfp)
        self.cur_imgfp = imgfp
        self.cur_pos = get_clock_pos(imgfp)
        self.enable_ip = False

    def draw(self, img):
        enable_ip = False
        if self.enable_ip_time is not None:
            span = datetime.datetime.now() - self.enable_ip_time
            if span.total_seconds() < 5:
                enable_ip = True
        if enable_ip == False:
            fi = self.cur_pos[3]
            fi %= len(self.fontpairs)
            fontpair = self.fontpairs[fi]
            draw_clock(img, (self.cur_pos[0], self.cur_pos[1]), fontpair[0], fontpair[1], linespace = fontpair[2], placecode = self.cur_pos[2], shadowoffset = self.cur_pos[4])
        else:
            draw_clock(img, (self.cur_pos[0], self.cur_pos[1]), self.fontpairs[0][1], None, t = myutils.get_ip_address(), placecode = self.cur_pos[2], shadowoffset = self.cur_pos[4])

    def save_spec(self):
        fpath = self.cur_imgfp + CLOCKPOS_FILE_SUFFIX
        with open(fpath, "w") as f:
            s = "%u %u %u %u %u" % (self.cur_pos[0], self.cur_pos[1], self.cur_pos[2], self.cur_pos[3], self.cur_pos[4])
            f.write(s + '\n')
            print("wrote \"%s\" to file \"%s\"" % (s, fpath))

    def change_xy(self, x, y):
        self.cur_pos[0] = x
        self.cur_pos[1] = y
        self.save_spec()

    def change_corner(self):
        c = self.cur_pos[2] & 0x7F
        if c >= 1 and c <= 9:
            if c == 9:
                c = 19
            else:
                c += 1
        elif c == 19:
            c = 16
        elif c == 16:
            c = 13
        elif c == 13:
            c = 1
        elif c == 0:
            c = 8
        else:
            c = 7
        self.cur_pos[2] = (self.cur_pos[2] & 0x80) + c
        self.save_spec()

    def change_size(self):
        sbit = (self.cur_pos[2] & 0x80) != 0
        if sbit:
            self.cur_pos[2] &= 0x7F
        else:
            self.cur_pos[2] |= 0x80
        self.save_spec()

    def change_font(self):
        self.cur_pos[3] = (self.cur_pos[3] + 1) % len(self.fontpairs)
        self.save_spec()

    def change_shadow(self):
        self.cur_pos[4] -= self.cur_pos[4] % 4
        self.cur_pos[4] += 4
        self.cur_pos[4] %= 16
        self.save_spec()

    def show_ip(self):
        self.enable_ip_time = datetime.datetime.now()

def load_fonts(dirpath = "./fonts"):
    fontfiles = myutils.get_all_files("./fonts", ["*.ttf"])
    fontresults = []
    for fp in fontfiles:
        font_pair = make_font_fit(fp)
    return fontresults

def make_font_fit(fontfp, mainsize = 500, maxheight = 500, datescale = 0.3, linespace = 0.1, margin = 6):
    tstr = string.digits + ":"
    dstr = string.ascii_letters + string.digits + ","

    while mainsize > 0:
        fsz      = int(round(mainsize))
        fsz2     = int(round(float(fsz) * datescale))
        font1    = ImageFont.truetype(fontfp, fsz)
        font2    = None
        preview2 = (0, 0)
        spacing  = 0
        if datescale > 0:
            font2 = ImageFont.truetype(fontfp, fsz2)
            preview2 = font2.getsize(dstr)
        else:
            linespace = 0
        preview1 = font1.getsize(tstr)
        spacing = int(round(float(preview1[1]) * linespace))
        total_height = preview1[1] + spacing + preview2[1] + (margin * 2)
        if total_height <= maxheight:
            return font1, font2, spacing
        else:
            mainsize -= 1

    return ImageFont.load_default(), ImageFont.load_default() if datescale > 0 else None, 0

def draw_clock(img, pos, fontbig, fontsmall, linespace = 0, t = None, placecode = 7, forecolour = (255, 255, 255), border = 2, border2 = 2, bordercolour = (0, 0, 0), shadowoffset = 0, shadowcolour = (0, 0, 0)):
    if t is None:
        t = datetime.datetime.now()
    if isinstance(t, str):
        tstr = t
    else:
        tstr = t.strftime("%I:%M").lstrip('0')
    dstr = None
    placecode = int(placecode)
    if fontsmall is not None:
        if (placecode & 0x80) == 0x00:
            dstr = t.strftime("%A, %B %-d")
        else:
            dstr = t.strftime("%a, %b %-d")
            if "Wednesday" in dstr and "ber" in dstr:
                dstr = dstr.replace("Wednesday", "Wed")
            if "Sept" in dstr:
                dstr = dstr.replace("September", "Sept")

    draw = ImageDraw.Draw(img)

    #dim          = fontbig.getsize(tstr)
    dim          = draw.textsize(tstr, fontbig)
    time_width   = dim[0]
    time_height  = dim[1]
    total_width  = time_width
    total_height = time_height
    date_width   = 0
    date_height  = 0
    if dstr is not None and fontsmall is not None:
        #dim = fontsmall.getsize(dstr)
        dim = draw.textsize(dstr, fontsmall)
        date_width   =  dim[0]
        date_height  =  dim[1]
        total_width  =  max(total_width, date_width)
        total_height += date_height + linespace

    x_pos_1 = pos[0]
    y_pos_1 = pos[1]
    x_pos_2 = x_pos_1
    y_pos_2 = y_pos_1

    corner = int(placecode & 0x7F)

    if corner == 7 or corner == 4 or corner == 1:
        x_pos_1 = pos[0]
        x_pos_2 = x_pos_1
    elif corner == 8 or corner == 5 or corner == 2:
        x_pos_1 = pos[0] - (time_width / 2)
        x_pos_2 = pos[0] - (date_width / 2)
    elif corner == 9 or corner == 6 or corner == 3:
        x_pos_1 = pos[0] - time_width
        x_pos_2 = pos[0] - date_width
    elif corner == 19 or corner == 16 or corner == 13:
        x_pos_1 = pos[0] - total_width
        x_pos_2 = pos[0] - total_width
    if corner == 7 or corner == 8 or corner == 9 or corner == 19:
        y_pos_1 = pos[1]
    elif corner == 4 or corner == 5 or corner == 6 or corner == 16:
        y_pos_1 = pos[1] - (total_height / 2)
    elif corner == 1 or corner == 2 or corner == 3 or corner == 13:
        y_pos_1 = pos[1] - total_height
    y_pos_2 = y_pos_1 + linespace + time_height

    if shadowoffset > 0:
        draw.text((x_pos_1 + shadowoffset, y_pos_1 + shadowoffset), tstr, font=fontbig, fill=shadowcolour)
    draw.text((x_pos_1, y_pos_1), tstr, font=fontbig, fill=forecolour, stroke_width=border, stroke_fill=bordercolour)
    if dstr is not None and fontsmall is not None:
        if shadowoffset > 0:
            draw.text((x_pos_2 + shadowoffset, y_pos_2 + shadowoffset), dstr, font=fontsmall, fill=shadowcolour)
        draw.text((x_pos_2, y_pos_2), dstr, font=fontsmall, fill=forecolour, stroke_width=border2, stroke_fill=bordercolour)

def get_clock_pos(imgfp):
    txtfp = imgfp + CLOCKPOS_FILE_SUFFIX
    try:
        with open(txtfp, "r") as f:
            line = f.readline()
        nums = line.split(' ')
        pos_x    = int(nums[0])
        pos_y    = int(nums[1])
        pos_pc   = int(nums[2]) if len(nums) > 2 else 0
        pos_fi   = int(nums[3]) if len(nums) > 3 else 0
        pos_sh   = int(nums[4]) if len(nums) > 4 else 0
        return [pos_x, pos_y, pos_pc, pos_fi, pos_sh]
    except Exception as ex:
        print("ERROR: unable to parse clock position from \"%s\", ex: %s" % (txtfp, str(ex)))
        return [0, 0, 0, 0, 0]
