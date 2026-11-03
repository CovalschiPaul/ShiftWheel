import sys
import shiftwheel as sw
from package_check import run


def test_frozen_startup_uses_executable(monkeypatch):
    monkeypatch.setattr(sys, 'frozen', True, raising=False)
    monkeypatch.setattr(sys, 'executable', r'C:\Program Files\ShiftWheel\ShiftWheel.exe')
    assert sw.startup_command() == '"C:\\Program Files\\ShiftWheel\\ShiftWheel.exe"'


def test_frozen_missing_library_gives_repair_message(monkeypatch):
    monkeypatch.setattr(sys, 'frozen', True, raising=False)
    message = sw.explain(ModuleNotFoundError('missing module'))
    assert 'reinstall' in message and 'pip' not in message


def test_package_check_runs_conversions(monkeypatch, tmp_path):
    import json
    report = tmp_path / 'check.json'
    monkeypatch.setattr(sys, 'argv', ['ShiftWheel', '--package-check', '--report', str(report)])
    assert run() == 0
    result = json.loads(report.read_text())
    assert result['ok']
    assert 'PNG to JPEG' in result['checks']


def test_toast_expands_for_long_result():
    from PySide6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication([])
    toast = sw.Toast()
    toast.flash('Done', '')
    short_height = toast.height()
    toast.flash('A long conversion result explaining where the output was saved. ' * 6, '')
    assert toast.height() > short_height
    assert toast.toolTip() == toast.msg
    assert toast.width() <= 420
    toast.hide()
    app.processEvents()
