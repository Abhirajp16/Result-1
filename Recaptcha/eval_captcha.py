"""Evaluate the trained CAPTCHA model on freshly downloaded VTU CAPTCHAs.

Produces the numbers used in the project report:
  * validation images
  * exact-match accuracy
  * character error rate (CER)

Usage
-----
  python eval_captcha.py download 40     # fetch N fresh CAPTCHAs -> captcha_eval/img_XXXX.png
  python eval_captcha.py sheet           # contact sheets      -> captcha_eval/sheet_N.png
  python eval_captcha.py predict         # run the model       -> captcha_eval/preds.csv
  python eval_captcha.py score           # labels.csv + preds.csv -> accuracy / CER

`labels.csv` is hand-annotated (file,label), one row per image.
"""

import os
import sys
import csv

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
EVAL_DIR = os.path.join(BASE_DIR, "captcha_eval")

PAGE_URL = "https://results.vtu.ac.in/JJEcbcs25/index.php"
BASE_URL = "https://results.vtu.ac.in/"

IMG_WIDTH = 160
IMG_HEIGHT = 75


# --------------------------------------------------------------------------- #
# 1. download fresh CAPTCHAs
# --------------------------------------------------------------------------- #
def download(n):
    import requests
    import urllib3
    from bs4 import BeautifulSoup
    from urllib.parse import urljoin

    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
    os.makedirs(EVAL_DIR, exist_ok=True)

    saved = 0
    with requests.Session() as session:
        session.headers.update({
            "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                           "AppleWebKit/537.36 (KHTML, like Gecko) "
                           "Chrome/91.0.4472.124 Safari/537.36")
        })
        for i in range(n):
            try:
                page = session.get(PAGE_URL, verify=False, timeout=20)
                page.raise_for_status()
                soup = BeautifulSoup(page.text, "html.parser")
                img_tag = soup.find("img", src=lambda s: s and "vtu_captcha.php" in s)
                if not img_tag:
                    print(f"[{i+1}/{n}] no CAPTCHA <img> on page - skipped")
                    continue
                url = urljoin(BASE_URL, img_tag["src"])
                img = session.get(url, verify=False, timeout=20)
                img.raise_for_status()
                saved += 1
                path = os.path.join(EVAL_DIR, f"img_{saved:04d}.png")
                with open(path, "wb") as f:
                    f.write(img.content)
                print(f"[{saved}/{n}] saved {path}")
            except Exception as e:                       # noqa: BLE001
                print(f"[{i+1}/{n}] error: {e}")
    print(f"\nDownloaded {saved} CAPTCHA images into {EVAL_DIR}")


# --------------------------------------------------------------------------- #
# 2. contact sheets for hand labelling
# --------------------------------------------------------------------------- #
def sheet(cols=2, rows=3, scale=6, per_sheet=6):
    from PIL import Image, ImageDraw

    files = sorted(f for f in os.listdir(EVAL_DIR)
                   if f.startswith("img_") and f.endswith(".png"))
    if not files:
        print("No images - run 'download' first.")
        return

    probe = Image.open(os.path.join(EVAL_DIR, files[0]))
    tw, th = probe.width * scale, probe.height * scale
    label_h = 34

    for s in range(0, len(files), per_sheet):
        chunk = files[s:s + per_sheet]
        sheet_img = Image.new("RGB", (cols * tw, rows * (th + label_h)), "white")
        draw = ImageDraw.Draw(sheet_img)
        for k, fn in enumerate(chunk):
            im = Image.open(os.path.join(EVAL_DIR, fn)).convert("RGB")
            im = im.resize((tw, th), Image.LANCZOS)
            c, r = k % cols, k // cols
            x, y = c * tw, r * (th + label_h)
            sheet_img.paste(im, (x, y + label_h))
            draw.rectangle([x, y, x + tw - 1, y + label_h - 1], fill="#111827")
            draw.text((x + 8, y + 9), fn, fill="white")
        out = os.path.join(EVAL_DIR, f"sheet_{s // per_sheet + 1:02d}.png")
        sheet_img.save(out)
        print("wrote", out)


# --------------------------------------------------------------------------- #
# 3. predict with the trained model
# --------------------------------------------------------------------------- #
def predict():
    os.environ.setdefault("CUDA_VISIBLE_DEVICES", "-1")
    import cv2
    import numpy as np
    import tensorflow as tf
    from tensorflow.keras import backend as K

    model_path = os.path.join(BASE_DIR, "vtu_captcha_predictor.h5")
    CHARACTERS = "0123456789abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ"
    num_to_char = {i: c for i, c in enumerate(CHARACTERS)}

    model = tf.keras.models.load_model(model_path, compile=False)
    files = sorted(f for f in os.listdir(EVAL_DIR)
                   if f.startswith("img_") and f.endswith(".png"))
    if not files:
        print("No images - run 'download' first.")
        return

    imgs = []
    keep = []
    for fn in files:
        img = cv2.imread(os.path.join(EVAL_DIR, fn), cv2.IMREAD_GRAYSCALE)
        if img is None:
            continue
        img = cv2.GaussianBlur(img, (5, 5), 0)
        _, img = cv2.threshold(img, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
        img = cv2.resize(img, (IMG_WIDTH, IMG_HEIGHT))
        img = img / 255.0
        imgs.append(np.expand_dims(img, axis=-1))
        keep.append(fn)

    x = np.array(imgs)
    pred = model.predict(x, verbose=0)
    input_len = np.ones(pred.shape[0]) * pred.shape[1]
    decoded = K.ctc_decode(pred, input_length=input_len, greedy=True)[0][0]

    out = os.path.join(EVAL_DIR, "preds.csv")
    with open(out, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["file", "prediction"])
        for row, fn in zip(decoded, keep):
            text = ""
            for v in row.numpy():
                if v == -1:
                    break
                if 0 <= v < len(num_to_char):
                    text += num_to_char[int(v)]
            w.writerow([fn, text])
            print(f"{fn} -> {text}")
    print(f"\nWrote {out} ({len(keep)} images)")


# --------------------------------------------------------------------------- #
# 4. score against the hand labels
# --------------------------------------------------------------------------- #
def score():
    import editdistance

    def load(path):
        d = {}
        if not os.path.exists(path):
            return d
        with open(path, newline="", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                key = row.get("file") or row.get("image")
                val = (row.get("label") or row.get("prediction") or "").strip()
                if key:
                    d[key.strip()] = val
        return d

    labels = load(os.path.join(EVAL_DIR, "labels.csv"))
    preds = load(os.path.join(EVAL_DIR, "preds.csv"))

    pairs = [(f, labels[f], preds[f]) for f in labels if f in preds]
    if not pairs:
        print("No overlapping rows between labels.csv and preds.csv.")
        return

    exact = sum(1 for _, t, p in pairs if t == p)
    cer = sum(editdistance.eval(t, p) / max(1, len(t)) for _, t, p in pairs) / len(pairs)

    print(f"Validation images : {len(pairs)}")
    print(f"Exact-match accuracy: {100.0 * exact / len(pairs):.1f} %")
    print(f"Character error rate: {100.0 * cer:.2f} %")
    print("\nWrong ones:")
    for fn, t, p in pairs:
        if t != p:
            print(f"  {fn}: true={t!r} pred={p!r}")


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "score"
    if cmd == "download":
        download(int(sys.argv[2]) if len(sys.argv) > 2 else 40)
    elif cmd == "sheet":
        sheet()
    elif cmd == "predict":
        predict()
    elif cmd == "score":
        score()
    else:
        print(__doc__)
