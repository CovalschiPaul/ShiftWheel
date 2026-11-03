# Build on Windows using the provided build script.
from PyInstaller.utils.hooks import collect_all
from pathlib import Path
root = Path(SPECPATH)
datas = [(str(root / "SUPPORTED_FORMATS.md"), ".")]
binaries = []
hiddenimports = ["package_check", "pynput.keyboard._win32", "pynput.mouse._win32"]
for package in ("PIL", "pypdf", "pymupdf", "openpyxl", "pillow_heif", "pytesseract"):
    d, b, h = collect_all(package)
    datas += d
    binaries += b
    hiddenimports += h
a = Analysis([str(root / "shiftwheel.py")], pathex=[str(root)], binaries=binaries,
             datas=datas, hiddenimports=hiddenimports, excludes=["tkinter", "PyQt5", "PyQt6"])
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name="ShiftWheel",
          console=False, icon=str(root / "assets" / "shiftwheel.ico"))
coll = COLLECT(exe, a.binaries, a.datas, name="ShiftWheel")
