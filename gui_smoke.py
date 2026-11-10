# -*- coding: utf-8 -*-
"""GUI 冒烟测试：启动界面 -> 截屏 -> 关闭
用法：python gui_smoke.py [可执行文件或脚本路径]
"""
import subprocess
import sys
import time
from pathlib import Path

from PIL import ImageGrab

HERE = Path(__file__).resolve().parent
target = sys.argv[1] if len(sys.argv) > 1 else str(HERE / "app.py")
extra = sys.argv[2:]
cmd = ([target] if target.lower().endswith(".exe") else [sys.executable, target]) + extra
proc = subprocess.Popen(cmd)
time.sleep(14)
img = ImageGrab.grab()
out = HERE / "gui_shot.png"
img.save(out)
print("screenshot saved:", out, "size:", img.size)
proc.terminate()
try:
    proc.wait(timeout=5)
except Exception:
    proc.kill()
print("app terminated, exit code:", proc.returncode)
err = HERE / "ocr_error.log"
print("error log exists:", err.exists())
