import os
from PIL import Image, ImageDraw
EV = "captcha_eval"
amb = ["img_0006.png","img_0007.png","img_0008.png","img_0011.png","img_0012.png","img_0015.png",
       "img_0017.png","img_0025.png","img_0026.png","img_0033.png","img_0039.png","img_0014.png"]
scale = 10
per = 3
lab = 36
for s in range(0, len(amb), per):
    chunk = amb[s:s+per]
    ims = [Image.open(os.path.join(EV, "bin", fn)).convert("RGB") for fn in chunk]
    tw, th = ims[0].width*scale, ims[0].height*scale
    out = Image.new("RGB", (tw, len(chunk)*(th+lab)), "white")
    d = ImageDraw.Draw(out)
    for k, (fn, im) in enumerate(zip(chunk, ims)):
        im = im.resize((tw, th), Image.NEAREST)
        y = k*(th+lab)
        out.paste(im, (0, y+lab))
        d.rectangle([0, y, tw-1, y+lab-1], fill="#111827")
        d.text((10, y+10), fn, fill="white")
    p = os.path.join(EV, f"zoom_{s//per+1:02d}.png")
    out.save(p)
    print("wrote", p)
