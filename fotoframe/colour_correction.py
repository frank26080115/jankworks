import sys, os, io, gc, random, time, datetime
import subprocess

import argparse

import cv2
import numpy as np
from PIL import Image

FILE_SUFFIX = ".corrections.txt"

def image_correct(img, fp):
    correction_file = fp + FILE_SUFFIX
    bgr = None
    try:
        if not os.path.exists(correction_file):
            return img

        with open(correction_file, "r") as f:
            rgb = np.array(img)
            bgr = cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR)
            line = f.readline()
            while line:
                parts = line.split(' ')
                if len(parts) >= 2:
                    if parts[0] == "gamma":
                        bgr = adjust_gamma(bgr, float(parts[1]))
                    if parts[0] == "vibrance":
                        bgr = adjust_vibrance(bgr, float(parts[1]))
                    if parts[0] == "blackpoint":
                        bgr = adjust_blackpoint_whitepoint(bgr, bp=float(parts[1]))
                    if parts[0] == "whitepoint":
                        bgr = adjust_blackpoint_whitepoint(bgr, wp=float(parts[1]))
                    if parts[0] == "brightness":
                        bgr = adjust_brightness_contrast(bgr, brightness=float(parts[1]))
                    if parts[0] == "contrast":
                        bgr = adjust_brightness_contrast(bgr, contrast=float(parts[1]))
                    if len(parts) >= 3:
                        if parts[0] == "blackpoint_whitepoint":
                            bgr = adjust_blackpoint_whitepoint(bgr, float(parts[1]), float(parts[2]))
                        if parts[0] == "brightness_contrast":
                            bgr = adjust_brightness_contrast(bgr, float(parts[1]), float(parts[2]))
                line = f.readline()
    except Exception as ex:
        print("ERROR: while attempting to correct file \"%s\", exception: %s" % (fp, str(ex)))
    finally:
        if bgr is None:
            return img
        else:
            return Image.fromarray(cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB))

def open_editor(fp):
    subprocess.Popen(["mousepad", fp + FILE_SUFFIX])

def adjust_gamma(img, gamma=1.0):
    invGamma = 1.0 / gamma
    table = np.array([((i / 255.0) ** invGamma) * 255
        for i in np.arange(0, 256)]).astype("uint8")
    return cv2.LUT(img, table)

def adjust_vibrance(img, x=1.0):
    hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
    invGamma = 1.0 / x
    table = np.array([((i / 255.0) ** invGamma) * 255
        for i in np.arange(0, 256)]).astype("uint8")
    hsv[...,1] = cv2.LUT(hsv[...,1], table)
    return cv2.cvtColor(hsv, cv2.COLOR_HSV2BGR)

def adjust_blackpoint_whitepoint(img, bp=0, wp=255):
    hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
    span = wp - bp
    m = float(255) / float(span)
    table = np.array([int(max(0, min(255, round(  (i - bp) + (i * m)  ))))
        for i in np.arange(0, 256)]).astype("uint8")
    hsv[...,2] = cv2.LUT(hsv[...,2], table)
    return cv2.cvtColor(hsv, cv2.COLOR_HSV2BGR)

def adjust_brightness_contrast(input_img, brightness = 0, contrast = 0):
    if brightness != 0:
        if brightness > 0:
            shadow = brightness
            highlight = 255
        else:
            shadow = 0
            highlight = 255 + brightness
        alpha_b = (highlight - shadow)/255
        gamma_b = shadow
        
        buf = cv2.addWeighted(input_img, alpha_b, input_img, 0, gamma_b)
    else:
        buf = input_img.copy()
    
    if contrast != 0:
        f = 131*(contrast + 127)/(127*(131-contrast))
        alpha_c = f
        gamma_c = 127*(1-f)
        buf = cv2.addWeighted(buf, alpha_c, buf, 0, gamma_c)

    return buf

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description='test colour correction')
    parser.add_argument('--file', '-f', type=str, help="file path to image")
    args = parser.parse_args()
    img = Image.open(args.file)
    res = image_correct(img, args.file)
    cv2.imshow("image", cv2.cvtColor(np.array(res), cv2.COLOR_RGB2BGR))
    cv2.waitKey(0)
