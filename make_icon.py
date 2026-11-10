# -*- coding: utf-8 -*-
"""生成应用图标 app.ico"""
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

HERE = Path(__file__).resolve().parent
SIZE = 256

img = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))
d = ImageDraw.Draw(img)

# 圆角矩形底（淡蓝色主色调）
d.rounded_rectangle([10, 10, 246, 246], radius=52, fill=(74, 144, 217, 255))

# 取景框
d.rounded_rectangle([58, 52, 198, 170], radius=18,
                    outline=(255, 255, 255, 255), width=12)
# 扫描线
d.rectangle([76, 104, 180, 122], fill=(255, 255, 255, 255))
# 取景框角点装饰
for cx, cy in [(58, 52), (198, 52), (58, 170), (198, 170)]:
    d.ellipse([cx - 9, cy - 9, cx + 9, cy + 9], fill=(255, 255, 255, 255))

# "OCR" 文字
font_path = Path("C:/Windows/Fonts/arialbd.ttf")
try:
    font = ImageFont.truetype(str(font_path), 64)
except Exception:
    font = ImageFont.load_default()
d.text((128, 210), "OCR", font=font, fill=(255, 255, 255, 255), anchor="mm")

out = HERE / "app.ico"
img.save(out, format="ICO",
         sizes=[(256, 256), (128, 128), (64, 64), (48, 48), (32, 32), (16, 16)])
print("icon saved:", out)
