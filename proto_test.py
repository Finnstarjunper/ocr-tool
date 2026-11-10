# -*- coding: utf-8 -*-
"""原型验证：RapidOCR 对深色主题代码截图的识别效果"""
import re
from PIL import Image
import numpy as np
from rapidocr_onnxruntime import RapidOCR

IMG = r"C:\Users\k1324\Desktop\htmlppt\ocr-tool\test_code.png"

ocr = RapidOCR()
img = Image.open(IMG).convert("RGB")
print("image size:", img.size)

res, elapse = ocr(IMG)
print("elapse:", elapse)
print("=== boxes ===")
items = []
for box, text, score in (res or []):
    xs = [p[0] for p in box]
    ys = [p[1] for p in box]
    it = dict(text=text, score=float(score), x0=min(xs), x1=max(xs),
              y0=min(ys), y1=max(ys), cy=(min(ys) + max(ys)) / 2,
              h=max(ys) - min(ys))
    items.append(it)
    print(f"x[{it['x0']:6.1f},{it['x1']:6.1f}] y[{it['y0']:6.1f},{it['y1']:6.1f}] "
          f"h={it['h']:5.1f} {score:.2f} | {text}")

# ---------- 行重建 ----------
items.sort(key=lambda t: (t["y0"], t["x0"]))
lines = []
cur = []
for it in items:
    if not cur:
        cur = [it]
        continue
    ref_cy = sum(x["cy"] for x in cur) / len(cur)
    ref_h = sum(x["h"] for x in cur) / len(cur)
    if abs(it["cy"] - ref_cy) <= max(ref_h, it["h"]) * 0.6:
        cur.append(it)
    else:
        lines.append(cur)
        cur = [it]
if cur:
    lines.append(cur)
for ln in lines:
    ln.sort(key=lambda t: t["x0"])

# ---------- 行号去除 ----------
def is_lineno(t):
    return re.fullmatch(r"\d{1,3}[.:]?", t["text"].strip()) is not None

removed = set()
for ln in lines:
    if len(ln) >= 2 and is_lineno(ln[0]):
        gap = ln[1]["x0"] - ln[0]["x1"]
        if gap > ln[0]["h"] * 0.7:
            removed.add(id(ln[0]))
print("lineno removed:", len(removed))

clean_lines = [[t for t in ln if id(t) not in removed] for ln in lines]
clean_lines = [ln for ln in clean_lines if ln]

# ---------- 字符宽度估计 ----------
widths = []
for ln in clean_lines:
    for t in ln:
        if len(t["text"]) >= 4:
            widths.append((t["x1"] - t["x0"]) / len(t["text"]))
char_w = sorted(widths)[len(widths) // 2] if widths else 8.0
print("estimated char width:", round(char_w, 2))

# ---------- 缩进还原 ----------
lefts = [ln[0]["x0"] for ln in clean_lines]
base_left = min(lefts)
out_lines = []
prev_y1 = None
for ln in clean_lines:
    left = ln[0]["x0"]
    indent = max(0, round((left - base_left) / char_w))
    parts = []
    prev = None
    for t in ln:
        if prev is not None:
            gap = t["x0"] - prev["x1"]
            if gap > char_w * 0.25:
                parts.append(" ")
        parts.append(t["text"])
        prev = t
    line_text = " " * indent + "".join(parts)
    # 空行提示
    if prev_y1 is not None:
        gap_y = ln[0]["y0"] - prev_y1
        if gap_y > ln[0]["h"] * 1.9:
            out_lines.append("")
    out_lines.append(line_text)
    prev_y1 = ln[-1]["y1"]

print("=== reconstructed ===")
print("\n".join(out_lines))
print("=== avg score:", round(sum(i['score'] for i in items) / max(1, len(items)), 3))

# PIL 输入对比
res2, _ = ocr(img)
texts1 = [t[1] for t in (res or [])]
texts2 = [t[1] for t in (res2 or [])]
print("path vs PIL input identical:", texts1 == texts2)

# 反色预处理测试
arr = np.array(img)
lum = arr.mean()
print("mean luminance:", round(float(lum), 1))
inv = Image.fromarray(255 - arr)
res3, _ = ocr(inv)
texts3 = [t[1] for t in (res3 or [])]
print("inverted result:", texts3)
print("inverted identical:", texts1 == texts3)
