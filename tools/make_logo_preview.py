# -*- coding: utf-8 -*-
"""生成 logo 对比预览图（旧 vs 新 + 实际使用尺寸下的效果）。"""
from PIL import Image, ImageDraw, ImageFont
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PUB = os.path.join(ROOT, 'public', 'images')
BAK = os.path.join(ROOT, '.logo_preview')
OUT = os.path.join(ROOT, '.logo_preview', 'logo-compare.png')

W = 1000
BG = (247, 247, 248)
FG = (40, 40, 42)
MUT = (140, 140, 148)
LINE = (222, 222, 226)

img = Image.new('RGB', (W, 790), BG)
d = ImageDraw.Draw(img)
# 用微软雅黑，保证中文标签不是方框
try:
    fb = ImageFont.truetype(r'C:\Windows\Fonts\msyhbd.ttc', 19)
    fs = ImageFont.truetype(r'C:\Windows\Fonts\msyh.ttc', 14)
except Exception:
    try:
        fb = ImageFont.truetype(r'C:\Windows\Fonts\segoeuib.ttf', 19)
        fs = ImageFont.truetype(r'C:\Windows\Fonts\segoeui.ttf', 14)
    except Exception:
        fb = fs = ImageFont.load_default()

y = 28
d.text((36, y), 'AlphaLom Logo — 新旧对比', font=fb, fill=FG)
y += 34
d.text((36, y), '旧版是上一代 FinFilo 的字标，品牌名已改，字体与配色也一并重做', font=fs, fill=MUT)
y += 34


def section(title, y):
    d.text((36, y), title, font=fb, fill=FG)
    y += 30
    d.line([(36, y), (W - 36, y)], fill=LINE, width=1)
    return y + 18


def panel(x, y, w, h, label, path, fit_bg=(255, 255, 255)):
    d.rectangle([x, y, x + w, y + h], fill=fit_bg, outline=LINE)
    if path and os.path.exists(path):
        im = Image.open(path).convert('RGBA')
        scale = min((w - 40) / im.width, (h - 40) / im.height, 1.6)
        im = im.resize((max(1, int(im.width * scale)), max(1, int(im.height * scale))), Image.LANCZOS)
        px = x + (w - im.width) // 2
        py = y + (h - im.height) // 2
        img.paste(im, (px, py), im)
    d.text((x + 12, y + h + 8), label, font=fs, fill=MUT)


# --- 横向字标对比 ---
y = section('横向字标（侧边栏 / 顶部使用）', y)
pw, ph = (W - 36 * 2 - 24) // 2, 150
panel(36, y, pw, ph, '旧：FinFilo（600×171）', os.path.join(BAK, 'alphalom-logo-220.png'))
panel(36 + pw + 24, y, pw, ph, '新：AlphaLom', os.path.join(PUB, 'alphalom-logo-220.png'))
y += ph + 42

# --- 侧边栏实际宽度 ---
y = section('侧边栏实际宽度 180px 下（1:1 像素）', y)
for i, (label, path) in enumerate([
    ('旧', os.path.join(BAK, 'alphalom-logo-220.png')),
    ('新', os.path.join(PUB, 'alphalom-logo-220.png')),
]):
    if os.path.exists(path):
        im = Image.open(path).convert('RGBA')
        im = im.resize((180, max(1, int(im.height * 180 / im.width))), Image.LANCZOS)
        py = y + i * 62
        d.text((36, py + 14), label, font=fs, fill=MUT)
        img.paste(im, (72, py), im)
y += 140

# --- App Icon / favicon ---
y = section('App Icon / favicon', y)
sizes = [16, 32, 48, 64, 96]
x = 36
for s in sizes:
    p = os.path.join(PUB, 'alphalom-logo-rect.png')
    im = Image.open(p).convert('RGBA').resize((s, s), Image.LANCZOS)
    img.paste(im, (x, y), im)
    d.text((x, y + s + 6), f'{s}px', font=fs, fill=MUT)
    x += s + 40

img.save(OUT)
print('saved', OUT, img.size)
