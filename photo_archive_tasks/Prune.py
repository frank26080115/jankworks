import os, re, datetime, glob
from dateutil.relativedelta import relativedelta

import KeeperFinder

def is_deletable_dir(fpath):
    if os.path.isfile(fpath):
        dir = os.path.dirname(fpath)
    elif os.path.isdir(fpath):
        dir = os.path.abspath(fpath).strip(os.path.sep)
    else:
        return False, ""

    dirlower = dir.lower()

    if "astro" in dirlower:
        return False, ""
    if "collection" in dirlower:
        return False, ""
    if "stack" in dirlower:
        return False, ""

    expr = "^[0-9]{6}-[0-9]{8}$"
    m = re.search(expr, os.path.basename(dir))
    if m:
        return True, os.path.basename(dir)
    expr = "^[0-9]{8}$"
    m = re.search(expr, os.path.basename(dir))
    if m:
        return True, os.path.basename(dir)
    return False, ""

def get_dir_date(dpath):
    if "\\" in dpath or "/" in dpath or os.path.sep in dpath:
        dpath = os.path.basename(dpath)
    if "-" not in dpath:
        return False
    nparts = dpath.split("-")
    if len(nparts[0]) != 6:
        return False
    dt_str = "20" + nparts[0]
    try:
        dt = datetime.datetime.strptime(dt_str, "%Y%m%d")
        return dt
    except:
        return False

def is_deletable_type(fpath):
    filename, file_extension = os.path.splitext(fpath)
    file_extension = file_extension.lower()
    if file_extension == ".arw" or file_extension == ".jpg":
        return True
    return False

def prune(start_dir = "..", run_scan_first = True, actually_delete = 2000 * 1024 * 1024 * 1024, keep_months = 3):
    print("starting directory = %s" % (os.path.abspath(start_dir)))
    if run_scan_first:
        KeeperFinder.build_keeper_list(start_dir = start_dir)

    keeper_list = []
    g = glob.glob("fpaths-*.txt")
    if len(g) <= 0:
        print("no file list cache available")
        return
    g.sort()
    most_recent = g[-1]
    with open(most_recent) as f:
        print("opening cached file list: %s" % most_recent)
        line = f.readline()
        while line:
            lstriped = line.strip()
            if len(lstriped) > 0:
                keeper_list.append(lstriped)
            line = f.readline()
    print("keeper list has %u entries" % len(keeper_list))

    sn_list = []
    g = glob.glob("sernums-*.txt")
    if len(g) <= 0:
        print("no serial number list cache available")
        return
    g.sort()
    most_recent = g[-1]
    with open(most_recent) as f:
        print("opening cached file list: %s" % most_recent)
        line = f.readline()
        while line:
            lstriped = line.strip()
            if len(lstriped) > 0:
                try:
                    x = int(lstriped)
                    if x not in sn_list:
                        sn_list.append(x)
                except:
                    pass
            line = f.readline()
    print("serial number list has %u entries" % len(sn_list))

    dt_today = datetime.datetime.now()
    dt_str = dt_today.strftime("%Y%m%d-%H%M%S")
    delete_fpaths = "dellist-" + dt_str + ".txt"
    print("caching delete list to " + delete_fpaths)
    delete_fpaths_file = open(delete_fpaths, "w")

    del_cnt = 0
    fsize_sum = 0

    for root, dirs, files in os.walk(start_dir, topdown=False):
        for name in files:
            fpath = os.path.abspath(os.path.join(root, name))
            del_dir, dir_name = is_deletable_dir(fpath)
            if del_dir and is_deletable_type(fpath):
                dt = get_dir_date(dir_name)
                if dt != False:
                    dt_before = dt_today - relativedelta(months=keep_months)
                    if dt < dt_before:
                        sn = KeeperFinder.get_serialnum(fpath)
                        if sn != False:
                            if sn not in sn_list:
                                delete_fpaths_file.write(fpath + "\n")
                                delete_fpaths_file.flush()
                                file_stats = os.stat(fpath)
                                fsize_sum += file_stats.st_size
                                del_cnt += 1
    delete_fpaths_file.close()
    print("delete list has %u files, %u bytes" % (del_cnt, fsize_sum))

    if actually_delete > 0:
        print("starting actual delete, using list file %s" % (delete_fpaths))
        delete_fpaths_file = open(delete_fpaths, "r")
        fcnt = 0
        fsize_del = 0
        line = delete_fpaths_file.readline()
        while line and fsize_del < actually_delete:
            line = line.strip()
            fsize = 0
            try:
                if os.path.exists(line):
                    try:
                        file_stats = os.stat(line)
                        fsize = file_stats.st_size
                    except:
                        pass
                    os.remove(line)
                    print("deleted: %s" % (line))
                    fcnt += 1
                    fsize_del += fsize
            except Exception as ex:
                print("ERROR: unable to delete file \"%s\", exception: %s" % (line, str(ex)))
            if fsize_del > actually_delete:
                break
            line = delete_fpaths_file.readline()
        print("deleted %u files, %u bytes" % (fcnt, fsize_del))
        delete_fpaths_file.close()

if __name__ == "__main__":
    print("running prune script")
    prune()
