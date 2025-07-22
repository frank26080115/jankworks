import os, re, datetime

def is_keeper(fpath):
    filename, file_extension = os.path.splitext(fpath)
    file_extension = file_extension.lower()
    if file_extension == ".tiff" or file_extension == ".psd" or file_extension == ".afphoto" or file_extension == ".dop":
        return True
    dirname = os.path.dirname(fpath)
    dirname = dirname.lower()
    if "good" in dirname or "keep" in dirname:
        return True
    expr = r"[a-z,]{3}([0-9]{5,})([^a-z^0-9].*\.[a-z0-9]+)"
    m = re.search(expr, os.path.basename(fpath), flags=re.IGNORECASE)
    if m:
        m.group(1)
    return False

def get_serialnum(fpath):
    expr = r"[a-z,]{3}([0-9]{5,})([^a-z^0-9].*\.[a-z0-9]+)"
    m = re.search(expr, os.path.basename(fpath), flags=re.IGNORECASE)
    if m:
        return int(m.group(1))
    expr = r"[a-z,]{3}([0-9]{5,})(\.[a-z0-9]+)"
    m = re.search(expr, os.path.basename(fpath), flags=re.IGNORECASE)
    if m:
        return int(m.group(1))
    return False

def build_keeper_list(start_dir = ".."):
    print("starting directory = %s" % (os.path.abspath(start_dir)))
    dt_str = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    file_fpaths = "fpaths-" + dt_str + ".txt"
    print("caching to " + file_fpaths)
    file_fpaths = open(file_fpaths, "w")
    file_sernums = "sernums-" + dt_str + ".txt"
    print("caching to " + file_sernums)
    file_sernums = open(file_sernums, "w")
    file_names = []
    serial_numbers = []
    fsize_sum = 0

    for root, dirs, files in os.walk(start_dir, topdown=False):
        for name in files:
            fpath = os.path.abspath(os.path.join(root, name))
            if is_keeper(fpath):
                file_fpaths.write(fpath + "\n")
                file_fpaths.flush()
                file_stats = os.stat(fpath)
                fsize_sum += file_stats.st_size
                ser_num = get_serialnum(fpath)
                if ser_num != False:
                    if ser_num not in serial_numbers:
                        serial_numbers.append(ser_num)
                        file_sernums.write("%u\n" % ser_num)
                        file_sernums.flush()
                filename, file_extension = os.path.splitext(fpath)
                filename = os.path.basename(filename)
                if filename not in file_names:
                    file_names.append(filename)
    file_fpaths.close()
    file_sernums.close()

    print("keeping %u file paths, %u serial numbers" % (len(file_names), len(serial_numbers)))

    return file_names, serial_numbers

if __name__ == "__main__":
    print("running keeper finder script")
    build_keeper_list()
