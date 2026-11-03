"""ShiftWheel v3.5 - hold Shift + drag files in Explorer -> radial convert menu (Windows).
Setup:    pip install PySide6 pynput Pillow pypdf pymupdf openpyxl
Optional: ffmpeg on PATH (video/audio)
          pillow-heif          (HEIC/HEIF images)
          pytesseract          (OCR – also needs Tesseract OCR installed)
Run:      double-click start_shiftwheel.bat (runs hidden in the tray; right-click the icon for settings,
          hotkey, debugger and quit). Or: pythonw shiftwheel.py
Everything runs locally; results are saved next to originals (or in Converted).
Image operations use the first frame/page of animated or multipage images.
"""

import sys, os, math, json, time, ctypes, shutil, subprocess, threading, traceback
import tempfile, re
from pathlib import Path
from functools import partial


def _startup_fail(ex):
    """ShiftWheel can't even start: explain why in a text file + a message box."""
    import platform

    pkg = str(getattr(ex, "name", "") or ex).split(".")[0]
    cmd = f'"{sys.executable}" -m pip install PySide6 pynput Pillow pypdf pymupdf openpyxl'
    text = "\n".join(
        [
            "SHIFTWHEEL COULD NOT START",
            time.strftime("%Y-%m-%d %H:%M:%S"),
            "",
            "WHY (plain English):",
            f"A required library ('{pkg}') is missing or could not load in this Python.",
            "This usually means pip installed it into a different Python than the one you launched.",
            "",
            "FIX: open Command Prompt and run this exact line, then start ShiftWheel again:",
            cmd,
            "",
            "If the install says 'no matching distribution', your Python version is too new/old for PySide6;",
            "install Python 3.12 from python.org (tick 'Add Python to PATH') and repeat.",
            "",
            "TECHNICAL",
            f"{type(ex).__name__}: {ex}",
            f"Python {sys.version.split()[0]} at {sys.executable}",
            f"System: {platform.platform()}",
        ]
    )
    if getattr(sys, "frozen", False):
        text = "SHIFTWHEEL COULD NOT START\nRepair or reinstall ShiftWheel using its installer.\n" + f"{type(ex).__name__}: {ex}"
    home = os.path.expanduser("~")
    path = next(
        (
            os.path.join(d, "ShiftWheel_error_report.txt")
            for d in (
                os.path.join(home, "OneDrive", "Desktop"),
                os.path.join(home, "Desktop"),
                os.getcwd(),
            )
            if os.path.isdir(d)
        ),
        "",
    )
    try:
        open(path, "w", encoding="utf-8").write(text)
    except OSError:
        path = "(could not save the report file)"
    if sys.stdout is not None:
        print(text)
    try:
        ctypes.windll.user32.MessageBoxW(
            0,
            f"ShiftWheel could not start: missing '{pkg}'.\n\nA report with the exact fix was saved to:\n{path}",
            "ShiftWheel",
            0x10,
        )
    except Exception:
        pass
    raise SystemExit(1)


try:
    from PySide6.QtWidgets import (
        QApplication,
        QWidget,
        QSystemTrayIcon,
        QMenu,
        QDialog,
        QDialogButtonBox,
        QVBoxLayout,
        QHBoxLayout,
        QLabel,
        QRubberBand,
        QInputDialog,
        QLineEdit,
        QPlainTextEdit,
        QPushButton,
        QFileDialog,
        QComboBox,
        QSpinBox,
        QFormLayout,
        QMessageBox,
    )
    from PySide6.QtCore import (
        Qt,
        QPointF,
        QRectF,
        QRect,
        QSize,
        QObject,
        Signal,
        QTimer,
        Slot,
    )
    from PySide6.QtGui import (
        QPainter,
        QColor,
        QPolygonF,
        QFont,
        QIcon,
        QPixmap,
        QCursor,
        QPen,
        QLinearGradient,
        QRadialGradient,
        QGuiApplication,
        QActionGroup,
        QKeySequence,
        QShortcut,
        QImage,
    )

    if sys.platform == "win32":
        from pynput import mouse, keyboard
    else:
        mouse = keyboard = (
            None  # Core and Qt tests can run without native Windows hooks.
        )
except ImportError as _e:
    _startup_fail(_e)

# Optional HEIC support
_HEIF = False
try:
    from pillow_heif import register_heif_opener

    register_heif_opener()
    _HEIF = True
except Exception:
    pass

u32 = None
if sys.platform == "win32":
    from ctypes import wintypes

    u32 = ctypes.WinDLL("user32", use_last_error=True)
    u32.GetForegroundWindow.restype = wintypes.HWND
    u32.GetClassNameW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
    u32.GetClassNameW.restype = ctypes.c_int
    u32.GetAsyncKeyState.argtypes = [ctypes.c_int]
    u32.GetAsyncKeyState.restype = ctypes.c_short

EXPLORER = {"CabinetWClass", "Progman", "WorkerW"}
VK = {"shift": 0x10, "ctrl": 0x11, "alt": 0x12}
CFG = os.path.join(
    os.environ.get("APPDATA", os.path.join(os.path.expanduser("~"), ".config")),
    "ShiftWheel",
    "config.json",
)
cfg = {
    "trigger": "shift",
    "folder": False,
    "anywhere": False,
    "quick": True,
    "hotkey": "<ctrl>+<alt>+w",
    "ocr_language": "eng",
    "libreoffice_path": "",
}
HOTKEYS = {
    "Ctrl+Alt+W": "<ctrl>+<alt>+w",
    "F9": "<f9>",
    "Ctrl+Shift+Space": "<ctrl>+<shift>+<space>",
    "Off": "",
}
VERSION = "3.5"
DEBUG = True  # also print to the console / IDLE shell
LOG_FILE = os.path.join(os.path.dirname(CFG), "debug.log")
_sinks = []
_last_result = ""  # for tray tooltip
_job_settings = threading.local()


def _copy(e):
    """Accept drops as COPY only. Accepting a MOVE (what Shift implies) lets Explorer delete the originals."""
    e.setDropAction(Qt.CopyAction)
    e.accept()


def dbg(*a):
    line = time.strftime("%H:%M:%S ") + " ".join(str(x) for x in a)
    if DEBUG and sys.stdout is not None:
        try:
            print("[ShiftWheel]", line, flush=True)
        except (OSError, UnicodeError):
            pass
    for sink in list(_sinks):
        try:
            sink(line)
        except RuntimeError:
            pass
    try:
        os.makedirs(os.path.dirname(LOG_FILE), exist_ok=True)
        with open(LOG_FILE, "a", encoding="utf-8") as handle:
            handle.write(line + "\n")
    except OSError:
        pass


try:
    with open(CFG, encoding="utf-8") as handle:
        loaded = json.load(handle)
    if isinstance(loaded, dict):
        if isinstance(loaded.get("libreoffice_path"), str):
            cfg["libreoffice_path"] = loaded["libreoffice_path"]
        for key in ("folder", "anywhere", "quick"):
            if type(loaded.get(key)) is bool:
                cfg[key] = loaded[key]
        if isinstance(loaded.get("trigger"), str) and loaded["trigger"] in VK:
            cfg["trigger"] = loaded["trigger"]
        if (
            isinstance(loaded.get("hotkey"), str)
            and loaded["hotkey"] in HOTKEYS.values()
        ):
            cfg["hotkey"] = loaded["hotkey"]
        if isinstance(loaded.get("ocr_language"), str) and re.fullmatch(
            r"[A-Za-z_]+(?:\+[A-Za-z_]+)*", loaded["ocr_language"]
        ):
            cfg["ocr_language"] = loaded["ocr_language"]
except (OSError, ValueError):
    pass


def save_cfg():
    os.makedirs(os.path.dirname(CFG), exist_ok=True)
    fd, temp = tempfile.mkstemp(dir=os.path.dirname(CFG), suffix=".json")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(cfg, handle, indent=2)
        os.replace(temp, CFG)
    finally:
        if os.path.exists(temp):
            os.unlink(temp)


def key_down():
    return bool(u32 and u32.GetAsyncKeyState(VK[cfg["trigger"]]) & 0x8000)


def fg_class():
    if u32 is None:
        return ""
    b = ctypes.create_unicode_buffer(64)
    u32.GetClassNameW(u32.GetForegroundWindow(), b, 64)
    return b.value


def out(p, ext, tag=""):
    d = os.path.dirname(p)
    if getattr(_job_settings, "folder", cfg["folder"]):
        d = os.path.join(d, "Converted")
        os.makedirs(d, exist_ok=True)
    base, i = os.path.join(d, os.path.splitext(os.path.basename(p))[0] + tag), 0
    o = f"{base}.{ext}"
    while os.path.exists(o):
        i += 1
        o = f"{base}_{i}.{ext}"
    return o


def write_output(p, ext, writer, tag=""):
    destination = out(p, ext, tag)
    fd, temporary = tempfile.mkstemp(
        prefix=".shiftwheel-",
        suffix="." + ext,
        dir=os.path.dirname(os.path.abspath(destination)),
    )
    os.close(fd)
    reserved = None
    try:
        writer(temporary)
        if os.path.getsize(temporary) == 0:
            raise RuntimeError(
                "The operation produced an empty file; no result was saved."
            )
        while True:
            destination = out(p, ext, tag)
            try:
                fd = os.open(destination, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
                os.close(fd)
                reserved = destination
                break
            except FileExistsError:
                continue
        os.replace(temporary, destination)
        reserved = None
        return destination
    finally:
        for path in (temporary, reserved):
            if path and os.path.exists(path):
                os.unlink(path)


def load_image(p):
    from PIL import Image, ImageOps

    with Image.open(p) as source:
        im = ImageOps.exif_transpose(source)
        im.load()
        return im.copy()


def image_ext(p):
    ext = Path(p).suffix.lower().lstrip(".")
    return "png" if ext in ("heic", "heif", "gif") else ext or "png"


def save_image(p, im, ext=None, tag="", strip=False):
    from PIL import Image

    ext = ext or image_ext(p)
    if ext in ("jpg", "jpeg", "pdf", "bmp"):
        if im.mode in ("RGBA", "LA") or "transparency" in im.info:
            rgba = im.convert("RGBA")
            background = Image.new("RGB", im.size, "white")
            background.paste(rgba, mask=rgba.getchannel("A"))
            im = background
        else:
            im = im.convert("RGB")
    if strip:
        im.info.clear()
        im.getexif().clear()
    return write_output(p, ext, lambda target: im.save(target), tag)


def checked_number(value, minimum, maximum, label):
    try:
        number = float(value)
    except (TypeError, ValueError):
        raise ValueError(
            f"{label} must be a number between {minimum} and {maximum}."
        ) from None
    if not math.isfinite(number) or not minimum <= number <= maximum:
        raise ValueError(f"{label} must be a number between {minimum} and {maximum}.")
    return number


class MediaError(RuntimeError):
    pass


def ffm(ext, args, tag=""):
    def convert(p):
        return write_output(
            p, ext, lambda target: _ff(["-i", p] + args + [target]), tag
        )

    convert.requires_ffmpeg = True
    return convert


def im_save(fmt, ext):
    return lambda p: save_image(p, load_image(p), ext)


def im_edit(tag, op):
    return lambda p: save_image(p, op(load_image(p)), tag=tag, strip=tag == "_clean")


def im_small(p):
    im = load_image(p)
    return write_output(
        p, "webp", lambda target: im.save(target, "WEBP", quality=75), "_small"
    )


def pdf_pages(ext):
    def convert(p):
        last = None
        with _fitz().open(p) as doc:
            if doc.needs_pass:
                raise ValueError("The PDF is password-protected. Unlock it first.")
            for n, page in enumerate(doc):
                pixmap = page.get_pixmap(dpi=150, colorspace=_fitz().csRGB, alpha=False)
                last = write_output(p, ext, pixmap.save, f"_p{n + 1}")
        if not last:
            raise ValueError("The PDF contains no pages.")
        return last

    return convert


def pdf_text(p):
    with _fitz().open(p) as doc:
        if doc.needs_pass:
            raise ValueError("The PDF is password-protected. Unlock it first.")
        text = "\n".join(page.get_text() for page in doc)
    if not text.strip():
        raise ValueError("No embedded text was found. Try OCR → TXT for scanned pages.")
    return write_output(
        p, "txt", lambda target: Path(target).write_text(text, encoding="utf-8")
    )


def pdf_small(p):
    from pypdf import PdfReader, PdfWriter

    with PdfWriter() as writer:
        writer.clone_document_from_reader(PdfReader(p))
        for page in writer.pages:
            page.compress_content_streams()
        return write_output(p, "pdf", writer.write, "_small")


def merge(paths):
    from pypdf import PdfWriter

    with (
        tempfile.TemporaryDirectory(prefix="shiftwheel-merge-") as directory,
        PdfWriter() as writer,
    ):
        for index, path in enumerate(paths):
            if path.lower().endswith(".pdf"):
                writer.append(path)
            else:
                from PIL import Image

                im = load_image(path).convert("RGBA")
                background = Image.new("RGB", im.size, "white")
                background.paste(im, mask=im.getchannel("A"))
                im = background
                temporary = os.path.join(directory, f"{index}.pdf")
                im.save(temporary, "PDF")
                writer.append(temporary)
        return write_output(paths[0], "pdf", writer.write, "_merged")


def _ff(args):
    executable = shutil.which("ffmpeg")
    if not executable:
        raise RuntimeError(
            "ffmpeg not found on PATH. Install FFmpeg, then restart ShiftWheel."
        )
    result = subprocess.run(
        [executable, "-nostdin", "-y", "-hide_banner", "-loglevel", "error"] + args,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
        creationflags=0x08000000 if os.name == "nt" else 0,
    )
    if result.returncode:
        raise MediaError(
            "FFmpeg could not process this file:\n" + result.stderr[-6000:]
        )


def _ask(title, label, text=""):
    s, ok = QInputDialog.getText(
        None, title, label, QLineEdit.Normal, text, Qt.WindowStaysOnTopHint
    )
    return s.strip() if ok and s.strip() else None


class CropDlg(QDialog):
    preview_loaded = Signal(object, object)
    preview_failed = Signal(str)

    def __init__(self, path):
        super().__init__()
        self.setWindowTitle("Crop: drag to select, then OK")
        self.setWindowFlag(Qt.WindowStaysOnTopHint)
        self.full, self.pm, self.o, self.sel = None, None, None, None
        self._closed = False
        self.lb = QLabel("Loading image preview…")
        self.lb.setMinimumSize(400, 80)
        self.rb = QRubberBand(QRubberBand.Rectangle, self.lb)
        self.buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        self.buttons.button(QDialogButtonBox.Ok).setEnabled(False)
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)
        layout = QVBoxLayout(self)
        layout.addWidget(self.lb)
        layout.addWidget(self.buttons)
        self.lb.mousePressEvent = self.press
        self.lb.mouseMoveEvent = self.drag
        self.lb.mouseReleaseEvent = self.drag
        self.preview_loaded.connect(self.show_preview, Qt.QueuedConnection)
        self.preview_failed.connect(self.show_error, Qt.QueuedConnection)
        self.loader = threading.Thread(
            target=self.load_preview, args=(path,), daemon=True
        )
        self.loader.start()

    def load_preview(self, path):
        try:
            from PIL import Image

            im = load_image(path)
            size = im.size
            im.thumbnail((820, 560), Image.Resampling.LANCZOS)
            im = im.convert("RGBA")
            raw = im.tobytes("raw", "RGBA")
            preview = QImage(
                raw, im.width, im.height, im.width * 4, QImage.Format_RGBA8888
            ).copy()
            self.preview_loaded.emit(size, preview)
        except Exception as error:
            try:
                self.preview_failed.emit(str(error))
            except RuntimeError:
                pass

    @Slot(object, object)
    def show_preview(self, size, preview):
        if self._closed:
            return
        self.full, self.pm = QSize(*size), QPixmap.fromImage(preview)
        self.lb.setPixmap(self.pm)
        self.lb.setFixedSize(self.pm.size())
        self.adjustSize()

    @Slot(str)
    def show_error(self, message):
        if not self._closed:
            self.lb.setWordWrap(True)
            self.lb.setText("Cannot preview this image: " + message)

    def done(self, result):
        self._closed = True
        super().done(result)

    def press(self, event):
        if self.pm is None or event.button() != Qt.LeftButton:
            return
        self.sel = None
        self.buttons.button(QDialogButtonBox.Ok).setEnabled(False)
        self.o = event.position().toPoint()
        self.rb.setGeometry(QRect(self.o, QSize()))
        self.rb.show()

    def drag(self, event):
        if self.o is not None:
            self.sel = (
                QRect(self.o, event.position().toPoint())
                .normalized()
                .intersected(self.lb.rect())
            )
            self.rb.setGeometry(self.sel)
            self.buttons.button(QDialogButtonBox.Ok).setEnabled(
                self.sel.width() >= 3 and self.sel.height() >= 3
            )
            if not (event.buttons() & Qt.LeftButton):
                self.o = None

    def box(self):
        if self.pm is None or self.sel is None:
            raise ValueError("Select a crop rectangle first.")
        rectangle = self.sel
        kx, ky = (
            self.full.width() / self.pm.width(),
            self.full.height() / self.pm.height(),
        )
        return (
            int(rectangle.left() * kx),
            int(rectangle.top() * ky),
            min(self.full.width(), math.ceil((rectangle.right() + 1) * kx)),
            min(self.full.height(), math.ceil((rectangle.bottom() + 1) * ky)),
        )


def crop_file(p, box):
    im = load_image(p)
    left, top, right, bottom = box
    if not (0 <= left < right <= im.width and 0 <= top < bottom <= im.height):
        raise ValueError("Crop rectangle is outside the image.")
    return save_image(p, im.crop(box), tag="_crop")


def crop(files):
    jobs = []
    for path in files:
        dialog = CropDlg(path)
        if (
            dialog.exec() == QDialog.Accepted
            and dialog.sel
            and dialog.sel.width() >= 3
            and dialog.sel.height() >= 3
        ):
            jobs.append((path, partial(crop_file, box=dialog.box())))
    return jobs


def parse_size(value):
    if value.endswith("%"):
        return ("percent", checked_number(value[:-1], 0.01, 1000, "Percentage"))
    number = checked_number(value, 1, 32768, "Width")
    if not number.is_integer():
        raise ValueError("Width must be a whole number of pixels.")
    return ("pixels", int(number))


def resize_file(p, size):
    from PIL import Image

    im = load_image(p)
    mode, amount = size
    width = max(1, round(im.width * amount / 100)) if mode == "percent" else amount
    height = max(1, round(im.height * width / im.width))
    if width * height > 80_000_000 or max(width, height) > 32768:
        raise ValueError(
            "Requested image is too large (limit: 80 megapixels / 32768 pixels per side)."
        )
    return save_image(
        p, im.resize((width, height), Image.Resampling.LANCZOS), tag=f"_{width}w"
    )


def resize_img(files):
    value = _ask(
        "Resize",
        "Width in pixels, or percentage (e.g. 50%). Aspect ratio is preserved.",
        "1280",
    )
    if value is None:
        return []
    size = parse_size(value)
    return [(path, partial(resize_file, size=size)) for path in files]


# ── Watermark dialog & function ──────────────────────────────────────────────
class WatermarkDlg(QDialog):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Batch watermark")
        self.setWindowFlag(Qt.WindowStaysOnTopHint)
        self.setMinimumWidth(360)
        form = QFormLayout()
        self.txt = QLineEdit("© ShiftWheel")
        self.pos = QComboBox()
        self.pos.addItems(
            ["Bottom-right", "Bottom-left", "Top-right", "Top-left", "Center"]
        )
        self.size = QSpinBox()
        self.size.setRange(8, 200)
        self.size.setValue(24)
        self.opacity = QSpinBox()
        self.opacity.setRange(10, 100)
        self.opacity.setValue(60)
        self.opacity.setSuffix("%")
        form.addRow("Text:", self.txt)
        form.addRow("Position:", self.pos)
        form.addRow("Font size:", self.size)
        form.addRow("Opacity:", self.opacity)
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        v = QVBoxLayout(self)
        v.addLayout(form)
        v.addWidget(bb)

    def values(self):
        return (
            self.txt.text().strip(),
            self.pos.currentText(),
            self.size.value(),
            self.opacity.value() / 100.0,
        )


def watermark_file(p, settings):
    from PIL import Image, ImageDraw, ImageFont

    text, position, font_size, opacity = settings
    im = load_image(p).convert("RGBA")
    font = (
        ImageFont.truetype(_FONT, font_size)
        if _FONT
        else ImageFont.load_default(size=font_size)
    )
    overlay = Image.new("RGBA", im.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)
    left, top, right, bottom = draw.textbbox((0, 0), text, font=font)
    width, height = right - left, bottom - top
    margin = max(8, font_size // 2)
    x = (
        (im.width - width) / 2
        if position == "Center"
        else (im.width - width - margin if "right" in position else margin)
    )
    y = (
        (im.height - height) / 2
        if position == "Center"
        else (im.height - height - margin if "Bottom" in position else margin)
    )
    xy = (max(0, x) - left, max(0, y) - top)
    alpha = int(255 * opacity)
    draw.text((xy[0] + 1, xy[1] + 1), text, font=font, fill=(0, 0, 0, alpha // 2))
    draw.text(xy, text, font=font, fill=(255, 255, 255, alpha))
    return save_image(p, Image.alpha_composite(im, overlay), tag="_wm")


def watermark(files):
    dialog = WatermarkDlg()
    if dialog.exec() != QDialog.Accepted or not dialog.values()[0]:
        return []
    return [(path, partial(watermark_file, settings=dialog.values())) for path in files]


# ── Video speed ──────────────────────────────────────────────────────────────
def _atempo_chain(speed):
    """Build atempo filter chain (each filter limited to 0.5–2.0)."""
    speed = checked_number(speed, 0.05, 16, "Speed")
    filters = []
    remaining = speed
    while remaining > 2.0 + 1e-6:
        filters.append("atempo=2.0")
        remaining /= 2.0
    while remaining < 0.5 - 1e-6:
        filters.append("atempo=0.5")
        remaining /= 0.5
    filters.append(f"atempo={remaining:.4f}")
    return ",".join(filters)


def speed_file(p, speed):
    speed = checked_number(speed, 0.05, 16, "Speed")
    # Optional audio mapping handles silent inputs without hiding unrelated failures.
    args = [
        "-map",
        "0:v:0",
        "-map",
        "0:a:0?",
        "-vf",
        f"setpts=(PTS-STARTPTS)/{speed}",
        "-af",
        "asetpts=PTS-STARTPTS," + _atempo_chain(speed),
        "-c:v",
        "libx264",
        "-pix_fmt",
        "yuv420p",
        "-c:a",
        "aac",
    ]
    return ffm("mp4", args, f"_{speed:g}x".replace(".", "p"))(p)


def vid_speed(files):
    value = _ask(
        "Video speed",
        "Speed factor from 0.05 to 16 (e.g. 0.5 or 2). Audio stays in sync.",
        "2",
    )
    if value is None:
        return []
    speed = checked_number(
        value.lower().replace("x", "").replace("×", "").strip(), 0.05, 16, "Speed"
    )
    return [(path, partial(speed_file, speed=speed)) for path in files]


# ── OCR ──────────────────────────────────────────────────────────────────────
def tesseract_path():
    found = shutil.which("tesseract")
    if found:
        return found
    for base in (
        os.environ.get("ProgramFiles", ""),
        os.environ.get("ProgramFiles(x86)", ""),
        os.path.join(os.environ.get("LOCALAPPDATA", ""), "Programs"),
    ):
        candidate = os.path.join(base, "Tesseract-OCR", "tesseract.exe")
        if base and os.path.isfile(candidate):
            return candidate
    return None


def _tesseract_ok():
    return bool(tesseract_path())


def ocr_engine():
    try:
        import pytesseract
    except ImportError:
        raise RuntimeError(
            "OCR requires pytesseract: python -m pip install pytesseract"
        ) from None
    executable = tesseract_path()
    if not executable:
        raise RuntimeError(
            "Tesseract OCR is missing. Install it with: winget install --id UB-Mannheim.TesseractOCR"
        )
    pytesseract.pytesseract.tesseract_cmd = executable
    language = getattr(_job_settings, "ocr_language", cfg["ocr_language"])
    missing = set(language.split("+")) - set(pytesseract.get_languages(config=""))
    if missing:
        raise RuntimeError(
            "Tesseract language data is missing: " + ", ".join(sorted(missing))
        )
    return pytesseract, language


def ocr_image(p):
    engine, language = ocr_engine()
    text = engine.image_to_string(load_image(p), lang=language, timeout=180)
    if not text.strip():
        raise ValueError("OCR found no readable text. No empty file was saved.")
    return write_output(
        p, "txt", lambda target: Path(target).write_text(text, encoding="utf-8"), "_ocr"
    )


def ocr_pdf(p):
    from PIL import Image

    engine, language = ocr_engine()
    lines = []
    with _fitz().open(p) as doc:
        if doc.needs_pass:
            raise ValueError("The PDF is password-protected. Unlock it first.")
        for number, page in enumerate(doc, 1):
            try:
                pix = page.get_pixmap(dpi=200, colorspace=_fitz().csRGB, alpha=False)
                im = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
                text = engine.image_to_string(im, lang=language, timeout=180)
            except Exception as ex:
                raise RuntimeError(f"OCR failed on page {number}: {ex}") from ex
            if not text.strip():
                text = "[No readable text detected on this page]"
            lines.append(f"--- page {number} ---\n{text}")
    if not lines:
        raise ValueError("The PDF contains no pages.")
    return write_output(
        p,
        "txt",
        lambda target: Path(target).write_text("\n\n".join(lines), encoding="utf-8"),
        "_ocr",
    )


def ocr_files(p):
    return ocr_pdf(p) if p.lower().endswith(".pdf") else ocr_image(p)


def parse_time(value):
    parts = value.strip().split(":")
    if not 1 <= len(parts) <= 3:
        raise ValueError("Use seconds, mm:ss, or hh:mm:ss.")
    values = [checked_number(x, 0, 1_000_000, "Time") for x in parts]
    if any(x >= 60 for x in values[1:]):
        raise ValueError("Minutes and seconds after a colon must be below 60.")
    result = 0.0
    for number in values:
        result = result * 60 + number
    return result


def trim_file(p, start, end):
    args = ["-ss", str(start), "-i", p]
    if end is not None:
        args += ["-t", str(end - start)]
    args += ["-c", "copy"]
    return write_output(
        p, Path(p).suffix[1:], lambda target: _ff(args + [target]), "_trim"
    )


def trim(files):
    value = _ask(
        "Trim",
        "Start - end (seconds or mm:ss). End may be blank. Stream copy is keyframe-approximate.",
        "0:00 - ",
    )
    if value is None:
        return []
    start, separator, end = value.partition("-")
    if not separator:
        raise ValueError("Enter start - end, for example 0:10 - 0:45.")
    start, end = parse_time(start or "0"), parse_time(end) if end.strip() else None
    if end is not None and end <= start:
        raise ValueError("End must be later than start.")
    return [(path, partial(trim_file, start=start, end=end)) for path in files]


def rename_plan(files, pattern):
    import string

    for _, field, spec, conversion in string.Formatter().parse(pattern):
        if field is not None and (field not in ("name", "n") or spec or conversion):
            raise ValueError("Use only {name} and {n}, without format specifiers.")
    plan, seen = [], set()
    for number, path in enumerate(files, 1):
        if not os.path.isfile(path):
            raise ValueError("Rename copies supports files only.")
        name = pattern.format(name=Path(path).stem, n=f"{number:03d}")
        if (
            not name
            or name in (".", "..")
            or re.search(r'[<>:"/\\|?*\x00-\x1f]', name)
            or name.endswith((" ", "."))
        ):
            raise ValueError("The pattern produces a filename Windows cannot use.")
        if name.split(".")[0].upper() in {
            "CON",
            "PRN",
            "AUX",
            "NUL",
            *(f"COM{i}" for i in range(1, 10)),
            *(f"LPT{i}" for i in range(1, 10)),
        }:
            raise ValueError("The pattern produces a reserved Windows filename.")
        if len(name + Path(path).suffix) > 240:
            raise ValueError("The resulting filename is too long.")
        target = os.path.join(os.path.dirname(path), name + Path(path).suffix)
        if cfg["folder"]:
            target = os.path.join(
                os.path.dirname(path), "Converted", name + Path(path).suffix
            )
        key = os.path.abspath(target).casefold()
        if (
            key in seen
            or os.path.exists(target)
            or key == os.path.abspath(path).casefold()
        ):
            raise ValueError(
                "A rename target already exists or repeats. Choose a different pattern."
            )
        seen.add(key)
        plan.append((path, target))
    return plan


def copy_named(p, target):
    os.makedirs(os.path.dirname(os.path.abspath(target)), exist_ok=True)
    # Exclusive creation prevents overwriting a target created after preflight.
    try:
        destination = open(target, "xb")
    except FileExistsError:
        raise ValueError(f"Target already exists: {target}") from None
    try:
        with destination, open(p, "rb") as source:
            shutil.copyfileobj(source, destination)
        shutil.copystat(p, target)
        return target
    except BaseException:
        os.unlink(target)
        raise


def rename(files):
    pattern = _ask(
        "Rename copies",
        "Create renamed COPIES; originals stay unchanged. Use {name} and {n}.",
        "{name}_{n}",
    )
    if pattern is None:
        return []
    return [
        (path, partial(copy_named, target=target))
        for path, target in rename_plan(files, pattern)
    ]


def parse_pages(value, count):
    pages = []
    for part in value.split(","):
        match = re.fullmatch(r"\s*(\d+)\s*(?:-\s*(\d+)\s*)?", part)
        if not match:
            raise ValueError("Use page numbers or ranges, for example 1-3,5.")
        first, last = int(match[1]), int(match[2] or match[1])
        if not 1 <= first <= last <= count:
            raise ValueError(
                f"Page ranges must be between 1 and {count}, in increasing order."
            )
        pages.extend(range(first - 1, last))
    return pages


def split_file(p, pages):
    from pypdf import PdfReader, PdfWriter

    reader = PdfReader(p)
    indices = parse_pages(pages, len(reader.pages))
    with PdfWriter() as writer:
        for index in indices:
            writer.add_page(reader.pages[index])
        return write_output(p, "pdf", writer.write, "_pages")


def split_pdf(files):
    pages = _ask(
        "Extract PDF pages",
        "Pages to keep from EACH PDF, e.g. 1-3,5 (page numbers start at 1).",
        "1",
    )
    return (
        []
        if pages is None
        else [(path, partial(split_file, pages=pages)) for path in files]
    )


def zipit(files):
    import zipfile

    members, names = [], set()
    # Snapshot before creating output; never traverse symlinks or include our output in itself.
    for path in files:
        if os.path.islink(path):
            raise ValueError(
                "ZIP does not follow symbolic links. Select the original file or folder."
            )
        if os.path.isdir(path):
            root_name = os.path.basename(os.path.normpath(path))
            if root_name.casefold() in names:
                raise ValueError(
                    "Two selected folders have the same name. Archive them separately."
                )
            names.add(root_name.casefold())
            members.append((path, root_name + "/"))
            for root, directories, filenames in os.walk(path):
                directories[:] = sorted(
                    d for d in directories if not os.path.islink(os.path.join(root, d))
                )
                for name in directories + sorted(filenames):
                    source = os.path.join(root, name)
                    if not os.path.islink(source):
                        members.append(
                            (source, os.path.relpath(source, os.path.dirname(path)))
                        )
        else:
            name = os.path.basename(path)
            if name.casefold() in names:
                raise ValueError(
                    "Two selected items have the same archive name. Archive them separately."
                )
            names.add(name.casefold())
            members.append((path, name))
    archive_names = [
        name.replace("\\", "/").rstrip("/").casefold() for _, name in members
    ]
    if len(set(archive_names)) != len(archive_names):
        raise ValueError(
            "Selected items overlap inside the archive. Select each folder only once."
        )

    def write(target):
        with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as archive:
            for source, name in members:
                archive.write(source, name)

    return write_output(files[0], "zip", write, "_archive" if len(files) > 1 else "")


def clean_av(p):
    return ffm(
        os.path.splitext(p)[1][1:], ["-map_metadata", "-1", "-c", "copy"], "_clean"
    )(p)


def clean_pdf(p):
    from pypdf import PdfReader, PdfWriter

    with PdfWriter() as writer:
        for page in PdfReader(p).pages:
            writer.add_page(page)
        writer.metadata = None
        return write_output(p, "pdf", writer.write, "_clean")


def pdf_rotate90(p):
    from pypdf import PdfReader, PdfWriter

    with PdfWriter() as writer:
        for page in PdfReader(p).pages:
            writer.add_page(page.rotate(90))
        return write_output(p, "pdf", writer.write, "_rot90")


def vid_frame(p):
    return ffm("png", ["-frames:v", "1", "-update", "1"], "_frame")(p)


def copy_paths(files):
    QApplication.clipboard().setText("\n".join(os.path.normpath(f) for f in files))
    return files[0]


def open_folder(files):
    p = files[0]
    folder = p if os.path.isdir(p) else os.path.dirname(p)
    subprocess.Popen(["explorer", os.path.normpath(folder)])
    return p


def grayscale(im):
    from PIL import ImageOps

    gray = ImageOps.grayscale(im).convert("RGB")
    if im.mode == "RGBA":
        gray.putalpha(im.getchannel("A"))
    return gray


OFFICE_INPUTS = {
    "presentation": {"ppt", "pptx", "pps", "ppsx", "odp"},
    "document": {"doc", "docx", "odt", "rtf"},
    "spreadsheet": {"xls", "xlsx", "ods"},
}
OFFICE_EXPORTS = {
    "presentation": {
        "pdf": "impress_pdf_Export",
        "pptx": "Impress MS PowerPoint 2007 XML",
        "odp": "impress8",
    },
    "document": {
        "pdf": "writer_pdf_Export",
        "docx": "Office Open XML Text",
        "odt": "writer8",
        "rtf": "Rich Text Format",
        "txt": "Text (encoded):UTF8",
    },
    "spreadsheet": {
        "pdf": "calc_pdf_Export",
        "xlsx": "Calc MS Excel 2007 XML",
        "ods": "calc8",
    },
}


def office_kind(path):
    extension = Path(path).suffix.lower().lstrip(".")
    return next(
        (kind for kind, extensions in OFFICE_INPUTS.items() if extension in extensions),
        None,
    )


def libreoffice_path():
    custom = getattr(_job_settings, "libreoffice_path", cfg.get("libreoffice_path", ""))
    if custom:
        if not os.path.isfile(custom):
            raise RuntimeError(
                "The saved LibreOffice path no longer exists. Use 'Locate LibreOffice…' in the tray menu."
            )
        return custom
    for name in ("soffice.com", "soffice.exe", "libreoffice", "soffice"):
        found = shutil.which(name)
        if found:
            return found
    for base in (
        os.environ.get("ProgramFiles", ""),
        os.environ.get("ProgramFiles(x86)", ""),
        os.path.join(os.environ.get("LOCALAPPDATA", ""), "Programs"),
    ):
        if base:
            for executable in ("soffice.com", "soffice.exe"):
                candidate = os.path.join(base, "LibreOffice", "program", executable)
                if os.path.isfile(candidate):
                    return candidate
    return None


def require_office():
    executable = libreoffice_path()
    if not executable:
        raise RuntimeError(
            "Office conversion needs LibreOffice (free). Install it from libreoffice.org, "
            "then restart ShiftWheel. If it is already installed, choose 'Locate LibreOffice…' "
            "in the tray menu and select program/soffice.com or soffice.exe."
        )
    return executable


def run_office_command(command, timeout=180):
    """Timeout cleanup targets only the isolated conversion process tree we start."""
    started = time.monotonic()
    dbg("Office conversion starting; timeout", timeout, "seconds")
    process = subprocess.Popen(
        command,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
        creationflags=(0x08000000 | 0x00000200) if os.name == "nt" else 0,
        start_new_session=os.name != "nt",
    )
    try:
        stdout, stderr = process.communicate(timeout=timeout)
    except subprocess.TimeoutExpired as error:
        dbg("Office conversion timed out after", round(time.monotonic() - started, 1), "seconds; PID", process.pid)
        if os.name == "nt":
            try:
                subprocess.run(
                    ["taskkill", "/PID", str(process.pid), "/T", "/F"],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    creationflags=0x08000000,
                    timeout=10,
                )
            except (OSError, subprocess.TimeoutExpired):
                process.kill()
        else:
            import signal

            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
        try:
            process.communicate(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill()
        raise RuntimeError(
            "Office conversion timed out. The document may be locked, password-protected or too complex."
        ) from error
    dbg("Office conversion finished in", round(time.monotonic() - started, 1), "seconds; exit", process.returncode)
    return subprocess.CompletedProcess(command, process.returncode, stdout, stderr)


def _office_export(path, target_ext, output_dir):
    """Run one isolated LibreOffice conversion; never reuse the user's desktop profile."""
    kind = office_kind(path)
    if kind is None or target_ext not in OFFICE_EXPORTS[kind]:
        raise ValueError(
            f"Unsupported Office conversion: {Path(path).suffix} to {target_ext}."
        )
    source = Path(path).resolve(strict=True)
    executable = require_office()
    with tempfile.TemporaryDirectory(
        prefix="shiftwheel-office-", ignore_cleanup_errors=True
    ) as temporary:
        work = Path(temporary)
        # Normalize the input basename: non-ASCII user paths remain supported, and output lookup is deterministic.
        staged = work / ("input" + source.suffix.lower())
        shutil.copyfile(source, staged)
        profile = work / "profile"
        (profile / "user").mkdir(parents=True)
        (profile / "user" / "registrymodifications.xcu").write_text(
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<oor:items xmlns:oor="http://openoffice.org/2001/registry">'
            '<item oor:path="/org.openoffice.Office.Common/Security/Scripting">'
            '<prop oor:name="MacroSecurityLevel" oor:op="fuse"><value>3</value></prop>'
            "</item></oor:items>",
            encoding="utf-8",
        )
        export = work / "export"
        export.mkdir()
        filter_spec = target_ext + ":" + OFFICE_EXPORTS[kind][target_ext]
        if kind == "presentation" and target_ext == "pdf":
            filter_spec += ":" + json.dumps(
                {"ExportHiddenSlides": {"type": "boolean", "value": "true"}}
            )
        command = [
            executable,
            "-env:UserInstallation=" + profile.as_uri(),
            "--headless",
            "--nologo",
            "--nodefault",
            "--norestore",
            "--convert-to",
            filter_spec,
            "--outdir",
            str(export),
            str(staged),
        ]
        result = run_office_command(command)
        produced = export / ("input." + target_ext)
        if result.returncode or not produced.is_file() or produced.stat().st_size == 0:
            detail = (result.stderr + "\n" + result.stdout).strip()[-3000:]
            raise RuntimeError(
                "LibreOffice did not produce a valid result. The file may be encrypted, damaged or unsupported.\n"
                + detail
            )
        if target_ext == "pdf":
            with _fitz().open(produced) as document:
                if document.needs_pass or len(document) == 0:
                    raise RuntimeError(
                        "The converted PDF is locked or contains no pages."
                    )
        destination = Path(output_dir) / ("converted." + target_ext)
        shutil.copyfile(produced, destination)
        return str(destination)


def office_convert(path, target_ext):
    with tempfile.TemporaryDirectory(prefix="shiftwheel-result-") as directory:
        result = _office_export(path, target_ext, directory)
        return write_output(
            path, target_ext, lambda output: shutil.copyfile(result, output)
        )


def office_pages(path, extension):
    # Export the entire document first, then rasterize every page/slide.
    with tempfile.TemporaryDirectory(prefix="shiftwheel-pages-") as directory:
        rendered = _office_export(path, "pdf", directory)
        last = None
        with _fitz().open(rendered) as document:
            for number, page in enumerate(document, 1):
                pixmap = page.get_pixmap(dpi=150, colorspace=_fitz().csRGB, alpha=False)
                last = write_output(path, extension, pixmap.save, f"_p{number}")
        return last


def office_text(path):
    if office_kind(path) == "document":
        return office_convert(path, "txt")
    with tempfile.TemporaryDirectory(prefix="shiftwheel-text-") as directory:
        rendered = _office_export(path, "pdf", directory)
        with _fitz().open(rendered) as document:
            text = "\n\n".join(
                f"--- page {number} ---\n{page.get_text()}"
                for number, page in enumerate(document, 1)
            )
        return write_output(
            path, "txt", lambda output: Path(output).write_text(text, encoding="utf-8")
        )


def universal_pdf(path):
    kind = file_kind(path)
    if kind in OFFICE_INPUTS:
        return office_convert(path, "pdf")
    if kind == "image":
        return im_save("PDF", "pdf")(path)
    if kind in ("text", "table", "json"):
        return txt_pdf(path)
    if kind == "pdf":
        return write_output(
            path, "pdf", lambda output: shutil.copyfile(path, output), "_copy"
        )
    raise ValueError("There is no PDF conversion for this file type.")


def merge_documents(paths):
    from pypdf import PdfWriter

    with (
        tempfile.TemporaryDirectory(prefix="shiftwheel-merge-docs-") as directory,
        PdfWriter() as writer,
    ):
        for number, path in enumerate(paths):
            kind = file_kind(path)
            if kind == "pdf":
                writer.append(path)
            elif kind in OFFICE_INPUTS:
                item_dir = Path(directory) / str(number)
                item_dir.mkdir()
                writer.append(_office_export(path, "pdf", item_dir))
            elif kind == "image":
                from PIL import Image

                rgba = load_image(path).convert("RGBA")
                image = Image.new("RGB", rgba.size, "white")
                image.paste(rgba, mask=rgba.getchannel("A"))
                temporary = Path(directory) / f"{number}.pdf"
                image.save(temporary, "PDF")
                writer.append(temporary)
            else:
                temporary = Path(directory) / f"{number}.pdf"
                with _txt_doc(path) as document:
                    document.save(temporary)
                writer.append(temporary)
        return write_output(paths[0], "pdf", writer.write, "_merged")


def table_rows(path):
    import csv

    extension = Path(path).suffix.lower()
    if extension == ".json":
        data = json.loads(_read_txt(path))
        if not isinstance(data, list) or not data:
            raise ValueError(
                "Table conversion needs a non-empty JSON array of rows or flat objects."
            )
        if all(isinstance(row, dict) for row in data):
            columns = list(dict.fromkeys(key for row in data for key in row))
            rows = [columns] + [[row.get(key) for key in columns] for row in data]
        elif all(isinstance(row, list) for row in data):
            rows = data
        else:
            raise ValueError(
                "JSON must contain either rows (arrays) or flat objects consistently."
            )
        if any(isinstance(value, (dict, list)) for row in rows for value in row):
            raise ValueError(
                "Nested JSON cannot be represented as a flat table without losing structure."
            )
    else:
        import io

        text = _read_txt(path)
        if extension == ".tsv":
            dialect = csv.excel_tab
        else:
            try:
                dialect = csv.Sniffer().sniff(text[:8192], delimiters=",;\t|")
            except csv.Error:
                dialect = csv.excel
        rows = list(csv.reader(io.StringIO(text, newline=""), dialect))
    if not rows:
        raise ValueError("The table is empty.")
    if len(rows) > 1_048_576 or max(map(len, rows), default=0) > 16_384:
        raise ValueError("The table exceeds Excel's row or column limit.")
    if any(
        isinstance(value, float) and not math.isfinite(value)
        for row in rows
        for value in row
    ):
        raise ValueError("Tables cannot contain NaN or infinite numeric values.")
    return rows


def table_convert(path, extension):
    import csv

    rows = table_rows(path)

    def write(output):
        if extension in ("csv", "tsv"):
            with open(output, "w", newline="", encoding="utf-8-sig") as handle:
                csv.writer(
                    handle, delimiter="\t" if extension == "tsv" else ","
                ).writerows(rows)
        elif extension == "json":
            # Arrays preserve duplicate headers, ragged rows and original column order.
            Path(output).write_text(
                json.dumps(rows, ensure_ascii=False, indent=2, allow_nan=False),
                encoding="utf-8",
            )
        elif extension == "xlsx":
            from openpyxl import Workbook
            from openpyxl.cell import WriteOnlyCell

            from openpyxl.cell.cell import ILLEGAL_CHARACTERS_RE

            for row in rows:
                for value in row:
                    if isinstance(value, str) and (
                        len(value) > 32767 or ILLEGAL_CHARACTERS_RE.search(value)
                    ):
                        raise ValueError(
                            "A cell has unsupported control characters or exceeds Excel's 32767-character limit."
                        )
            workbook = Workbook(write_only=True)
            sheet = workbook.create_sheet("Data")
            for row in rows:
                cells = []
                for value in row:
                    if isinstance(value, str) and len(value) > 32767:
                        raise ValueError(
                            "A cell exceeds Excel's 32767-character limit."
                        )
                    if (
                        isinstance(value, int)
                        and not isinstance(value, bool)
                        and abs(value) >= 10**15
                    ):
                        value = str(
                            value
                        )  # Excel numbers retain only 15 significant decimal digits.
                    cell = WriteOnlyCell(sheet, value=value)
                    if isinstance(value, str):
                        cell.data_type = "s"  # Preserve leading zeros and literal strings beginning with '='.
                    cells.append(cell)
                sheet.append(cells)
            workbook.save(output)
        else:
            raise ValueError("Unsupported table output type.")

    return write_output(path, extension, write)


def spreadsheet_tables(path, extension):
    """Export all worksheets, including empty ones; formula text is preserved explicitly."""
    import csv
    from openpyxl import load_workbook

    with tempfile.TemporaryDirectory(prefix="shiftwheel-sheets-") as directory:
        source = (
            path
            if Path(path).suffix.lower() == ".xlsx"
            else _office_export(path, "xlsx", directory)
        )
        workbook = load_workbook(source, read_only=True, data_only=False)
        last = None
        try:
            for number, sheet in enumerate(workbook.worksheets, 1):
                if extension == "json":
                    rows = [
                        [
                            value.isoformat() if hasattr(value, "isoformat") else value
                            for value in row
                        ]
                        for row in sheet.iter_rows(values_only=True)
                    ]
                    last = write_output(
                        path,
                        "json",
                        lambda output, rows=rows: Path(output).write_text(
                            json.dumps(
                                rows, ensure_ascii=False, indent=2, allow_nan=False
                            ),
                            encoding="utf-8",
                        ),
                        f"_sheet{number}",
                    )
                else:

                    def write(output, sheet=sheet):
                        with open(
                            output, "w", newline="", encoding="utf-8-sig"
                        ) as handle:
                            writer = csv.writer(
                                handle, delimiter="\t" if extension == "tsv" else ","
                            )
                            wrote_row = False
                            for row in sheet.iter_rows(values_only=True):
                                writer.writerow(row)
                                wrote_row = True
                            if not wrote_row:
                                writer.writerow([])

                    last = write_output(path, extension, write, f"_sheet{number}")
        finally:
            workbook.close()
        if not last:
            raise ValueError("The workbook has no worksheets.")
        return last


def show_format_info(files):
    extensions = ", ".join(
        sorted({Path(path).suffix.lower() or "(no extension)" for path in files})
    )
    QMessageBox.information(
        None,
        "Conversion limits",
        f"Selected: {extensions}\n\n" + supported_formats_text(),
    )
    return files[0]


def supported_formats_text():
    try:
        office = "ready" if libreoffice_path() else "not installed"
    except RuntimeError:
        office = "saved path needs updating"
    return (
        "Presentations (PPT/PPTX/PPS/PPSX/ODP): PDF, slide PNG/JPG, TXT, PPTX, ODP.\n"
        "Documents (DOC/DOCX/ODT/RTF): PDF, DOCX, ODT, RTF, TXT, page PNG/JPG.\n"
        "Spreadsheets (XLS/XLSX/ODS): PDF, XLSX, ODS; all sheets to CSV/TSV/JSON.\n"
        "Tables (CSV/TSV): XLSX, JSON, CSV, TSV, raw-text PDF.\n"
        "JSON: raw-text PDF; flat arrays/objects can also become XLSX/CSV/TSV.\n"
        "Images: PNG/JPG/WebP/BMP/TIFF/PDF and image edits. GIF/TIFF edits use the first frame/page.\n"
        "PDF: page PNG/JPG, text/OCR, merge, split, rotate and compression.\n"
        "Video/audio: compatible media targets using FFmpeg. Text/code: readable PDF.\n\n"
        f"LibreOffice: {office}. FFmpeg: {'ready' if shutil.which('ffmpeg') else 'not installed'}.\n\n"
        "Unsupported files still have ZIP/copy-path tools. ZIP is packaging, not format conversion.\n"
        "No EXE-to-document, CAD/3D, proprietary project or PDF-to-editable-Office conversion is included.\n"
        "Office layout can change if fonts/features differ. PDFs preserve static pages, not animation.\n"
        "CSV/JSON exports preserve cells/formula text, not formatting or computed formula results."
    )


H = lambda a, b, c, d=False: (
    a,
    b,
    c,
    d,
)  # (icon, label, fn, mode) mode: False=per file, True=all files, "ui"=dialog
V264 = ["-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac"]
COMMON = [
    H("📦", "Zip", zipit, True),
    H("✏", "Rename copies", rename, "ui"),
    H("📋", "Copy path", copy_paths, "main"),
    H("📂", "Open folder", open_folder, True),
]
SETS = {
    "image": [
        H("🖼", "PNG", im_save("PNG", "png")),
        H("📷", "JPG", im_save("JPEG", "jpg")),
        H("🌐", "WEBP", im_save("WEBP", "webp")),
        H("📄", "PDF", im_save("PDF", "pdf")),
        H("🗜", "Compress", im_small),
        H("✂", "Crop", crop, "ui"),
        H("📐", "Resize", resize_img, "ui"),
        H("💧", "Watermark", watermark, "ui"),
        H(
            "↻",
            "Rot 90°",
            im_edit(
                "_rot90",
                lambda i: i.transpose(__import__("PIL").Image.Transpose.ROTATE_270),
            ),
        ),
        H(
            "↺",
            "Rot -90°",
            im_edit(
                "_rot-90",
                lambda i: i.transpose(__import__("PIL").Image.Transpose.ROTATE_90),
            ),
        ),
        H(
            "↔",
            "Flip H",
            im_edit(
                "_flipH",
                lambda i: i.transpose(
                    __import__("PIL").Image.Transpose.FLIP_LEFT_RIGHT
                ),
            ),
        ),
        H(
            "↕",
            "Flip V",
            im_edit(
                "_flipV",
                lambda i: i.transpose(
                    __import__("PIL").Image.Transpose.FLIP_TOP_BOTTOM
                ),
            ),
        ),
        H("⬛", "Grayscale", im_edit("_gray", grayscale)),
        H("🔤", "OCR → TXT", ocr_files),
        H("🧹", "Clear metadata", im_edit("_clean", lambda i: i)),
        H("📎", "Merge PDF", merge, True),
    ]
    + COMMON,
    "video": [
        H("🎬", "MP4", ffm("mp4", V264)),
        H(
            "🌐",
            "WebM",
            ffm("webm", ["-c:v", "libvpx-vp9", "-b:v", "1M", "-c:a", "libopus"]),
        ),
        H("✨", "GIF", ffm("gif", ["-vf", "fps=12,scale=480:-1"])),
        H("🎵", "MP3", ffm("mp3", ["-vn", "-b:a", "192k"])),
        H("🗜", "Compress", ffm("mp4", V264 + ["-crf", "28"], "_small")),
        H("📺", "720p", ffm("mp4", ["-vf", "scale=-2:720"] + V264, "_720p")),
        H("⏩", "Speed", vid_speed, "ui"),
        H("🖼", "1st frame", vid_frame),
        H("✂", "Trim", trim, "ui"),
        H(
            "🔇",
            "Mute",
            ffm("mp4", ["-an", "-c:v", "libx264", "-pix_fmt", "yuv420p"], "_mute"),
        ),
        H("🧹", "Clear metadata", clean_av),
    ]
    + COMMON,
    "audio": [
        H("🎵", "MP3", ffm("mp3", ["-vn", "-b:a", "192k"])),
        H("🔊", "WAV", ffm("wav", ["-vn"])),
        H("💎", "FLAC", ffm("flac", ["-vn"])),
        H("🍎", "M4A", ffm("m4a", ["-vn", "-c:a", "aac"])),
        H("🗜", "Small MP3", ffm("mp3", ["-vn", "-b:a", "96k"], "_small")),
        H("✂", "Trim", trim, "ui"),
        H("🧹", "Clear metadata", clean_av),
    ]
    + COMMON,
    "pdf": [
        H("🖼", "Pages → PNG", pdf_pages("png")),
        H("📷", "Pages → JPG", pdf_pages("jpg")),
        H("📝", "Text", pdf_text),
        H("🔤", "OCR → TXT", ocr_files),
        H("📎", "Merge", merge, True),
        H("🗜", "Compress", pdf_small),
        H("✂", "Split", split_pdf, "ui"),
        H("↻", "Rot 90°", pdf_rotate90),
        H("🧹", "Clear metadata", clean_pdf),
    ]
    + COMMON,
}


def _fitz():
    try:
        import pymupdf as fz
    except ImportError:
        import fitz as fz
    if not hasattr(fz, "open") or not hasattr(fz, "Document"):
        raise ImportError(
            "Install PyMuPDF; the unrelated package named fitz is not supported."
        )
    return fz


_FONT = next(
    (
        f
        for f in (
            r"C:\Windows\Fonts\arial.ttf",
            r"C:\Windows\Fonts\segoeui.ttf",
            "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        )
        if os.path.exists(f)
    ),
    None,
)


def _read_txt(p):
    raw = open(p, "rb").read()
    if raw[:2] in (b"\xff\xfe", b"\xfe\xff"):
        return raw.decode("utf-16")
    try:
        return raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        return raw.decode("cp1252", errors="replace")


def _wrap(txt, width, measure):
    lines = []
    for para in txt.replace("\t", "    ").splitlines():
        cur = ""
        for w in para.split(" "):
            t = (cur + " " + w) if cur else w
            if measure(t) <= width:
                cur = t
                continue
            if cur:
                lines.append(cur)
            while len(w) > 1 and measure(w) > width:  # break very long words
                k = len(w)
                while k > 1 and measure(w[:k]) > width:
                    k -= 1
                lines.append(w[:k])
                w = w[k:]
            cur = w
        lines.append(cur)
    return lines or [""]


def _txt_doc(p):
    fitz = _fitz()
    font = fitz.Font(fontfile=_FONT) if _FONT else fitz.Font("helv")
    kw = {"fontfile": _FONT, "fontname": "u"} if _FONT else {"fontname": "helv"}
    fs, top, bot, left = 11, 56, 786, 50
    doc, y, page = fitz.open(), top, None
    for ln in _wrap(_read_txt(p), 495, lambda t: font.text_length(t, fs)):
        if page is None or y > bot:
            page, y = doc.new_page(width=595, height=842), top
        if ln:
            page.insert_text((left, y), ln, fontsize=fs, **kw)
        y += fs * 1.45
    return doc


def _txt_pillow(p, o):  # fallback when PyMuPDF is missing or broken (image-based PDF)
    from PIL import Image, ImageDraw, ImageFont

    fs = 26
    font = ImageFont.truetype(_FONT, fs) if _FONT else ImageFont.load_default()
    probe = ImageDraw.Draw(Image.new("RGB", (1, 1)))
    pages, y, dr = [], 0, None
    for ln in _wrap(_read_txt(p), 1040, lambda t: probe.textlength(t, font=font)):
        if not pages or y > 1650:
            im = Image.new("RGB", (1240, 1754), "white")
            pages.append(im)
            dr, y = ImageDraw.Draw(im), 100
        dr.text((100, y), ln, fill="black", font=font)
        y += int(fs * 1.45)
    pages[0].save(o, "PDF", save_all=True, append_images=pages[1:])


def txt_pdf(p):
    def write(target):
        with _txt_doc(p) as doc:
            doc.save(target)

    return write_output(p, "pdf", write)


def txt_merge(paths):
    with _fitz().open() as doc:
        for path in paths:
            with _txt_doc(path) as source:
                doc.insert_pdf(source)
        return write_output(paths[0], "pdf", doc.save, "_merged")


def selftest():
    import tempfile, importlib

    dbg("self-test | python", sys.version.split()[0], "|", sys.executable)
    dependencies_ok = True
    modules = ("PySide6", "PIL", "pypdf", "pymupdf", "openpyxl") + (
        ("pynput",) if sys.platform == "win32" else ()
    )
    for mod in modules:
        try:
            m = importlib.import_module(mod)
            dbg("  ok:", mod, getattr(m, "__version__", ""))
        except Exception as ex:
            dependencies_ok = False
            dbg("  MISSING:", mod, "->", ex)
    dbg(
        "  ffmpeg:", shutil.which("ffmpeg") or "not found (only needed for video/audio)"
    )
    try:
        dbg(
            "  LibreOffice:",
            libreoffice_path() or "not found (needed for Office conversion)",
        )
    except RuntimeError as error:
        dbg("  LibreOffice:", error)
    dbg("  pillow-heif (HEIC):", "yes" if _HEIF else "not installed (optional)")
    try:
        import pytesseract

        dbg("  pytesseract:", getattr(pytesseract, "__version__", "installed"))
    except Exception:
        dbg("  pytesseract: not installed (optional, for OCR)")
    dbg(
        "  tesseract binary:", shutil.which("tesseract") or "not found (needed for OCR)"
    )
    try:
        with tempfile.TemporaryDirectory(prefix="shiftwheel-selftest-") as directory:
            p = os.path.join(directory, "selftest.txt")
            Path(p).write_text("ShiftWheel self-test\n" * 3, encoding="utf-8")
            output = txt_pdf(p)
            dbg("  txt -> pdf OK:", os.path.getsize(output), "bytes")
        return dependencies_ok
    except Exception:
        dbg("  txt -> pdf FAILED:", traceback.format_exc())
        return False


SETS["text"] = [
    H("📄", "PDF", txt_pdf),
    H("📎", "Merge to 1 PDF", txt_merge, True),
] + COMMON


def explain(ex):
    if getattr(sys, "frozen", False) and isinstance(ex, ModuleNotFoundError):
        return "An included app library is missing. Repair or reinstall ShiftWheel using its installer."
    m, t = str(ex).lower(), type(ex).__name__
    if (
        isinstance(ex, (ValueError, MediaError))
        or "libreoffice" in m
        or "office conversion" in m
    ):
        return str(ex)
    if isinstance(ex, subprocess.CalledProcessError):
        return "ffmpeg ran but could not process this file (unsupported, damaged, or already in use)."
    if isinstance(ex, ModuleNotFoundError) or "no module named" in m:
        if "pytesseract" in m or "pillow_heif" in m:
            return str(ex)
        return f'A required library is missing. Run: "{sys.executable}" -m pip install PySide6 pynput Pillow pypdf pymupdf openpyxl'
    if "ffmpeg" in m:
        return str(ex)
    if "tesseract" in m or "ocr" in m:
        return str(ex)
    if isinstance(ex, PermissionError):
        return "Windows refused access: the file is open in another program, read-only, or in a protected folder."
    if "cannot identify image" in m or "UnidentifiedImage" in t:
        return (
            "This file is not a picture the tool can read (or it is damaged). "
            "For HEIC photos install pillow-heif: pip install pillow-heif"
        )
    if "password" in m or "encrypted" in m:
        return "The PDF is password-protected. Unlock it first."
    if isinstance(ex, FileNotFoundError):
        return (
            "The file no longer existed when the conversion started. It was moved, renamed or deleted. "
            "(Shift-dragging can make Explorer treat a drop as a MOVE; older builds could let Explorer delete the original - check the Recycle Bin.)"
        )
    return (
        "Unexpected error. The technical detail below shows exactly where it happened."
    )


def make_report(action, files, ex=None, tb=""):
    import platform, tempfile, importlib

    L = [
        "SHIFTWHEEL ERROR REPORT",
        time.strftime("%Y-%m-%d %H:%M:%S"),
        "",
        f"What was attempted: {action}",
        "Files: " + ("; ".join(files) if files else "-"),
        "",
    ]
    if ex is not None:
        L += [
            "WHY IT FAILED (plain English):",
            explain(ex),
            "",
            "TECHNICAL DETAIL:",
            f"{type(ex).__name__}: {ex}",
            tb or "",
            "",
        ]
    L += [
        "SYSTEM",
        f"ShiftWheel: {VERSION}",
        f"System: {platform.platform()}",
        f"Python: {sys.version.split()[0]} ({sys.executable})",
    ]
    for mod in (
        "PySide6",
        "pynput",
        "PIL",
        "pypdf",
        "pymupdf",
        "pillow_heif",
        "pytesseract",
    ):
        try:
            L.append(
                f"{mod}: {getattr(importlib.import_module(mod), '__version__', 'installed')}"
            )
        except Exception as e2:
            L.append(f"{mod}: MISSING ({e2})")
    L += [
        f"ffmpeg: {shutil.which('ffmpeg') or 'not found'}",
        f"tesseract: {shutil.which('tesseract') or 'not found'}",
        f"HEIC support: {_HEIF}",
        f"Settings: {cfg}",
        "",
        "RECENT LOG",
    ]
    try:
        L += open(LOG_FILE, encoding="utf-8").read().splitlines()[-40:]
    except OSError:
        pass
    home = os.path.expanduser("~")
    for d in (
        os.path.join(home, "OneDrive", "Desktop"),
        os.path.join(home, "Desktop"),
        os.path.dirname(LOG_FILE),
        tempfile.gettempdir(),
    ):
        try:
            os.makedirs(d, exist_ok=True) if d == os.path.dirname(LOG_FILE) else None
            if os.path.isdir(d):
                p = os.path.join(d, "ShiftWheel_error_report.txt")
                open(p, "w", encoding="utf-8").write("\n".join(L))
                dbg("report saved:", p)
                return p
        except OSError:
            continue
    return ""


OFFICE_PDF = H("📄", "PDF", partial(office_convert, target_ext="pdf"))
OFFICE_PNG = H("🖼", "Pages → PNG", partial(office_pages, extension="png"))
OFFICE_JPG = H("📷", "Pages → JPG", partial(office_pages, extension="jpg"))
SETS["presentation"] = [
    OFFICE_PDF,
    OFFICE_PNG,
    OFFICE_JPG,
    H("📝", "Text", office_text),
    H("▣", "PPTX", partial(office_convert, target_ext="pptx")),
    H("▣", "ODP", partial(office_convert, target_ext="odp")),
    H("📎", "Merge PDF", merge_documents, True),
] + COMMON
SETS["document"] = [
    OFFICE_PDF,
    H("▤", "DOCX", partial(office_convert, target_ext="docx")),
    H("▤", "ODT", partial(office_convert, target_ext="odt")),
    H("▤", "RTF", partial(office_convert, target_ext="rtf")),
    H("📝", "Text", office_text),
    OFFICE_PNG,
    OFFICE_JPG,
    H("📎", "Merge PDF", merge_documents, True),
] + COMMON
SETS["spreadsheet"] = [
    OFFICE_PDF,
    H("▦", "XLSX", partial(office_convert, target_ext="xlsx")),
    H("▦", "ODS", partial(office_convert, target_ext="ods")),
    H("▦", "Sheets → CSV", partial(spreadsheet_tables, extension="csv")),
    H("▦", "Sheets → TSV", partial(spreadsheet_tables, extension="tsv")),
    H("▦", "Sheets → JSON", partial(spreadsheet_tables, extension="json")),
] + COMMON
SETS["table"] = [
    H("▦", "XLSX", partial(table_convert, extension="xlsx")),
    H("▦", "JSON", partial(table_convert, extension="json")),
    H("▦", "CSV", partial(table_convert, extension="csv")),
    H("▦", "TSV", partial(table_convert, extension="tsv")),
    H("📄", "Text → PDF", txt_pdf),
] + COMMON
SETS["json"] = [
    H("📄", "Text → PDF", txt_pdf),
    H("▦", "Table → XLSX", partial(table_convert, extension="xlsx")),
    H("▦", "Table → CSV", partial(table_convert, extension="csv")),
    H("▦", "Table → TSV", partial(table_convert, extension="tsv")),
] + COMMON
SETS["image"] = (
    SETS["image"][: -len(COMMON)]
    + [H("🖼", "BMP", im_save("BMP", "bmp")), H("🖼", "TIFF", im_save("TIFF", "tiff"))]
    + COMMON
)
SETS["audio"] = (
    SETS["audio"][: -len(COMMON)]
    + [
        H("🎵", "OGG", ffm("ogg", ["-vn", "-c:a", "libvorbis"])),
        H("🎵", "Opus", ffm("opus", ["-vn", "-c:a", "libopus"])),
    ]
    + COMMON
)
SETS["other"] = [H("?", "Format info", show_format_info, "main")] + COMMON
KIND = {}
for kind, extensions in {
    "image": "png jpg jpeg jpe webp bmp gif tif tiff heic heif avif ico",
    "video": "mp4 mov mkv avi webm m4v mpg mpeg wmv flv mts m2ts ts 3gp ogv",
    "audio": "mp3 wav wave m4a flac ogg aac opus aif aiff wma amr ac3",
    "pdf": "pdf",
    "text": "txt md markdown log xml ini text py bat cmd js html htm css yaml yml toml sql c cpp h cs java sh ps1 srt vtt rst",
    "table": "csv tsv",
    "json": "json",
    **{
        kind: " ".join(sorted(extensions)) for kind, extensions in OFFICE_INPUTS.items()
    },
}.items():
    for extension in extensions.split():
        KIND["." + extension] = kind


def file_kind(path):
    return (
        "other" if os.path.isdir(path) else KIND.get(Path(path).suffix.lower(), "other")
    )


def action_requires_office(action, files):
    operation = action[2]
    function = operation.func if isinstance(operation, partial) else operation
    if function in (office_convert, office_pages, office_text):
        return True
    if function == spreadsheet_tables:
        return any(Path(path).suffix.lower() != ".xlsx" for path in files)
    if function in (universal_pdf, merge_documents):
        return any(file_kind(path) in OFFICE_INPUTS for path in files)
    return False


class Bus(QObject):
    show = Signal()
    quit = Signal()
    summon = Signal()
    dismiss = Signal()
    done = Signal(str, str)
    log = Signal(str)
    busy = Signal(bool)
    finished = Signal()


def actions_for(files):
    if files and all(os.path.isdir(path) for path in files):
        return COMMON
    kinds = {file_kind(path) for path in files}
    if len(kinds) == 1:
        kind = next(iter(kinds))
        actions = list(SETS[kind])
        # Do not present a same-format conversion as useful work.
        if kind in OFFICE_INPUTS or kind in ("table", "json"):
            source_extensions = {
                Path(path).suffix.lower().lstrip(".") for path in files
            }
            actions = [
                action
                for action in actions
                if not (
                    len(source_extensions) == 1
                    and action[1].lower() in source_extensions
                )
            ]
        return actions
    if kinds and kinds <= {"image", "pdf"}:
        return [H("📎", "Merge PDF", merge, True)] + COMMON
    if kinds and kinds <= {"image", "pdf", "text", "table", "json", *OFFICE_INPUTS}:
        return [
            H("📄", "Each → PDF", universal_pdf),
            H("📎", "Merge PDF", merge_documents, True),
        ] + COMMON
    return COMMON


def action_pages(actions):
    if len(actions) <= 8:
        return [list(actions)]
    pages = []
    for index in range(0, len(actions), 7):
        page = list(actions[index : index + 7])
        page += [("", "", None, False)] * (7 - len(page))
        pages.append(page + [("➜", "More…", None, "page")])
    return pages


class Jobs(QObject):
    """Own UI state on the GUI thread; workers only process files and emit signals."""

    def __init__(self, bus):
        super().__init__()
        self.bus, self.active, self.thread = bus, False, None
        bus.finished.connect(self.finish, Qt.QueuedConnection)

    @Slot()
    def finish(self):
        self.active = False
        self.bus.busy.emit(False)

    def start(self, act, files):
        if self.active:
            self.bus.done.emit(
                "A job is already running. Please wait for it to finish.", ""
            )
            return
        if not files or any(not os.path.exists(path) for path in files):
            self.bus.done.emit("One or more selected files no longer exist.", "")
            return
        operation = act[2].func if isinstance(act[2], partial) else act[2]
        if (
            getattr(operation, "requires_ffmpeg", False)
            or operation in (vid_speed, trim, vid_frame, clean_av)
        ) and not shutil.which("ffmpeg"):
            QMessageBox.information(
                None,
                "FFmpeg required",
                "This conversion needs FFmpeg. Install FFmpeg, add its bin folder to PATH, then restart ShiftWheel.",
            )
            return
        if action_requires_office(act, files):
            try:
                require_office()
            except RuntimeError as error:
                QMessageBox.information(None, "LibreOffice required", str(error))
                return
        self.active = (
            True  # Includes modal-dialog preparation; prevents reentrant submissions.
        )
        self.bus.busy.emit(True)
        try:
            if act[3] == "main":
                output = act[2](files)
                self.bus.done.emit(f"✓ {act[1]} done", output or "")
                self.finish()
                return
            if act[3] == "ui":
                jobs = act[2](files)
            elif act[3] is True:
                jobs = [(list(files), act[2])]
            else:
                jobs = [(path, act[2]) for path in files]
            if not jobs:
                self.bus.done.emit(f"Cancelled: {act[1]}", "")
                self.finish()
                return
        except Exception as ex:
            self.bus.done.emit(f"✗ {act[1]}: {ex}", "")
            dbg("Preparation failed:", traceback.format_exc())
            self.finish()
            return
        self.bus.done.emit(f"Working… {act[1]}", "")
        self.thread = threading.Thread(
            target=self.run, args=(act[1], list(files), jobs, dict(cfg)), daemon=False
        )
        self.thread.start()

    def run(self, label, files, jobs, settings=None):
        _job_settings.folder = (settings or cfg)["folder"]
        _job_settings.ocr_language = (settings or cfg)["ocr_language"]
        _job_settings.libreoffice_path = (settings or cfg).get("libreoffice_path", "")
        successes, errors, last = 0, [], ""
        try:
            for source, operation in jobs:
                try:
                    output = operation(source)
                    if not output:
                        raise RuntimeError("The operation returned no result.")
                    last = str(output)
                    successes += 1
                except Exception as ex:
                    detail = f"Input: {source}\n{traceback.format_exc()}"
                    errors.append((ex, detail))
                    dbg("ERROR", detail)
            message = f"{label}: {successes}/{len(jobs)} completed"
            if errors:
                message += f"; {len(errors)} failed. Click to locate report."
                last = make_report(
                    label,
                    files,
                    errors[0][0],
                    "\n\n".join(detail for _, detail in errors),
                )
            self.bus.done.emit(message, last)
        except Exception as ex:
            dbg("Job reporting failed:", traceback.format_exc())
            self.bus.done.emit(f"✗ {label}: {ex}", "")
        finally:
            self.bus.finished.emit()


class Wheel(QWidget):
    S, R, r = 460, 205, 67

    def __init__(self, bus, jobs=None):
        super().__init__()
        self.bus, self.jobs = bus, jobs or Jobs(bus)
        self.files, self.pinned, self.page = [], False, 0
        self.hover, self.open, self.grow = -1, 0.0, []
        self.all_actions, self.pages, self.acts = [], [], []
        self.more_blocked = False
        self.icon_font = QFont("Segoe UI Emoji", 16)
        self.label_font = QFont("Segoe UI", 9, QFont.DemiBold)
        self.title_font = QFont("Segoe UI", 10, QFont.Bold)
        self.small_font = QFont("Segoe UI", 8)
        self.polygons = {}
        for count in range(1, 9):
            for index in range(count):
                angle, step = index * 360 / count, 360 / count
                for growth in range(11):
                    self.polygons[(count, index, growth)] = self.ring(
                        angle - step / 2 + 1.2,
                        angle + step / 2 - 1.2,
                        self.r,
                        self.R + 1.4 * growth,
                    )
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        self.setAcceptDrops(True)
        self.resize(self.S, self.S)
        self.tick = QTimer(self, interval=16, timeout=self.step)
        self.idle = QTimer(self, singleShot=True, interval=5000, timeout=self.hide)
        self.more_timer = QTimer(
            self, singleShot=True, interval=550, timeout=self.next_page
        )
        self.shortcut = QShortcut(
            QKeySequence(Qt.Key_Escape), self, activated=self.hide
        )
        self.shortcut.setContext(Qt.ApplicationShortcut)
        bus.dismiss.connect(self.hide)
        self.set_actions(SETS["image"])

    def set_actions(self, actions):
        self.all_actions, self.pages, self.page = (
            list(actions),
            action_pages(actions),
            0,
        )
        self.more_blocked = False
        self.more_timer.stop()
        self.set_page()

    def set_page(self):
        self.acts = self.pages[self.page]
        self.grow, self.hover = [0.0] * len(self.acts), -1
        self.animate()

    def next_page(self):
        if len(self.pages) > 1 and self.isVisible():
            self.page = (self.page + 1) % len(self.pages)
            self.more_blocked = True  # Move off More before dwelling again.
            self.set_page()

    def animate(self):
        if self.isVisible():
            self.tick.start()
        self.update()

    def pop(self, summoned=False):
        if self.jobs.active:
            return
        self.pinned = summoned
        cursor = QCursor.pos()
        screen = QGuiApplication.screenAt(cursor) or QGuiApplication.primaryScreen()
        if screen is None:
            return
        geometry = screen.availableGeometry()
        self.move(
            max(
                geometry.left(),
                min(cursor.x() - self.S // 2, geometry.right() - self.S + 1),
            ),
            max(
                geometry.top(),
                min(cursor.y() - self.S // 2, geometry.bottom() - self.S + 1),
            ),
        )
        self.hover, self.open, self.files = -1, 0.0, []
        self.set_actions(SETS["image"])
        self.show()
        self.raise_()
        self.tick.start()
        self.idle.start(12000 if summoned else 5000)
        if summoned:
            self.activateWindow()
            self.setFocus()

    def hideEvent(self, event):
        self.tick.stop()
        self.idle.stop()
        self.more_timer.stop()
        super().hideEvent(event)

    def step(self):
        self.open += (1 - self.open) * 0.22
        settled = abs(1 - self.open) < 0.003
        if settled:
            self.open = 1.0
        for index in range(len(self.grow)):
            target = float(index == self.hover)
            self.grow[index] += (target - self.grow[index]) * 0.3
            if abs(target - self.grow[index]) < 0.003:
                self.grow[index] = target
            else:
                settled = False
        self.update()
        if settled:
            self.tick.stop()

    def idx(self, point):
        dx, dy = point.x() - self.S / 2, point.y() - self.S / 2
        distance = math.hypot(dx, dy)
        if distance <= self.r - 8:
            return -2
        count = len(self.acts)
        if not count or not self.r < distance < self.R + 14:
            return -1
        angle = math.degrees(math.atan2(dx, -dy)) % 360
        step = 360 / count
        index = int(((angle + step / 2) % 360) // step)
        offset = (angle - index * step + 180) % 360 - 180
        if abs(offset) > step / 2 - 1.2:
            return -1
        if distance > self.R + 14 * self.grow[index]:
            return -1
        if self.acts[index][2] is None and self.acts[index][3] != "page":
            return -1
        return index

    @staticmethod
    def ring(a0, a1, r0, r1):
        pts = [
            QPointF(
                r1 * math.sin(math.radians(a0 + (a1 - a0) * k / 14)),
                -r1 * math.cos(math.radians(a0 + (a1 - a0) * k / 14)),
            )
            for k in range(15)
        ]
        pts += [
            QPointF(
                r0 * math.sin(math.radians(a1 - (a1 - a0) * k / 14)),
                -r0 * math.cos(math.radians(a1 - (a1 - a0) * k / 14)),
            )
            for k in range(15)
        ]
        return QPolygonF(pts)

    @staticmethod
    def draw_action_icon(p, x, y, label):
        """Small vector marks stay crisp without relying on emoji fonts."""
        p.save()
        p.translate(x, y)
        pen = p.pen()
        pen.setWidthF(1.8)
        pen.setCapStyle(Qt.RoundCap)
        pen.setJoinStyle(Qt.RoundJoin)
        p.setPen(pen)
        p.setBrush(Qt.NoBrush)
        if label.startswith("More"):
            p.drawLine(QPointF(-9, 0), QPointF(9, 0))
            p.drawLine(QPointF(3, -6), QPointF(9, 0))
            p.drawLine(QPointF(3, 6), QPointF(9, 0))
        elif label in ("Resize", "Crop", "Compress"):
            p.drawRoundedRect(QRectF(-11, -9, 22, 18), 2, 2)
            p.drawLine(QPointF(-6, 5), QPointF(6, -5))
            p.drawLine(QPointF(1, -5), QPointF(6, -5))
            p.drawLine(QPointF(6, -5), QPointF(6, 0))
        else:
            p.drawRoundedRect(QRectF(-8, -11, 16, 22), 2, 2)
            p.drawLine(QPointF(-4, -3), QPointF(4, -3))
            p.drawLine(QPointF(-4, 2), QPointF(4, 2))
            p.drawLine(QPointF(-4, 7), QPointF(1, 7))
        p.restore()

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setOpacity(min(1.0, self.open * 1.4))
        p.translate(self.S / 2, self.S / 2)
        s = 0.8 + 0.2 * self.open
        p.scale(s, s)
        sh = QRadialGradient(0, 0, self.R + 18)
        sh.setColorAt(0.8, QColor(0, 0, 0, 110))
        sh.setColorAt(1, QColor(0, 0, 0, 0))
        p.setPen(Qt.NoPen)
        p.setBrush(sh)
        p.drawEllipse(QPointF(0, 0), self.R + 18, self.R + 18)
        n = len(self.acts)
        if n == 0:
            return
        st = 360 / n
        acc = QLinearGradient(-self.R, -self.R, self.R, self.R)
        acc.setColorAt(0, QColor(255, 185, 100))
        acc.setColorAt(1, QColor(255, 128, 70))
        for i, (ic, lb, _f, _b) in enumerate(self.acts):
            if not lb:
                continue
            g = self.grow[i] if i < len(self.grow) else 0
            m = i * st
            p.setBrush(acc if g > 0.5 else QColor(30, 35, 46, 248))
            p.setPen(QPen(QColor(255, 255, 255, 40), 1.5))
            p.drawPolygon(self.polygons[(n, i, round(g * 10))])
            mid = (self.R + self.r) / 2 + 7 * g
            x, y = mid * math.sin(math.radians(m)), -mid * math.cos(math.radians(m))
            p.setPen(QColor(25, 29, 38) if g > 0.5 else QColor(240, 243, 249))
            self.draw_action_icon(p, x, y - 14, lb)
            p.setFont(self.label_font)
            p.drawText(QRectF(x - 48, y + 2, 96, 38), Qt.AlignHCenter | Qt.AlignTop | Qt.TextWordWrap, lb)
        p.setBrush(QColor(16, 17, 26, 245))
        p.setPen(QPen(QColor(255, 140, 60, 160), 2))
        p.drawEllipse(QPointF(0, 0), self.r - 8, self.r - 8)
        p.setPen(QColor("white"))
        if 0 <= self.hover < n:
            title = self.acts[self.hover][1]
        elif self.hover == -2 and cfg["quick"] and self.files:
            title = "Release:\n" + self.all_actions[0][1]
        else:
            title = "Drop here" if self.files else "Drag onto\nan action"
        p.setFont(self.title_font)
        p.drawText(QRectF(-52, -33, 104, 46), Qt.AlignCenter | Qt.TextWordWrap, title)
        sub = (
            f"Page {self.page + 1}/{len(self.pages)}"
            if len(self.pages) > 1
            else "Esc to close"
        )
        p.setPen(QColor(255, 255, 255, 150))
        p.setFont(self.small_font)
        p.drawText(QRectF(-50, 13, 100, 18), Qt.AlignCenter, sub)
        if self.files:
            count = len(self.files)
            p.drawText(QRectF(-48, 31, 96, 16), Qt.AlignCenter, f"{count} file" + ("s" if count != 1 else ""))

    def dragEnterEvent(self, event):
        files = [
            url.toLocalFile() for url in event.mimeData().urls() if url.isLocalFile()
        ]
        if (
            self.jobs.active
            or not files
            or not (event.possibleActions() & Qt.CopyAction)
        ):
            event.ignore()
            return
        self.files = list(dict.fromkeys(os.path.abspath(path) for path in files))
        self.idle.stop()
        self.set_actions(actions_for(self.files))
        _copy(event)

    def dragMoveEvent(self, event):
        if not self.files:
            event.ignore()
            return
        index = self.idx(event.position())
        if index != self.hover:
            self.hover = index
            self.animate()
        is_more = 0 <= index < len(self.acts) and self.acts[index][3] == "page"
        if not is_more:
            self.more_timer.stop()
            self.more_blocked = False
        elif not self.more_blocked and not self.more_timer.isActive():
            self.more_timer.start()
        _copy(event)

    def dragLeaveEvent(self, event):
        self.more_timer.stop()
        self.more_blocked = False
        self.hover = -1
        self.files = []
        if self.pinned:
            self.idle.start(12000)
            self.animate()
        else:
            self.hide()

    def dropEvent(self, event):
        index = self.idx(event.position())
        files = list(self.files)
        self.more_timer.stop()
        if not files or not (event.possibleActions() & Qt.CopyAction):
            event.ignore()
            self.hide()
            return
        # Accept even inert drops as COPY, so Explorer must never delete sources.
        _copy(event)
        action = (
            self.all_actions[0]
            if index == -2 and cfg["quick"]
            else (self.acts[index] if 0 <= index < len(self.acts) else None)
        )
        self.hide()
        if action is None or action[2] is None:
            self.bus.done.emit(
                "No action run. Drop onto an action; hover More to change pages.", ""
            )
            return
        QTimer.singleShot(0, lambda a=action, paths=files: self.jobs.start(a, paths))


class Toast(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        self.resize(380, 100)
        self.message_font = QFont("Segoe UI", 10, QFont.DemiBold)
        self.hint_font = QFont("Segoe UI", 8)
        self.msg, self.path = "", ""
        self.t = QTimer(self, singleShot=True, interval=4500, timeout=self.hide)

    def flash(self, msg, path):
        global _last_result
        self.msg, self.path = msg, path
        _last_result = msg.split("\n")[0] if msg else ""
        screen = QGuiApplication.screenAt(QCursor.pos()) or QGuiApplication.primaryScreen()
        g = screen.availableGeometry()
        self.setFont(self.message_font)
        width = min(420, max(240, g.width() - 32))
        bounds = self.fontMetrics().boundingRect(QRect(0, 0, width - 36, 10000), Qt.TextWordWrap, self.msg)
        height = min(max(100, bounds.height() + 48), max(100, g.height() - 32))
        self.resize(width, height)
        self.setToolTip(self.msg)
        self.move(g.right() - width - 15, g.bottom() - height - 15)
        self.show()
        self.update()
        self.t.start()

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setBrush(QColor(24, 26, 36, 240))
        p.setPen(QPen(QColor(255, 140, 60, 180), 1.5))
        p.drawRoundedRect(QRectF(2, 2, self.width() - 4, self.height() - 4), 14, 14)
        p.setPen(QColor("white"))
        p.setFont(self.message_font)
        p.drawText(QRectF(18, 12, self.width() - 36, self.height() - 44), Qt.AlignVCenter | Qt.TextWordWrap, self.msg)
        p.setPen(QColor(255, 170, 80))
        p.setFont(self.hint_font)
        hint = (
            "Click to show in folder"
            if self.path and os.path.exists(self.path)
            else ("Click to dismiss" if self.path else "")
        )
        p.drawText(QRectF(18, self.height() - 28, self.width() - 36, 18), Qt.AlignVCenter, hint)

    def mousePressEvent(self, _):
        if self.path and os.path.exists(self.path):
            subprocess.Popen(["explorer", "/select,", os.path.normpath(self.path)])
        self.hide()


class DebugWin(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(f"ShiftWheel debugger v{VERSION}")
        self.resize(660, 420)
        self.setWindowFlag(Qt.WindowStaysOnTopHint)
        self.status = QLabel("...")
        self.status.setStyleSheet("font: 10pt Consolas; padding: 4px")
        self.box = QPlainTextEdit()
        self.box.setReadOnly(True)
        self.box.setMaximumBlockCount(1000)
        self.box.setStyleSheet("background:#12141c;color:#d7dae0;font:9pt Consolas")
        b1, b2 = QPushButton("Clear"), QPushButton("Copy log")
        b1.clicked.connect(self.box.clear)
        b2.clicked.connect(
            lambda: QApplication.clipboard().setText(self.box.toPlainText())
        )
        row = QHBoxLayout()
        row.addWidget(b1)
        row.addWidget(b2)
        row.addStretch()
        v = QVBoxLayout(self)
        v.addWidget(self.status)
        v.addWidget(self.box)
        v.addLayout(row)
        QTimer(self, interval=200, timeout=self.poll).start()

    def add_line(self, line):
        self.box.appendPlainText(line)

    def poll(self):
        if self.isVisible():
            lm = bool(u32.GetAsyncKeyState(0x01) & 0x8000)
            self.status.setText(
                f"{cfg['trigger'].capitalize()}: {'DOWN' if key_down() else 'up'}  |  "
                f"Left mouse: {'DOWN' if lm else 'up'}  |  Window: {fg_class()}  |  Hotkey: {cfg['hotkey'] or 'off'}"
            )


def startup_command():
    if getattr(sys, "frozen", False):
        return f'"{sys.executable}"'
    executable = Path(sys.executable)
    hidden = executable.with_name("pythonw.exe")
    if hidden.exists():
        executable = hidden
    return f'"{executable}" "{os.path.abspath(__file__)}"'


def startup_enabled():
    import winreg

    try:
        with winreg.OpenKey(
            winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Run"
        ) as key:
            return winreg.QueryValueEx(key, "ShiftWheel")[0] == startup_command()
    except OSError:
        return False


def set_startup(on):
    import winreg

    with winreg.CreateKeyEx(
        winreg.HKEY_CURRENT_USER,
        r"Software\Microsoft\Windows\CurrentVersion\Run",
        0,
        winreg.KEY_SET_VALUE,
    ) as key:
        if on:
            winreg.SetValueEx(key, "ShiftWheel", 0, winreg.REG_SZ, startup_command())
        else:
            try:
                winreg.DeleteValue(key, "ShiftWheel")
            except FileNotFoundError:
                pass


def main():
    if sys.platform != "win32":
        print(
            "ShiftWheel's Explorer integration requires Windows. Core tests can run on other systems."
        )
        return 1
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.CreateMutexW.argtypes = [ctypes.c_void_p, wintypes.BOOL, wintypes.LPCWSTR]
    kernel.CreateMutexW.restype = wintypes.HANDLE
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel.CloseHandle.restype = wintypes.BOOL
    mutex = kernel.CreateMutexW(None, False, "Local\\ShiftWheel.Desktop")
    if not mutex:
        raise ctypes.WinError(ctypes.get_last_error())
    if ctypes.get_last_error() == 183:
        u32.MessageBoxW(
            0,
            "ShiftWheel is already running. Use its tray icon. To update it, quit the running version first.",
            "ShiftWheel",
            0x40,
        )
        kernel.CloseHandle(mutex)
        return 0
    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)
    if not QSystemTrayIcon.isSystemTrayAvailable():
        QMessageBox.critical(
            None,
            "ShiftWheel",
            "The Windows notification area is unavailable. Restart Explorer and try again.",
        )
        kernel.CloseHandle(mutex)
        return 1
    bus, toast = Bus(), Toast()
    jobs = Jobs(bus)
    wheel, debugger = Wheel(bus, jobs), DebugWin()
    _sinks.append(bus.log.emit)
    bus.log.connect(debugger.add_line, Qt.QueuedConnection)
    bus.done.connect(toast.flash, Qt.QueuedConnection)
    bus.show.connect(wheel.pop, Qt.QueuedConnection)
    bus.summon.connect(
        lambda: wheel.hide() if wheel.isVisible() else wheel.pop(True),
        Qt.QueuedConnection,
    )

    def uncaught(kind, error, tb):
        detail = "".join(traceback.format_exception(kind, error, tb))
        dbg("UNCAUGHT", detail)
        path = make_report("Unexpected error", [], error, detail)
        bus.done.emit("An error occurred. Click to locate the report.", path)

    sys.excepthook = uncaught
    pixmap = QPixmap(64, 64)
    pixmap.fill(Qt.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.Antialiasing)
    painter.setBrush(QColor(255, 120, 60))
    painter.setPen(Qt.NoPen)
    painter.drawEllipse(4, 4, 56, 56)
    painter.setBrush(QColor(20, 20, 30))
    painter.drawEllipse(22, 22, 20, 20)
    painter.end()
    tray, menu = QSystemTrayIcon(QIcon(pixmap)), QMenu()

    def tooltip(*unused):
        message = (
            f"ShiftWheel v{VERSION} – hold {cfg['trigger'].capitalize()} and drag files"
        )
        tray.setToolTip(
            message
            + (
                "\nWorking…"
                if jobs.active
                else ("\n" + _last_result if _last_result else "")
            )
        )

    bus.busy.connect(tooltip)
    bus.done.connect(lambda *_: QTimer.singleShot(0, tooltip))
    triggers = menu.addMenu("Trigger key")
    trigger_group = QActionGroup(triggers)
    for key in VK:
        action = triggers.addAction(key.capitalize())
        action.setCheckable(True)
        action.setChecked(cfg["trigger"] == key)
        trigger_group.addAction(action)
        action.triggered.connect(
            lambda checked, k=key: (cfg.update(trigger=k), save_cfg(), tooltip())
        )
    for label, setting in (
        ("Save into a 'Converted' folder", "folder"),
        ("Trigger in any app", "anywhere"),
        ("Release on center = quick action", "quick"),
    ):
        action = menu.addAction(label)
        action.setCheckable(True)
        action.setChecked(cfg[setting])
        action.triggered.connect(
            lambda checked, k=setting: (cfg.update({k: checked}), save_cfg())
        )
    startup = menu.addAction("Start with Windows")
    startup.setCheckable(True)
    startup.setChecked(startup_enabled())

    def change_startup(checked):
        try:
            set_startup(checked)
        except OSError as error:
            startup.setChecked(startup_enabled())
            QMessageBox.warning(None, "Startup setting", str(error))

    startup.triggered.connect(change_startup)
    hotkeys = {"listener": None}

    def set_hotkey(spec):
        try:
            replacement = (
                keyboard.GlobalHotKeys({spec: bus.summon.emit}) if spec else None
            )
            if replacement:
                replacement.start()
            previous = hotkeys["listener"]
            hotkeys["listener"] = replacement
            if previous:
                previous.stop()
            cfg["hotkey"] = spec
            save_cfg()
        except Exception as error:
            bus.done.emit(f"Hotkey could not start: {error}", "")

    hotkey_menu = menu.addMenu("Summon hotkey")
    group = QActionGroup(hotkey_menu)
    for name, spec in HOTKEYS.items():
        action = hotkey_menu.addAction(name)
        action.setCheckable(True)
        action.setChecked(cfg["hotkey"] == spec)
        group.addAction(action)
        action.triggered.connect(lambda checked, value=spec: set_hotkey(value))

    def choose_language():
        language = _ask(
            "OCR language",
            "Installed Tesseract languages, e.g. eng, ron, spa or eng+ron.",
            cfg["ocr_language"],
        )
        if language is not None:
            if not re.fullmatch(r"[A-Za-z_]+(?:\+[A-Za-z_]+)*", language):
                QMessageBox.warning(
                    None, "OCR language", "Use language codes such as eng or eng+ron."
                )
                return
            cfg["ocr_language"] = language
            save_cfg()

    menu.addAction("OCR language…", choose_language)

    def locate_office():
        path, _ = QFileDialog.getOpenFileName(
            None,
            "Select LibreOffice program/soffice.com or soffice.exe",
            "",
            "LibreOffice (soffice.com soffice.exe);;All files (*)",
        )
        if path:
            if Path(path).name.lower() not in (
                "soffice.com",
                "soffice.exe",
                "soffice",
                "libreoffice",
            ):
                QMessageBox.warning(
                    None, "LibreOffice", "Select the LibreOffice soffice executable."
                )
                return
            cfg["libreoffice_path"] = path
            save_cfg()

    menu.addAction(
        "Supported formats and tools…",
        lambda: QMessageBox.information(
            None, "ShiftWheel conversion support", supported_formats_text()
        ),
    )
    menu.addAction("Locate LibreOffice…", locate_office)
    menu.addAction(
        "Use automatic LibreOffice detection",
        lambda: (cfg.update(libreoffice_path=""), save_cfg()),
    )

    def pick():
        if jobs.active:
            bus.done.emit("Please wait for the current job to finish.", "")
            return
        files, _ = QFileDialog.getOpenFileNames(None, "Choose files to convert")
        if not files:
            return
        actions = actions_for(files)
        label, ok = QInputDialog.getItem(
            None,
            "ShiftWheel",
            f"{len(files)} file(s) — choose an action:",
            [a[1] for a in actions],
            0,
            False,
            Qt.WindowStaysOnTopHint,
        )
        if ok:
            jobs.start(next(action for action in actions if action[1] == label), files)

    menu.addAction("Convert files… (no dragging)", pick)
    menu.addAction("Show wheel", lambda: wheel.pop(True))
    menu.addAction("Show debugger", lambda: (debugger.show(), debugger.raise_()))
    menu.addAction(
        "Open log file", lambda: os.path.exists(LOG_FILE) and os.startfile(LOG_FILE)
    )

    def diagnose(_paths):
        result = selftest()
        return make_report("Self-test " + ("passed" if result else "FAILED"), [])

    menu.addAction(
        "Save diagnostic report",
        lambda: jobs.start(
            H("", "Diagnostic", diagnose, True), [sys.executable if getattr(sys, "frozen", False) else os.path.abspath(__file__)]
        ),
    )

    def request_quit():
        if jobs.active:
            tray.showMessage(
                "ShiftWheel is working",
                "Let the current job finish before quitting. This protects incomplete output.",
            )
            return
        app.quit()

    bus.quit.connect(request_quit)
    menu.addSeparator()
    menu.addAction("Quit", request_quit)
    tray.setContextMenu(menu)
    tray.activated.connect(
        lambda reason: (
            bus.summon.emit()
            if reason == QSystemTrayIcon.ActivationReason.DoubleClick
            else None
        )
    )
    tray.show()
    tooltip()
    set_hotkey(cfg["hotkey"])
    state = {"start": None, "shown": False, "allowed": False}

    def on_click(x, y, button, pressed):
        if button == mouse.Button.left:
            state["start"] = (x, y) if pressed else None
            state["shown"] = False
            state["allowed"] = cfg["anywhere"] or fg_class() in EXPLORER

    def on_move(x, y):
        start = state["start"]
        if (
            start
            and not state["shown"]
            and state["allowed"]
            and key_down()
            and math.hypot(x - start[0], y - start[1]) >= 20
        ):
            state["shown"] = True
            bus.show.emit()

    listener = mouse.Listener(on_click=on_click, on_move=on_move)
    escape = keyboard.Listener(
        on_press=lambda key: bus.dismiss.emit() if key == keyboard.Key.esc else None
    )
    try:
        listener.start()
        escape.start()
        dbg(f"ShiftWheel v{VERSION} started; copies only; trigger = {cfg['trigger']}")
        tray.showMessage(
            "ShiftWheel is running",
            f"Hold {cfg['trigger'].capitalize()} and drag a file. Right-click the tray icon for settings.",
        )
        return app.exec()
    finally:
        listener.stop()
        escape.stop()
        if hotkeys["listener"]:
            hotkeys["listener"].stop()
        if jobs.thread and jobs.thread.is_alive():
            jobs.thread.join()
        _sinks.clear()
        tray.hide()
        kernel.CloseHandle(mutex)


if __name__ == "__main__":
    if "--package-check" in sys.argv:
        from package_check import run
        raise SystemExit(run())
    raise SystemExit(main())
