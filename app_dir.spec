# -*- mode: python ; coding: utf-8 -*-
"""
PyInstaller 打包配置（文件夹版，启动快，日常使用）
- 版本号从 app.py 的 APP_VERSION 读取，产物名自动带 _V.. 后缀
- 裁剪：opengl32sw / Qt6Pdf / Qt6Network / Qt6Svg / Qt 翻译 / cv2/data /
        onnxruntime 工具模块 / 误带入的三方包 / cv2 视频解码
产物：dist/OCR文字识别_V../OCR文字识别_V...exe
"""
import re
from pathlib import Path

from PyInstaller.utils.hooks import collect_all, collect_dynamic_libs

APP_VERSION = re.search(r'APP_VERSION\s*=\s*"([^"]+)"',
                        Path("app.py").read_text(encoding="utf-8")).group(1)
NAME = f"OCR文字识别_{APP_VERSION}"

datas, binaries, hiddenimports = [], [], []

for pkg in ("rapidocr", "cv2", "shapely", "pyclipper"):
    try:
        d, b, h = collect_all(pkg)
        datas += d
        binaries += b
        hiddenimports += h
    except Exception as e:
        print(f"[spec] skip {pkg}: {e}")

# onnxruntime 只打包动态库，不打包 tools/transformers 等训练工具模块
try:
    binaries += collect_dynamic_libs("onnxruntime")
except Exception as e:
    print(f"[spec] onnxruntime libs: {e}")
hiddenimports += ["onnxruntime"]

datas += [("app.ico", ".")]
hiddenimports += ["rapidocr", "numpy", "PIL", "yaml", "omegaconf",
                  "colorlog", "tqdm", "six", "requests"]

# 运行时用不到的大文件/模块过滤
DROP_RE = re.compile(
    r"opengl32sw\.dll$"
    r"|Qt6Pdf\.dll$"
    r"|Qt6Network\.dll$"
    r"|Qt6Svg\.dll$"
    r"|videoio_ffmpeg"
    r"|[/\\]translations[/\\]"
    r"|[/\\]iconengines[/\\]"
    r"|[/\\]cv2[/\\]data[/\\]"
    r"|[/\\]onnxruntime[/\\](transformers|quantization|tools|datasets|backend)[/\\]"
    r"|[/\\]imageformats[/\\]q(?!ico)[^/\\]*\.dll$",
    re.I,
)

binaries = [b for b in binaries if not DROP_RE.search(b[0])]
datas = [d for d in datas if not DROP_RE.search(d[0])]

a = Analysis(
    ["app.py"],
    pathex=[],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        "tkinter", "matplotlib", "PyQt5", "PyQt6-WebEngine",
        "torch", "torchvision", "torchaudio", "torch.distributed",
        "scipy", "pandas", "botocore", "boto3", "av", "jedi",
        "IPython", "cryptography", "lxml", "pydantic", "qh3",
        "email_validator", "uvicorn", "fastapi", "flask", "django",
        "pytest",
        "onnx", "zmq", "zstandard", "google", "brotli", "brotlicffi",
        "_brotli", "protobuf", "grpc", "tensorboard", "notebook",
        "onnxruntime.training", "onnxruntime.tools",
        "onnxruntime.transformers", "onnxruntime.quantization",
    ],
    noarchive=False,
)

# 钩子可能在 Analysis 阶段重新带入大文件，再过滤一遍
a.binaries = [b for b in a.binaries if not DROP_RE.search(b[0])]
a.datas = [d for d in a.datas if not DROP_RE.search(d[0])]

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name=NAME,
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    icon="app.ico",
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name=NAME,
)
