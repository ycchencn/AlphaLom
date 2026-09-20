# -*- coding: utf-8 -*-
"""渲染侧边栏 + 登录页的 logo 使用效果预览（模拟实际界面）。"""
from PIL import Image, ImageDraw, ImageFont
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PUB = os.path.join(ROOT, 'public', 'images')
OUT = os.path.join(ROOT, '.logo_preview', 'logo-in-context.png')

W, H = 1000, 560
img = Image.new('RGB', (W, H), (238, 239, 242))
d = ImageDraw.Draw(img)
fb = ImageFont.truetype(r'C:\Windows\Fonts\msyhbd.ttc', 15)
fs = ImageFont.truetype(r'C:\Windows\Fonts\msyh.ttc', 13)

# ---------- 左：侧边栏（深色）实际宽度 16rem = 256px ----------
SB_W = 256
d.rectangle([0, 0, SB_W, H], fill=(37, 43, 52))
d.text((16, 12), '侧边栏 256px（实际渲染）', font=fs, fill=(150, 155, 165))

logo = Image.open(os.path.join(PUB, 'alphalom-logo-220.png')).convert('RGBA')
# CSS: height 1.6rem == 25.6px
lh = 26
logo = logo.resize((max(1, round(lh * logo.width / logo.height)), lh), Image.LANCZOS)
img.paste(logo, ((SB_W - logo.width) // 2, 48), logo)
d.line([(16, 48 + logo.height + 24), (SB_W - 16, 48 + logo.height + 24)], fill=(70, 76, 86))

# 菜单条示意
menus = ['市场总览', '股票池', 'ETF 监控', '组合管理', '量化信号', '系统日志']
y = 48 + logo.height + 44
for m in menus:
    d.rounded_rectangle([12, y, SB_W - 12, y + 34], radius=6,
                        fill=(52, 60, 72) if m == 'ETF 监控' else None)
    d.text((26, y + 9), m, font=fs, fill=(220, 224, 230) if m == 'ETF 监控' else (170, 176, 186))
    y += 40

# ---------- 右：浏览器标签页 favicon + 登录页 ----------
RX = SB_W + 30
d.text((RX, 12), '浏览器标签页 favicon（16px / 32px）', font=fs, fill=(110, 114, 122))
tab = Image.new('RGBA', (300, 34), (255, 255, 255, 255))
td = ImageDraw.Draw(tab)
td.rounded_rectangle([0, 0, 299, 33], radius=8, fill=(255, 255, 255))
ico = Image.open(os.path.join(PUB, 'favicon.ico'))
ico16 = ico.convert('RGBA').resize((16, 16), Image.LANCZOS)
tab.paste(ico16, (10, 9), ico16)
td.text((34, 9), 'AlphaLom', font=fs, fill=(60, 64, 70))
img.paste(tab, (RX, 34), tab)

ico32 = Image.open(os.path.join(PUB, 'alphalom-logo-rect.png')).convert('RGBA').resize((32, 32), Image.LANCZOS)
img.paste(ico32, (RX + 320, 34), ico32)
d.text((RX, 82), '登录页 logo', font=fs, fill=(110, 114, 122))

login = Image.new('RGB', (620, 330), (255, 255, 255))
ld = ImageDraw.Draw(login)
login_logo = Image.open(os.path.join(PUB, 'alphalom-logo.png')).convert('RGBA')
# CSS: height 2.2rem == 35.2px
llh = 35
login_logo = login_logo.resize((max(1, round(llh * login_logo.width / login_logo.height)), llh), Image.LANCZOS)
login.paste(login_logo, ((620 - login_logo.width) // 2, 46), login_logo)
ld.text((0, 46 + login_logo.height + 22), 'Welcome to AlphaLom!', font=fb, fill=(30, 32, 36), anchor='ma')
ld.text((0, 46 + login_logo.height + 52), 'Sign in to System', font=fs, fill=(150, 154, 160), anchor='ma')
ld.rectangle([90, 46 + login_logo.height + 92, 530, 46 + login_logo.height + 128], outline=(220, 222, 226), width=1)
ld.text((104, 46 + login_logo.height + 102), 'Email address', font=fs, fill=(175, 178, 184))
img.paste(login, (RX, 104))
d.rectangle([RX, 104, RX + 620, 104 + 330], outline=(214, 216, 220))

img.save(OUT)
print('saved', OUT, img.size)
