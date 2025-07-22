import os, shutil

img_exts = ["jpg", "jpeg", "arw", "tif", "tiff", "afphoto", "png"]

class DirObj(object):
    def __init__(self, path, parent = None):
        self.path = path
        self.parent = parent
        self.self_cnts = {}
        self.childs = []
        self.all_cnt = 0
        self.file_cnt = 0

    def search(self):
        for item in os.listdir(self.path):
            self.all_cnt += 1
            item_path = os.path.join(self.path, item)
            if os.path.isfile(item_path):
                self.file_cnt += 1
                file_name_without_extension, file_extension = os.path.splitext(os.path.basename(item_path))
                if len(file_extension) >= 2:
                    file_extension = file_extension.lower()
                if file_extension in self.self_cnts:
                    self.self_cnts[file_extension] += 1
                else:
                    self.self_cnts[file_extension] = 1
            elif os.path.isdir(item_path):
                ob = DirObj(item_path, self)
                ob.search()
                self.childs.append(ob)

    def get_ext_cnt(self, ext):
        ext = ext.lower()
        if ext[0] != '.':
            ext = '.' + ext
        cnt = 0
        if ext in self.self_cnts:
            cnt += self.self_cnts[ext]
        for i in self.childs:
            cnt += i.get_ext_cnt(ext)
        return cnt

    def prune(self):
        for i in self.childs:
            i.prune()
        bn = os.path.basename(self.path)
        if bn == "good" or bn == "keep":
            if self.all_cnt == 0:
                shutil.rmtree(self.path)
                print(f"deleting {self.path}")
        if self.parent is not None:
            parent_bn = os.path.basename(self.parent.path)
            if bn[0] == "2" and parent_bn.lower().startswith("photography2"):
                has_any = False
                for i in img_exts:
                    if self.get_ext_cnt("." + i) > 0:
                        has_any = True
                        break
                if has_any == False:
                    if self.path.lower().endswith("empty") == False:
                        abs_path = os.path.abspath(self.path)
                        new_path = abs_path + "-is-empty"
                        os.rename(abs_path, new_path)
                        print(f"renamed '{abs_path}' => '{new_path}'")

if __name__ == "__main__":
    print("running empty directory pruning script")
    x = DirObj(os.path.abspath(".."))
    x.search()
    print("search done")
    x.prune()
    print("dir prune done")