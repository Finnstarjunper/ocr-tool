# -*- mode: python ; coding: utf-8 -*-
"""
PyInstaller 打包配置（单文件版，便于分发）
- 版本号从 app.py 的 APP_VERSION 读取，产物名自动带 _V.. 后缀
- 与文件夹版相同的裁剪策略
产物：dist/OCR文字识别_V...exe
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

try:
    binaries += collect_dynamic_libs("onnxruntime")
except Exception as e:
    print(f"[spec] onnxruntime libs: {e}")
hiddenimports += ["onnxruntime"]

datas += [("app.ico", ".")]
hiddenimports += ["rapidocr", "numpy", "PIL", "yaml", "omegaconf",
                  "colorlog", "tqdm", "six", "requests"]

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

a.binaries = [b for b in a.binaries if not DROP_RE.search(b[0])]
a.datas = [d for d in a.datas if not DROP_RE.search(d[0])]

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name=NAME,
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    icon="app.ico",
)
