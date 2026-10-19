"""Одноразовый генератор иконки и заставки для buildozer.spec.

    python tools/make_icons.py

Создаёт icon.png (512x512) и presplash.png (1024x1536) в корне проекта.
Нужен только на этапе подготовки исходников к сборке, в APK не попадает
как зависимость (Pillow в requirements не входит).
"""

import os

from PIL import Image, ImageDraw, ImageFont

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

BG_TOP = (24, 34, 52)
BG_BOTTOM = (12, 17, 28)
ACCENT = (224, 141, 27)
TEXT = (245, 247, 250)

FONT_CANDIDATES = [
    "C:/Windows/Fonts/calibrib.ttf",
    "C:/Windows/Fonts/arialbd.ttf",
    "C:/Windows/Fonts/segoeuib.ttf",
    "C:/Windows/Fonts/tahoma.ttf",
]


def font(size):
    for path in FONT_CANDIDATES:
        if os.path.exists(path):
            return ImageFont.truetype(path, size)
    return ImageFont.load_default()


def gradient(size):
    w, h = size
    img = Image.new("RGB", size, BG_BOTTOM)
    top = Image.new("RGB", size, BG_TOP)
    mask = Image.new("L", size, 0)
    draw = ImageDraw.Draw(mask)
    for y in range(h):
        draw.line([(0, y), (w, y)], fill=int(255 * (1 - y / max(1, h))))
    img.paste(top, (0, 0), mask)
    return img


def rounded(img, radius):
    """Обрезать углы, подложив прозрачность."""
    w, h = img.size
    mask = Image.new("L", (w, h), 0)
    draw = ImageDraw.Draw(mask)
    draw.rounded_rectangle([0, 0, w - 1, h - 1], radius=radius, fill=255)
    out = img.convert("RGBA")
    out.putalpha(mask)
    return out


def centered(draw, text, size, font_obj, color):
    box = draw.textbbox((0, 0), text, font=font_obj)
    tw, th = box[2] - box[0], box[3] - box[1]
    return (size[0] // 2 - tw // 2 - box[0], size[1] // 2 - th // 2 - box[1])


def make_icon():
    size = (512, 512)
    img = rounded(gradient(size), 96)
    draw = ImageDraw.Draw(img)
    draw.rounded_rectangle([40, 40, 471, 471], radius=72, outline=ACCENT, width=10)
    f = font(190)
    pos = centered(draw, "ППУ", size, f, TEXT)
    draw.text(pos, "ППУ", font=f, fill=TEXT)
    f2 = font(46)
    box = draw.textbbox((0, 0), "ПОМОЩНИК", font=f2)
    draw.text(((size[0] - (box[2] - box[0])) // 2, 330), "ПОМОЩНИК", font=f2, fill=ACCENT)
    img.save(os.path.join(BASE, "icon.png"))

    presplash = gradient((1024, 1536))
    dp = ImageDraw.Draw(presplash)
    f_big = font(240)
    dp.text(centered(dp, "ППУ", (1024, 1536), f_big, TEXT), "ППУ", font=f_big, fill=TEXT)
    f_small = font(58)
    box = dp.textbbox((0, 0), "Помощник ППУ", font=f_small)
    dp.text(((1024 - (box[2] - box[0])) // 2, 1000), "Помощник ППУ", font=f_small, fill=ACCENT)
    presplash.save(os.path.join(BASE, "presplash.png"))

    print("icon.png / presplash.png записаны в", BASE)


if __name__ == "__main__":
    make_icon()
