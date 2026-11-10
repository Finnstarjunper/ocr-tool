# -*- coding: utf-8 -*-
"""
OCR 文字识别工具
================
识别图片中的文字（重点优化代码截图），识别结果可直接复制编辑。

功能：
- 打开图片 / 粘贴截图(Ctrl+V) / 拖拽图片导入
- 代码模式：保留缩进与空行、自动去除行号，等宽字体显示
- 普通模式：普通文字段落识别
- 结果可编辑、一键复制、保存为 TXT、识别后自动复制
- 自检模式：OCR文字识别.exe --selftest 图片 结果.txt
"""

import re
import sys
import time
import traceback
from pathlib import Path

from PIL import Image

APP_NAME = "OCR 文字识别工具"
APP_VERSION = "V2"  # 版本号：以后每代升级同步修改（打包脚本自动读取此值）
IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".bmp", ".webp", ".tif", ".tiff"}

# ============================================================
# OCR 核心（与界面无关）
# ============================================================

_engine = None


def get_engine():
    """延迟加载 RapidOCR 引擎（新版 rapidocr 包，PP-OCRv4/v5 模型，仅加载一次）"""
    global _engine
    if _engine is None:
        import logging
        from rapidocr import RapidOCR
        _engine = RapidOCR()
        # 引擎初始化会重设日志级别，必须在创建之后再压掉 INFO 日志
        logging.getLogger("RapidOCR").setLevel(logging.WARNING)
    return _engine


def _run_engine(engine, img):
    """统一引擎输出为 [(box4点, 文本, 置信度), ...]"""
    out = engine(img)
    boxes = getattr(out, "boxes", None)
    txts = getattr(out, "txts", None) or []
    scores = getattr(out, "scores", None) or []
    if boxes is None:
        return []
    raw = []
    for box, t, s in zip(boxes, txts, scores):
        raw.append(([[float(p[0]), float(p[1])] for p in box], str(t), float(s)))
    return raw


def preprocess(img: Image.Image) -> Image.Image:
    """预处理：转 RGB、过小图放大、过大图缩小，提升识别稳定性"""
    img = img.convert("RGB")
    w, h = img.size
    longest = max(w, h)
    if longest < 800:
        factor = min(3.0, 1200.0 / longest)
        img = img.resize((int(w * factor), int(h * factor)), Image.LANCZOS)
    elif longest > 4000:
        factor = 4000.0 / longest
        img = img.resize((int(w * factor), int(h * factor)), Image.LANCZOS)
    return img


def _is_line_number(text: str) -> bool:
    """判断是否为编辑器行号（1、2、3 或 1. / 2: 之类）"""
    return re.fullmatch(r"\d{1,4}[.:]?", text.strip()) is not None


_FULL2HALF = {"（": "(", "）": ")", "【": "[", "】": "]", "［": "[", "］": "]",
              "｛": "{", "｝": "}", "，": ",", "：": ":", "；": ";", "！": "!", "？": "?"}


def _fix_punct(line: str) -> str:
    """代码模式标点修正：紧邻 ASCII 字符的全角标点转半角（中文注释里的保持不动）"""
    def ascii_ish(ch):
        return bool(ch) and ord(ch) < 128 and (
            ch.isalnum() or ch in "()[]{}\"'`_.:=!<>+-*/%#&|,;?$~^\\")

    chars = list(line)
    for i, c in enumerate(chars):
        if c in _FULL2HALF:
            prev_ch = chars[i - 1] if i > 0 else ""
            next_ch = chars[i + 1] if i + 1 < len(chars) else ""
            if ascii_ish(prev_ch) or ascii_ish(next_ch):
                chars[i] = _FULL2HALF[c]
    return "".join(chars)


def reconstruct(raw_result, code_mode: bool = True):
    """
    把 OCR 返回的文本框重组为带换行/缩进的文本。
    raw_result: [(box4点, 文本, 置信度), ...]
    返回: (最终文本, 平均置信度, 识别行数, 低置信度行[(行号, 分数), ...])
    """
    if not raw_result:
        return "", 0.0, 0, []

    items = []
    for box, text, score in raw_result:
        text = str(text).strip()
        if not text:
            continue
        xs = [p[0] for p in box]
        ys = [p[1] for p in box]
        items.append({
            "text": text,
            "score": float(score),
            "x0": min(xs), "x1": max(xs),
            "y0": min(ys), "y1": max(ys),
            "cy": (min(ys) + max(ys)) / 2.0,
            "h": max(ys) - min(ys),
        })
    if not items:
        return "", 0.0, 0, []

    avg_score = sum(i["score"] for i in items) / len(items)

    # --- 按纵向位置归行 ---
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

    # --- 代码模式：去掉左侧孤立行号 ---
    if code_mode:
        removed = set()
        for ln in lines:
            if len(ln) >= 2 and _is_line_number(ln[0]["text"]):
                gap = ln[1]["x0"] - ln[0]["x1"]
                if gap > ln[0]["h"] * 0.7:
                    removed.add(id(ln[0]))
        if removed:
            lines = [[t for t in ln if id(t) not in removed] for ln in lines]
            lines = [ln for ln in lines if ln]

    if not lines:
        return "", avg_score, 0, []

    # --- 字符宽度估计（用于空格与缩进计算，CJK 按 2 个半角宽折算） ---
    def _units(s: str) -> float:
        return sum(2.0 if ord(c) > 0x2E7F else 1.0 for c in s)

    widths = []
    for ln in lines:
        for t in ln:
            u = _units(t["text"])
            if u >= 4:
                widths.append((t["x1"] - t["x0"]) / u)
    if widths:
        widths.sort()
        char_w = widths[len(widths) // 2]
    else:
        char_w = sum(t["h"] for ln in lines for t in ln) / len(items) * 0.55
    char_w = max(char_w, 1.0)

    # --- 空行检测：相邻行顶部间距明显大于常规行距 ---
    y_tops = [ln[0]["y0"] for ln in lines]
    gaps = [y_tops[i + 1] - y_tops[i] for i in range(len(y_tops) - 1)]
    if gaps:
        gs = sorted(gaps)
        median_gap = gs[len(gs) // 2]
    else:
        median_gap = 0

    base_left = min(ln[0]["x0"] for ln in lines)

    out_lines = []
    line_scores = []
    for idx, ln in enumerate(lines):
        if idx > 0 and median_gap > 0 and gaps[idx - 1] > median_gap * 1.65:
            out_lines.append("")
            line_scores.append(None)
        indent = 0
        if code_mode:
            indent = max(0, round((ln[0]["x0"] - base_left) / char_w))
        parts = []
        prev = None
        for t in ln:
            if prev is not None:
                gap = t["x0"] - prev["x1"]
                if gap > char_w * 0.25:
                    parts.append(" ")
            parts.append(t["text"])
            prev = t
        text_line = (" " * indent + "".join(parts)).rstrip()
        if code_mode:
            text_line = _fix_punct(text_line)
        out_lines.append(text_line)
        line_scores.append(min(t["score"] for t in ln))

    # 去掉首尾空行
    while out_lines and not out_lines[0].strip():
        out_lines.pop(0)
        line_scores.pop(0)
    while out_lines and not out_lines[-1].strip():
        out_lines.pop()
        line_scores.pop()

    low_lines = [(i + 1, round(s, 2)) for i, s in enumerate(line_scores)
                 if s is not None and s < 0.85]
    return "\n".join(out_lines), avg_score, len(lines), low_lines


def recognize(img: Image.Image, code_mode: bool = True) -> dict:
    """完整识别流程：预处理 -> OCR -> 文本重组"""
    engine = get_engine()
    img2 = preprocess(img)
    raw = _run_engine(engine, img2)
    text, score, n_lines, low_lines = reconstruct(raw, code_mode=code_mode)
    return {"text": text, "score": score, "lines": n_lines,
            "count": len(raw), "low_lines": low_lines}


# ============================================================
# 自检模式（打包后验证 exe 可用，无需界面）
# ============================================================

def run_selftest(argv) -> int:
    img_path = Path(argv[2])
    out_path = Path(argv[3]) if len(argv) > 3 else img_path.with_suffix(".ocr.txt")
    meta_path = Path(str(out_path) + ".meta.txt")
    try:
        img = Image.open(img_path)
        t0 = time.time()
        data = recognize(img, code_mode=True)
        elapsed = time.time() - t0
        out_path.write_text(data["text"], encoding="utf-8")
        meta_path.write_text(
            f"version={APP_VERSION}\nimage={img_path}\nsize={img.size}\nlines={data['lines']}\n"
            f"boxes={data['count']}\navg_score={data['score']:.4f}\n"
            f"low_lines={data['low_lines']}\n"
            f"elapsed={elapsed:.2f}s\nOK\n",
            encoding="utf-8",
        )
        return 0
    except Exception:
        out_path.write_text("ERROR\n" + traceback.format_exc(), encoding="utf-8")
        meta_path.write_text("FAILED\n" + traceback.format_exc(), encoding="utf-8")
        return 1


# ============================================================
# 图形界面
# ============================================================

def log_error(msg: str):
    """写错误日志（打包后的窗口程序没有控制台，排错靠它）"""
    for base in (Path(sys.argv[0]).resolve().parent,
                 Path.home() / "AppData" / "Local" / "Temp"):
        try:
            (base / "ocr_debug.log").write_text(msg, encoding="utf-8")
            return
        except Exception:
            continue


def run_gui(initial_path: str | None = None):
    from PyQt6.QtCore import Qt, QThread, QTimer, pyqtSignal, QMimeData
    from PyQt6.QtGui import (QPixmap, QImage, QIcon, QShortcut, QKeySequence,
                             QFont, QPalette, QColor, QTextCursor, QTextCharFormat)
    from PyQt6.QtWidgets import (
        QApplication, QMainWindow, QWidget, QLabel, QPushButton, QCheckBox,
        QPlainTextEdit, QHBoxLayout, QVBoxLayout, QFrame, QFileDialog,
        QMessageBox, QStatusBar, QSizePolicy, QTextEdit,
    )

    def resource_path(name: str) -> str:
        base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
        return str(base / name)

    class RecognizeWorker(QThread):
        done = pyqtSignal(dict)
        failed = pyqtSignal(str)

        def __init__(self, img, code_mode):
            super().__init__()
            self._img = img
            self._code_mode = code_mode

        def run(self):
            try:
                t0 = time.time()
                data = recognize(self._img, self._code_mode)
                data["seconds"] = time.time() - t0
                self.done.emit(data)
            except Exception as e:
                self.failed.emit(f"{e}\n{traceback.format_exc()}")

    class MainWindow(QMainWindow):
        def __init__(self, initial_path: str | None = None):
            super().__init__()
            self.setWindowTitle(f"{APP_NAME} {APP_VERSION}")
            self.resize(1120, 720)
            self.setWindowIcon(QIcon(resource_path("app.ico")))
            self.setAcceptDrops(True)

            self._image: Image.Image | None = None
            self._pixmap: QPixmap | None = None
            self._worker: RecognizeWorker | None = None

            # ---- 工具栏按钮 ----
            self.btn_open = QPushButton("打开图片")
            self.btn_paste = QPushButton("粘贴截图")
            self.btn_run = QPushButton("识 别")
            self.btn_copy = QPushButton("复制全部")
            self.btn_save = QPushButton("保存 TXT")

            self.chk_code = QCheckBox("代码模式（保留缩进·去行号）")
            self.chk_code.setChecked(True)
            self.chk_autocopy = QCheckBox("识别后自动复制")
            self.chk_autocopy.setChecked(True)

            for b in (self.btn_open, self.btn_paste, self.btn_save):
                b.setObjectName("btnLight")
            self.btn_run.setObjectName("btnPrimary")
            self.btn_copy.setObjectName("btnPrimary")

            top = QHBoxLayout()
            top.setSpacing(10)
            for b in (self.btn_open, self.btn_paste, self.btn_run,
                      self.btn_copy, self.btn_save):
                top.addWidget(b)
            top.addSpacing(12)
            top.addWidget(self.chk_code)
            top.addWidget(self.chk_autocopy)
            top.addStretch(1)

            # ---- 图片预览 ----
            self.preview = QLabel("将图片拖到这里\n或点击「打开图片 / 粘贴截图」")
            self.preview.setObjectName("preview")
            self.preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self.preview.setMinimumSize(340, 300)
            self.preview.setSizePolicy(
                QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

            self.hint = QLabel("支持 PNG / JPG / BMP / WebP，截图可直接 Ctrl+V 粘贴")
            self.hint.setObjectName("hint")
            self.hint.setAlignment(Qt.AlignmentFlag.AlignCenter)

            left = QVBoxLayout()
            left.setSpacing(8)
            left.addWidget(self.preview, 1)
            left.addWidget(self.hint)

            # ---- 结果区 ----
            self.result = QPlainTextEdit()
            self.result.setPlaceholderText(
                "识别结果会显示在这里，可直接编辑、Ctrl+A 全选、Ctrl+C 复制")
            self.result.setFont(QFont("Consolas", 11))

            right = QVBoxLayout()
            right.setSpacing(8)
            lbl = QLabel("识别结果（可编辑复制）")
            lbl.setObjectName("hint")
            right.addWidget(lbl)
            right.addWidget(self.result, 1)

            center = QHBoxLayout()
            center.setSpacing(12)
            center.addLayout(left, 4)
            center.addLayout(right, 6)

            # ---- 状态栏 ----
            self.status = QStatusBar()
            self.setStatusBar(self.status)
            self.status.showMessage(f"就绪（{APP_VERSION}）")

            # ---- 总布局 ----
            root = QWidget()
            vbox = QVBoxLayout(root)
            vbox.setContentsMargins(14, 12, 14, 10)
            vbox.setSpacing(10)
            vbox.addLayout(top)
            vbox.addLayout(center, 1)
            self.setCentralWidget(root)

            # ---- 信号 ----
            self.btn_open.clicked.connect(self.open_image)
            self.btn_paste.clicked.connect(self.paste_image)
            self.btn_run.clicked.connect(self.start_recognize)
            self.btn_copy.clicked.connect(self.copy_all)
            self.btn_save.clicked.connect(self.save_txt)

            QShortcut(QKeySequence.StandardKey.Open, self, self.open_image)
            QShortcut(QKeySequence("Ctrl+V"), self, self.paste_image)
            QShortcut(QKeySequence("Ctrl+Return"), self, self.start_recognize)
            QShortcut(QKeySequence("Ctrl+S"), self, self.save_txt)

            self.setStyleSheet(STYLE)

            if initial_path:
                QTimer.singleShot(250, lambda: self._open_and_run(initial_path))

        def _open_and_run(self, path: str):
            self.load_path(path)
            if self._image is not None:
                self.start_recognize()

        # ---------- 图片导入 ----------
        def open_image(self):
            path, _ = QFileDialog.getOpenFileName(
                self, "选择图片", "",
                "图片文件 (*.png *.jpg *.jpeg *.bmp *.webp *.tif *.tiff)")
            if path:
                self.load_path(path)

        def load_path(self, path: str):
            try:
                img = Image.open(path)
                img.load()
            except Exception as e:
                QMessageBox.warning(self, APP_NAME, f"无法打开图片：\n{e}")
                return
            self.set_image(img, Path(path).name)

        def set_image(self, img: Image.Image, name: str = "剪贴板截图"):
            self._image = img
            data = img.convert("RGB").tobytes("raw", "RGB")
            qimg = QImage(data, img.width, img.height,
                          img.width * 3, QImage.Format.Format_RGB888)
            self._pixmap = QPixmap.fromImage(qimg.copy())
            self.update_preview()
            self.status.showMessage(
                f"已加载：{name}（{img.width}x{img.height}），点击「识别」开始")

        def update_preview(self):
            if self._pixmap is None:
                return
            scaled = self._pixmap.scaled(
                self.preview.size(),
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation)
            self.preview.setPixmap(scaled)

        def resizeEvent(self, event):
            super().resizeEvent(event)
            self.update_preview()

        def paste_image(self):
            clipboard = QApplication.clipboard()
            mime: QMimeData = clipboard.mimeData()
            if mime.hasImage():
                qimg = clipboard.image()
                if qimg and not qimg.isNull():
                    img = Image.fromqimage(qimg) if hasattr(Image, "fromqimage") else self._qimg_to_pil(qimg)
                    self.set_image(img, "剪贴板截图")
                    return
            if mime.hasUrls():
                for url in mime.urls():
                    p = url.toLocalFile()
                    if Path(p).suffix.lower() in IMAGE_EXTS:
                        self.load_path(p)
                        return
            QMessageBox.information(self, APP_NAME, "剪贴板中没有图片，请先截图（Win+Shift+S）")

        @staticmethod
        def _qimg_to_pil(qimg) -> Image.Image:
            qimg = qimg.convertToFormat(QImage.Format.Format_RGBA8888)
            w, h = qimg.width(), qimg.height()
            buf = qimg.bits().asstring(qimg.sizeInBytes())
            return Image.frombuffer("RGBA", (w, h), buf, "raw", "RGBA", 0, 1).convert("RGB")

        # ---------- 拖拽 ----------
        def dragEnterEvent(self, event):
            if event.mimeData().hasUrls():
                for url in event.mimeData().urls():
                    if Path(url.toLocalFile()).suffix.lower() in IMAGE_EXTS:
                        event.acceptProposedAction()
                        return
            if event.mimeData().hasImage():
                event.acceptProposedAction()

        def dropEvent(self, event):
            mime = event.mimeData()
            if mime.hasUrls():
                for url in mime.urls():
                    p = url.toLocalFile()
                    if Path(p).suffix.lower() in IMAGE_EXTS:
                        self.load_path(p)
                        return
            if mime.hasImage():
                qimg = clipboard_image = QApplication.clipboard().image()
                if qimg is None or qimg.isNull():
                    qimg = mime.imageData()
                img = self._qimg_to_pil(qimg)
                self.set_image(img, "拖入的图片")

        # ---------- 识别 ----------
        def start_recognize(self):
            if self._image is None:
                QMessageBox.information(self, APP_NAME, "请先打开、粘贴或拖入一张图片")
                return
            if self._worker is not None and self._worker.isRunning():
                return
            self.btn_run.setEnabled(False)
            self.btn_run.setText("识别中…")
            self.status.showMessage("正在识别…")
            self._worker = RecognizeWorker(self._image, self.chk_code.isChecked())
            self._worker.done.connect(self.on_done)
            self._worker.failed.connect(self.on_failed)
            self._worker.start()

        def _highlight_low_lines(self, low_lines):
            """低置信度行加浅黄背景，提示需人工核对"""
            sels = []
            doc = self.result.document()
            for ln, _score in low_lines:
                block = doc.findBlockByNumber(ln - 1)
                if not block.isValid():
                    continue
                sel = QTextEdit.ExtraSelection()
                sel.cursor = QTextCursor(block)
                sel.cursor.movePosition(
                    QTextCursor.MoveOperation.EndOfBlock,
                    QTextCursor.MoveMode.KeepAnchor)
                fmt = QTextCharFormat()
                fmt.setBackground(QColor("#FFF3BF"))
                sel.format = fmt
                sels.append(sel)
            self.result.setExtraSelections(sels)

        def on_done(self, data: dict):
            self.btn_run.setEnabled(True)
            self.btn_run.setText("识 别")
            try:
                text = data["text"]
                self.result.setPlainText(text)
                low = data.get("low_lines") or []
                self._highlight_low_lines(low)
                if not text.strip():
                    self.status.showMessage("未识别到文字，请换更清晰的图片")
                    return
                msg = (f"识别完成：{data['lines']} 行 / {data['count']} 个文本块，"
                       f"平均置信度 {data['score']:.2f}，耗时 {data['seconds']:.1f}s")
                if low:
                    nums = "、".join(str(n) for n, _ in low[:8])
                    more = "…" if len(low) > 8 else ""
                    msg += f"；{len(low)} 行置信度较低（已黄色高亮，请核对）：第 {nums}{more} 行"
                if self.chk_autocopy.isChecked():
                    QApplication.clipboard().setText(text)
                    msg += "，结果已复制到剪贴板"
                self.status.showMessage(msg)
            except Exception:
                log_error(traceback.format_exc())
                self.status.showMessage("显示结果出错，详见 ocr_debug.log")

        def on_failed(self, errmsg: str):
            self.btn_run.setEnabled(True)
            self.btn_run.setText("识 别")
            self.status.showMessage("识别失败")
            log_error(errmsg)
            QMessageBox.critical(self, APP_NAME, f"识别出错：\n{errmsg[:500]}")

        # ---------- 输出 ----------
        def copy_all(self):
            text = self.result.toPlainText()
            if not text.strip():
                QMessageBox.information(self, APP_NAME, "还没有可复制的识别结果")
                return
            QApplication.clipboard().setText(text)
            self.status.showMessage("已复制全部结果到剪贴板")

        def save_txt(self):
            text = self.result.toPlainText()
            if not text.strip():
                QMessageBox.information(self, APP_NAME, "还没有可保存的识别结果")
                return
            path, _ = QFileDialog.getSaveFileName(
                self, "保存识别结果", "识别结果.txt", "文本文件 (*.txt)")
            if not path:
                return
            try:
                Path(path).write_text(text, encoding="utf-8")
                self.status.showMessage(f"已保存：{path}")
            except Exception as e:
                QMessageBox.warning(self, APP_NAME, f"保存失败：\n{e}")

    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setStyle("Fusion")

    # 强制浅色调色板：系统深色模式下 Qt 默认文字为白色，
    # 会白字白底看不见识别结果，这里显式固定为深色文字
    pal = app.palette()
    pal.setColor(QPalette.ColorRole.Window, QColor("#F7F9FC"))
    pal.setColor(QPalette.ColorRole.WindowText, QColor("#000000"))
    pal.setColor(QPalette.ColorRole.Base, QColor("#FFFFFF"))
    pal.setColor(QPalette.ColorRole.AlternateBase, QColor("#EEF3F9"))
    pal.setColor(QPalette.ColorRole.Text, QColor("#000000"))
    pal.setColor(QPalette.ColorRole.Button, QColor("#E8F1FB"))
    pal.setColor(QPalette.ColorRole.ButtonText, QColor("#2C6FBF"))
    pal.setColor(QPalette.ColorRole.BrightText, QColor("#C0392B"))
    pal.setColor(QPalette.ColorRole.Highlight, QColor("#BBD7F5"))
    pal.setColor(QPalette.ColorRole.HighlightedText, QColor("#12243B"))
    pal.setColor(QPalette.ColorRole.PlaceholderText, QColor("#8A97A8"))
    pal.setColor(QPalette.ColorRole.ToolTipBase, QColor("#FFFFFF"))
    pal.setColor(QPalette.ColorRole.ToolTipText, QColor("#000000"))
    app.setPalette(pal)

    win = MainWindow(initial_path)
    win.show()
    return app.exec()


STYLE = """
QMainWindow, QWidget { background: #F7F9FC; font-size: 13px; }
QPushButton {
    background: #E8F1FB; color: #2C6FBF; border: 1px solid #C3D9F2;
    padding: 7px 16px; border-radius: 6px; font-size: 13px;
}
QPushButton:hover { background: #D8E7F8; }
QPushButton:pressed { background: #C6DBF4; }
QPushButton#btnPrimary {
    background: #4A90D9; color: white; border: 1px solid #3B7CC4;
    font-weight: bold;
}
QPushButton#btnPrimary:hover { background: #5BA0E8; }
QPushButton#btnPrimary:pressed { background: #3B7CC4; }
QPushButton:disabled { background: #D5DCE6; color: #97A3B4; border: 1px solid #D5DCE6; }
QCheckBox { spacing: 6px; color: #44506A; }
QCheckBox:hover { color: #2C6FBF; }
QLabel#preview {
    background: #EEF3F9; border: 2px dashed #B9C6D8; border-radius: 8px;
    color: #8A97A8; font-size: 14px;
}
QLabel#hint { color: #8A97A8; font-size: 12px; }
QPlainTextEdit {
    font-family: Consolas, "Courier New", monospace;
    background: white; color: #000000;
    border: 1px solid #D6DEE8; border-radius: 8px;
    padding: 8px; selection-background-color: #BBD7F5; selection-color: #000000;
}
QStatusBar { background: #EFF3F8; color: #55617A; font-size: 12px; }
"""


def main():
    if len(sys.argv) >= 3 and sys.argv[1] == "--selftest":
        sys.exit(run_selftest(sys.argv))
    # 支持把图片路径作为参数传入（右键图片→打开方式），自动加载并识别
    initial = None
    for a in sys.argv[1:]:
        p = Path(a)
        if p.suffix.lower() in IMAGE_EXTS and p.exists():
            initial = str(p.resolve())
            break
    try:
        sys.exit(run_gui(initial))
    except Exception:
        traceback.print_exc()
        try:
            log_error(traceback.format_exc())
        except Exception:
            pass
        raise


if __name__ == "__main__":
    main()
