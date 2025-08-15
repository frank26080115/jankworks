import sys, os, io, gc, random, time, datetime, subprocess, glob

from pathlib import Path

def find_picture_dirs(target_dir):
    target_path = Path(target_dir).resolve()
    if not target_path.is_dir():
        raise ValueError(f"{target_dir} is not a valid directory")

    parent = target_path.parent
    name_prefix = target_path.name

    # Include target_path and any siblings that start with the same prefix
    dirs = [str(d) for d in parent.iterdir() if d.is_dir() and d.name.startswith(name_prefix)]
    return dirs

def get_all_files(dirpath, allexts):
    dirs = find_picture_dirs(dirpath)
    allfiles = []
    results  = []
    for d in dirs:
        for ext in allexts:
            allfiles.extend(glob.glob(os.path.join(d, ext        ), recursive = True))
            allfiles.extend(glob.glob(os.path.join(d, ext.upper()), recursive = True))
        for i in allfiles:
            found = False
            for j in results:
                if i.lower() == j.lower():
                    found = True
                    break
            if not found:
                results.append(i)
    return results

def get_ip_address():
    import socket
    ip_address = '';
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("www.google.com", 80))
        ip_address = s.getsockname()[0]
        s.close()
        return ip_address
    except:
        s = subprocess.check_output(['hostname', '-I'])
        s = str(s)
        s = s.split(' ')
        return s[0]
