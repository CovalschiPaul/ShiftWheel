"""Executable smoke test; does not start hooks, tray, or modify preferences."""
import importlib
import json
import sys
import tempfile
from pathlib import Path


def run():
    report = {"ok": False, "checks": []}
    target = Path(sys.argv[sys.argv.index("--report") + 1]) if "--report" in sys.argv else Path(tempfile.gettempdir()) / "ShiftWheel-package-check.json"
    try:
        for module in ("PySide6.QtWidgets", "PIL.Image", "pypdf", "pymupdf", "openpyxl", "pillow_heif", "pytesseract"):
            importlib.import_module(module)
            report["checks"].append(module)
        if sys.platform == "win32":
            importlib.import_module("pynput")
        from PIL import Image
        import pymupdf
        from openpyxl import Workbook, load_workbook
        from PySide6.QtWidgets import QApplication, QWidget
        app = QApplication.instance() or QApplication([])
        widget = QWidget()
        widget.resize(100, 100)
        app.processEvents()
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            image = root / "image.png"
            Image.new("RGB", (16, 12), "orange").save(image)
            with Image.open(image) as im:
                im.save(root / "image.jpg")
            with Image.open(root / "image.jpg") as im:
                assert im.size == (16, 12)
            with pymupdf.open() as doc:
                doc.new_page().insert_text((40, 40), "ShiftWheel")
                doc.save(root / "sample.pdf")
            from pypdf import PdfReader
            assert "ShiftWheel" in PdfReader(root / "sample.pdf").pages[0].extract_text()
            book = Workbook()
            book.active["A1"] = "00123"
            book.save(root / "sample.xlsx")
            loaded = load_workbook(root / "sample.xlsx")
            assert loaded.active["A1"].value == "00123"
            loaded.close()
        widget.close()
        report["checks"].extend(["Qt widget", "PNG to JPEG", "PDF write/read", "XLSX write/read"])
        report["ok"] = True
    except Exception:
        import traceback
        report["error"] = traceback.format_exc()
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(report, indent=2), encoding="utf-8")
    return 0 if report["ok"] else 1
