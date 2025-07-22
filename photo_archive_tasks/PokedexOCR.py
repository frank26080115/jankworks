#import pytesseract
import easyocr
import glob, os
#from PIL import Image, ImageOps
import cv2

deep_search = False

if deep_search:
    search_root = "./../**/"
else:
    search_root = "./Collections/pokedex/**/"

g1 = glob.glob(search_root + "DSC*3x2*.jpg", recursive=True)
g2 = glob.glob(search_root + "DSC*3x2*.png", recursive=True)
g3 = glob.glob(search_root + "DSC*pokedex*.jpg", recursive=True)
g4 = glob.glob(search_root + "DSC*pokedex*.png", recursive=True)

concatenated_list = g1 + g2 + g3 + g4

db_file = "pokedex-database.csv"
data_dict = {}
if os.path.exists(db_file):
    with open(db_file, "r") as f:
        for line in f:
            line = line.strip()
            key, value = line.split(',')
            data_dict[key.strip()] = value.strip()
        print(f"read in {len(data_dict)} items (out of {len(concatenated_list)} files) into database")

for i in concatenated_list:
    #print(i)
    basename = os.path.basename(i)
    if basename in data_dict:
        continue
    #image = Image.open(i)
    image = cv2.imread(i)
    #gray_image = image.convert('L')
    gray_image = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    #inverted_image = ImageOps.invert(gray_image)
    _, mask = cv2.threshold(gray_image, 255 - 16, 255, cv2.THRESH_BINARY) # Invert the mask to make non-white pixels True
    mask = cv2.bitwise_not(mask) # Apply the mask to the grayscale image to turn non-white pixels black
    black_background_image = gray_image.copy()
    black_background_image[mask == 255] = 0
    inverted_image = cv2.bitwise_not(black_background_image)

    tdirpath = os.path.join('C:\\', 'Sandbox', 'pokedex-temp')
    os.makedirs(tdirpath, exist_ok=True)
    tpath = os.path.join(tdirpath, basename)
    #inverted_image.save(tpath)

    tgt_width = int(1080 * 2)
    tgt_height = int((tgt_width / 3) * 2)
    height, width = inverted_image.shape[:2]
    if width > tgt_width or height > tgt_height:
        scale_w = tgt_width / width
        scale_h = tgt_height / height
        scale = min(scale_w, scale_h) # Calculate the new dimensions
        new_width = int(width * scale)
        new_height = int(height * scale) # Resize the image
        resized_image = cv2.resize(inverted_image, (new_width, new_height), interpolation=cv2.INTER_AREA)
        inverted_image = resized_image

    cv2.imwrite(tpath, inverted_image)

    #text = pytesseract.image_to_string(tpath, lang='eng', config='--psm 6')
    reader = easyocr.Reader(['en'])
    result = reader.readtext(tpath)
    text = ' '.join([res[1] for res in result])
    text = text.replace('\n', ' ')

    if text is not None and len(text) > 0 and text.count(' ') <= 5 and text.count('-') <= 3:
        text = f"{basename},{text}"
    else:
        text = f"{basename},unknown"
    data_dict[basename] = text
    with open(db_file, "a") as f:
        f.write(text + "\n")
    print(text)
