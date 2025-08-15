import sys, os, io, gc, random, time, datetime, subprocess, glob

import cv2
import numpy as np
from PIL import Image, ImageDraw

def analyze_image(fp, mode = 0, screen_size = (3840, 2160), box_size = [1000, 400], analysis_scale = 4, show = True, showwait = False):
    screen_width  = screen_size[0]
    screen_height = screen_size[1]
    screen_aspect = float(screen_width) / float(screen_height)
    img = Image.open(fp)
    img_aspect = float(img.width) / float(img.height)
    wpercent = 1
    hpercent = 1
    print('image open "%s" (%u , %u , %.4f)' % (fp, img.width, img.height, img_aspect))
    if img_aspect >= screen_aspect:
        wpercent = float(screen_width) / float(img.width)
        dstheight = float(img.height) * wpercent
        topoffset = int(round(float(screen_height - dstheight) / float(2)))
        sz = (screen_width, int(round(dstheight)))
        pos = (0, topoffset)
    else:
        hpercent = float(screen_height) / float(img.height)
        dstwidth = float(img.width) * hpercent
        leftoffset = int(round(float(screen_width - dstwidth) / float(2)))
        sz = (int(round(dstwidth)), screen_height)
        pos = (leftoffset, 0)
    img = img.resize(sz)
    print('image size (%u x %u) offset (%u , %u)' % (sz[0], sz[1], pos[0], pos[1]))

    img = img.resize((int(round(sz[0] / analysis_scale)), int(round(sz[1] / analysis_scale))))

    cimg = np.array(img)
    if mode == 0:
        cvtimg = cv2.cvtColor(cimg, cv2.COLOR_BGR2Lab)
        cvtimg = np.multiply(cvtimg, (1.5, 1.0, 1.0), dtype=np.double)
    else:
        cvtimg = cv2.cvtColor(cimg, cv2.COLOR_BGR2GRAY)
        cvtimg = cv2.cvtColor(cvtimg, cv2.COLOR_GRAY2RGB)

    distarr = np.ndarray((cvtimg.shape[0], cvtimg.shape[1], 1), np.double)

    print("calculating energy map")

    sqrt2 = np.sqrt(2)
    x = 0
    while x < cvtimg.shape[1]:
        y = 0
        while y < cvtimg.shape[0]:
            pix  = cvtimg[y, x]
            sum = 0
            if y < cvtimg.shape[0] - 1:
                if x > 0:
                    pix1 = cvtimg[y + 1, x - 1]
                    dist1 = np.linalg.norm(np.subtract(pix,pix1), ord=1)
                    sum += dist1 / sqrt2
                pix2 = cvtimg[y + 1, x + 0]
                dist2 = np.linalg.norm(np.subtract(pix,pix2), ord=1)
                sum += dist2
                if x < cvtimg.shape[1] - 1:
                    pix3 = cvtimg[y + 1, x + 1]
                    dist3 = np.linalg.norm(np.subtract(pix,pix3), ord=1)
                    sum += dist3 / sqrt2
            if x > 0:
                pix4 = cvtimg[y + 0, x - 1]
                dist4 = np.linalg.norm(np.subtract(pix,pix4), ord=1)
                sum += dist4
            if x < cvtimg.shape[1] - 2:
                pix6 = cvtimg[y + 0, x + 1]
                dist6 = np.linalg.norm(np.subtract(pix,pix6), ord=1)
                sum += dist6
            if y > 0:
                if x > 0:
                    pix7 = cvtimg[y - 1, x - 1]
                    dist7 = np.linalg.norm(np.subtract(pix,pix7), ord=1)
                    sum += dist7 / sqrt2
                pix8 = cvtimg[y - 1, x + 0]
                dist8 = np.linalg.norm(np.subtract(pix,pix8), ord=1)
                sum += dist8
                if x < cvtimg.shape[1] - 1:
                    pix9 = cvtimg[y - 1, x + 1]
                    dist9 = np.linalg.norm(np.subtract(pix,pix9), ord=1)
                    sum += dist9 / sqrt2
            distavg = sum / float(8)
            #distavg += (pix[0] ** 3) / (2 * (255 ** 3))
            distarr[y, x] = distavg
            y += 1
        x += 1
        progress = float(x) * float(100) / float(cvtimg.shape[1])
        print("\rprogress %.1f" % progress, end='', flush=True)
    print("\r\ndone calculating energy map")
    normalized = cv2.normalize(distarr, 0, 255, norm_type=cv2.NORM_MINMAX, dtype=cv2.CV_8U)

    print("finding best box")

    box_size_small = (int(round(box_size[0] / analysis_scale)), int(round(box_size[1] / analysis_scale)))
    boxarr = np.ndarray((normalized.shape[0] - box_size_small[1], normalized.shape[1] - box_size_small[0], 1), np.double)
    x = 0
    while x < boxarr.shape[1]:
        y = 0
        while y < boxarr.shape[0]:
            sum = np.sum(distarr[y:y + box_size_small[1], x:x + box_size_small[0]])
            boxarr[y, x] = sum
            y += 1
        x += 1
        progress = float(x) * float(100) / float(boxarr.shape[1])
        print("\rprogress %.1f" % progress, end='', flush=True)
    print("\r\ndone finding box")

    am = boxarr.argmin()
    minpos = np.unravel_index(am, boxarr.shape)
    minval = boxarr[minpos[0], minpos[1]]
    print("min %.1f argmin %u pos (%u , %u)" % (minval, am, minpos[1], minpos[0]))

    boxnorm = cv2.normalize(boxarr, 0, 255, norm_type=cv2.NORM_MINMAX, dtype=cv2.CV_8U)
    cv2.imwrite(fp + ".box.png", cv2.cvtColor(boxnorm, cv2.COLOR_GRAY2RGB))

    th = 1
    while th <= 255:
        thresh = cv2.inRange(boxnorm, 0, th)
        contours, hierarchy = cv2.findContours(thresh, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        if len(contours) >= 2:
            #th = max(1, int(round(float(th) * 0.75)))
            th = max(1, int(round(float(th - 1))))
            break
        break
        th += 1
    thresh = cv2.inRange(boxnorm, 0, th)
    contours, hierarchy = cv2.findContours(thresh, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

    cv2.imwrite(fp + ".boxthresh.png", cv2.cvtColor(cv2.normalize(thresh, 0, 255, norm_type=cv2.NORM_MINMAX, dtype=cv2.CV_8U), cv2.COLOR_GRAY2RGB))

    cX = None
    cY = None

    if len(contours) == 1:
        m = cv2.moments(contours[0])
        try:
            cX = int(m["m10"] / m["m00"])
            cY = int(m["m01"] / m["m00"])
        except ZeroDivisionError:
            cX = minpos[1]
            cY = minpos[0]
    elif len(contours) > 1:
        contours = sorted(contours, key=lambda x: cv2.contourArea(x), reverse=True)
        found = False
        for c in contours:
            m = cv2.moments(c)
            try:
                cX = int(m["m10"] / m["m00"])
                cY = int(m["m01"] / m["m00"])
                if thresh[cY, cX] != 0:
                    found = True
                    break
            except ZeroDivisionError:
                pass
        if found == False:
            for c in contours:
                m = cv2.moments(c)
                try:
                    cX = int(m["m10"] / m["m00"])
                    cY = int(m["m01"] / m["m00"])
                    distances = np.sqrt(((thresh[:,:,0] - cY) ** 2) + ((thresh[:,:,1] - cX) ** 2))
                    nearest_index = np.argmin(distances)
                    nearest_pos = np.unravel_index(nearest_index, distances.shape)
                    cX = nearest_pos[1]
                    cY = nearest_pos[0]
                    break
                except ZeroDivisionError:
                    pass

    normalized_rgb = cv2.cvtColor(normalized, cv2.COLOR_GRAY2RGB)

    if cX is not None and cY is not None:
        print("found best box at (%u , %u)" % (cX, cY))
        cv2.rectangle(normalized_rgb, (cX, cY), (cX + box_size_small[0], cY + box_size_small[1]), (0, 0, 255), 1)
        with open(fp + ".clockpos.txt", "w") as f:
            f.write("%u %u %u %u %u %u\n" % (box_size[0], box_size[1], pos[0], pos[1], cX * analysis_scale, cY * analysis_scale))

    if show:
        cv2.imshow('frame', normalized_rgb)
    cv2.imwrite(fp + ".png", normalized_rgb)
    if show:
        cv2.waitKey(0 if showwait else 1)

g = glob.glob("C:\\Users\\frank\\Pictures\\PhotoFrame\\*.jpg")
for gi in g:
    analyze_image(gi, show = True, showwait = False)
#analyze_image("test.jpg")
#analyze_image("C:\\Users\\frank\\Pictures\\PhotoFrame\\andromeda_galaxy_starry.jpg")
