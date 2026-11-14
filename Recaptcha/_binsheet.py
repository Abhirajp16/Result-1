import os, cv2
from PIL import Image, ImageDraw
EV = "captcha_eval"
os.makedirs(os.path.join(EV, "bin"), exist_ok=True)
files = sorted(f for f in os.listdir(EV) if f.startswith("img_") and f.endswith(".png"))
tiles = []
for fn in files:
    g = cv2.imread(os.path.join(EV, fn), cv2.IMREAD_GRAYSCALE)
    g = cv2.GaussianBlur(g, (5,5), 0)
    _, b = cv2.threshold(g, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
    out = os.path.join(EV, "bin", fn)
    cv2.imwrite(out, b)
    tiles.append((fn, b.shape[1], b.shape[0]))
print("native size:", tiles[0][1], "x", tiles[0][2], "count:", len(tiles))
scale = 8
cols, rows, per = 2, 3, 6
tw, th = tiles[0][1]*scale, tiles[0][2]*scale
lab = 34
for s in range(0, len(tiles), per):
    chunk = tiles[s:s+per]
    sheet = Image.new("RGB", (cols*tw, rows*(th+lab)), "white")
    d = ImageDraw.Draw(sheet)
    for k, (fn, w, h) in enumerate(chunk):
        im = Image.open(os.path.join(EV, "bin", fn)).convert("RGB").resize((tw, th), Image.NEAREST)
        c, r = k % cols, k // cols
        x, y = c*tw, r*(th+lab)
        sheet.paste(im, (x, y+lab))
        d.rectangle([x, y, x+tw-1, y+lab-1], fill="#111827")
        d.text((x+8, y+9), fn, fill="white")
    p = os.path.join(EV, f"binsheet_{s//per+1:02d}.png")
    sheet.save(p)
    print("wrote", p)
