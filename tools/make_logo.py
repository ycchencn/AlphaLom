# -*- coding: utf-8 -*-
"""
AlphaLom Logo 生成：Wordmark（横向）+ App Icon（方形）
风格延续旧 FinFilo logo：衬线体、分色、干净利落。
"""
from PIL import Image, ImageDraw, ImageFont
import os

OUT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'public', 'images')
FONTS = r'C:\Windows\Fonts'

# 品牌配色
RED = (214, 60, 51)      # 主色，沿用旧 logo 的红
INK = (26, 26, 26)       # 深墨色

SS = 4                    # 超采样倍数，抗锯齿


def load(name, size):
    return ImageFont.truetype(os.path.join(FONTS, name), size)


def text_size(draw, s, font):
    box = draw.textbbox((0, 0), s, font=font)
    return box[2] - box[0], box[3] - box[1], box


def make_wordmark(path, height=220, word='AlphaLom', split=5,
                  font_name='georgia.ttf', pad_x=24, pad_y=18):
    """
    生成横向 wordmark。
    split: 前 N 个字符用主色（Alpha），其余用墨色（Lom）。
    """
    f = load(font_name, height * SS)
    canvas = Image.new('RGBA', (10, 10))
    d = ImageDraw.Draw(canvas)

    a, b = word[:split], word[split:]
    wa, ha, bba = text_size(d, a, f)
    wb, hb, bbb = text_size(d, b, f)

    gap = int(height * SS * 0.01)          # 分色两段之间留一点自然间距
    total_w = wa + gap + wb
    asc, desc = f.getmetrics()
    total_h = asc + desc

    W = total_w + pad_x * 2 * SS
    H = total_h + pad_y * 2 * SS
    img = Image.new('RGBA', (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)

    # 用基线对齐两段，保证「Alpha」与「Lom」在同一条基线上
    baseline = pad_y * SS + asc
    x = pad_x * SS
    d.text((x - bba[0], baseline - bba[3]), a, font=f, fill=RED)
    x += wa + gap
    d.text((x - bbb[0], baseline - bbb[3]), b, font=f, fill=INK)

    img = img.crop(img.getbbox())
    return img.resize((max(1, img.width // SS), max(1, img.height // SS)), Image.LANCZOS)


def make_icon(path, size=200, letter='A', font_name='georgiab.ttf',
              bg=(214, 60, 51), fg=(255, 255, 255), radius_ratio=0.22,
              glyph_ratio=0.58):
    """生成方形 App Icon：圆角底 + 单字母。"""
    S = size * SS
    img = Image.new('RGBA', (S, S), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    r = int(S * radius_ratio)
    d.rounded_rectangle([0, 0, S - 1, S - 1], radius=r, fill=bg + (255,))

    f = load(font_name, int(S * glyph_ratio))
    bb = d.textbbox((0, 0), letter, font=f)
    w, h = bb[2] - bb[0], bb[3] - bb[1]
    # 视觉居中：字母的几何中心略低于字面中心，向上抬一点更平衡
    x = (S - w) / 2 - bb[0]
    y = (S - h) / 2 - bb[1] - S * 0.015
    d.text((x, y), letter, font=f, fill=fg + (255,))

    return img.resize((size, size), Image.LANCZOS)


def make_icon_multisize(path, sizes=(16, 32, 48, 64, 200)):
    """
    favicon 多尺寸：小尺寸（<=32px）换用更粗的衬线加重、放大字面，
    否则 Georgia 的细衬线在 16px 下会糊成一团。

    PNG 单帧格式无法容纳多尺寸，故这里只产出最大尺寸的单帧图；
    真正的多尺寸请见 make_favicon_ico()。
    """
    biggest = max(sizes)
    f = make_icon(None, size=biggest, font_name='georgiab.ttf',
                  glyph_ratio=0.58, radius_ratio=0.22)
    f.save(path)
    return f


def make_favicon_ico(path, sizes=(16, 24, 32, 48, 64)):
    """.ico 支持多尺寸内嵌，浏览器按显示尺寸取最合适的一帧。"""
    frames = []
    for s in sizes:
        ratio = 0.74 if s <= 32 else 0.58      # 小尺寸放大字面，避免细衬线糊掉
        radius = 0.24 if s <= 32 else 0.22
        frames.append(make_icon(None, size=s, font_name='georgiab.ttf',
                                glyph_ratio=ratio, radius_ratio=radius))
    frames[0].save(path, format='ICO',
                   sizes=[(f.width, f.height) for f in frames])
    return frames


if __name__ == '__main__':
    os.makedirs(OUT, exist_ok=True)

    # 1) 侧边栏 wide logo（侧边栏以 180px 宽显示，这里留足 2x 冗余给高清屏）
    wm = make_wordmark(None, height=210, split=5, pad_x=10, pad_y=24)
    wm.save(os.path.join(OUT, 'alphalom-logo-220.png'))
    print('alphalom-logo-220.png', wm.size, '-> 180px 显示时高约', round(180 * wm.height / wm.width))

    # 2) 通用 wordmark
    wm2 = wm.resize((wm.width // 2, wm.height // 2), Image.LANCZOS)
    wm2.save(os.path.join(OUT, 'alphalom-logo.png'))
    print('alphalom-logo.png', wm2.size)

    # 3) favicon（PNG，浏览器普遍支持）
    ic = make_icon_multisize(os.path.join(OUT, 'alphalom-logo-rect.png'))
    print('alphalom-logo-rect.png', ic.size)

    # 3b) 多尺寸 .ico，兼顾 16px 标签页与高分屏
    frames = make_favicon_ico(os.path.join(OUT, 'favicon.ico'))
    print('favicon.ico', [f.size for f in frames])

    # 4) 单独产出一枚 512 高清方形图标，供桌面/应用图标使用
    make_icon(None, size=512, glyph_ratio=0.58).save(
        os.path.join(OUT, 'alphalom-icon-512.png'))
    print('alphalom-icon-512.png (512, 512)')
