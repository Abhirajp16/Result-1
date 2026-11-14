import os, cv2, numpy as np
from PIL import Image, ImageDraw
EV = "captcha_eval"
amb = ["img_0012.png","img_0017.png","img_0025.png","img_0026.png","img_0039.png","img_0006.png"]
scale = 14
lab = 40
pad = 30
for i, fn in enumerate(amb):
    g = cv2.imread(os.path.join(EV, "bin", fn), cv2.IMREAD_GRAYSCALE)
    g = cv2.copyMakeBorder(g, 10, 10, pad, pad, cv2.BORDER_CONSTANT, value=0)
    im = Image.fromarray(g).convert("RGB")
    tw, th = im.width*scale, im.height*scale
    out = Image.new("RGB", (tw, th+lab), "white")
    d = ImageDraw.Draw(out)
    out.paste(im.resize((tw, th), Image.NEAREST), (0, lab))
    d.rectangle([0, 0, tw-1, lab-1], fill="#111827")
    d.text((10, 12), fn, fill="white")
    p = os.path.join(EV, f"pad_{i+1:02d}.png")
    out.save(p)
    print("wrote", p)
