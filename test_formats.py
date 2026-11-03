"""Expanded-format regression checks. Install LibreOffice for Office integration tests.
Optionally set SHIFTWHEEL_SAMPLE_PPTX to a real presentation to verify all its slides.
"""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
import csv
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import xml.etree.ElementTree as ET
from zipfile import ZipFile

import pytest
from openpyxl import Workbook, load_workbook
from PySide6.QtWidgets import QApplication
import shiftwheel as sw


@pytest.fixture(autouse=True)
def settings(tmp_path, monkeypatch):
    monkeypatch.setitem(sw.cfg, "folder", False)
    monkeypatch.setitem(sw.cfg, "libreoffice_path", "")
    monkeypatch.setattr(sw, "LOG_FILE", str(tmp_path / "debug.log"))
    monkeypatch.setattr(sw, "DEBUG", False)
    for key in ("folder", "libreoffice_path"):
        if hasattr(sw._job_settings, key):
            monkeypatch.delattr(sw._job_settings, key)


@pytest.fixture
def office():
    if not sw.libreoffice_path():
        pytest.skip("LibreOffice is not installed")


@pytest.fixture
def table(tmp_path):
    path = tmp_path / "tabel română.csv"
    with path.open("w", encoding="utf-8-sig", newline="") as stream:
        csv.writer(stream).writerows(
            [
                ["Name", "Code", "Literal"],
                ["Paul, Andrei", "00123", "=2+2"],
                ["Ștefan", "00007", "two\nlines"],
            ]
        )
    return str(path)


@pytest.fixture
def workbook(tmp_path):
    path = tmp_path / "multiple sheets.xlsx"
    book = Workbook()
    sheet = book.active
    sheet.title = "First"
    sheet.append(["Name", "Value"])
    sheet.append(["Paul", 25])
    sheet.append(["Formula", "=B2*2"])
    sheet = book.create_sheet("Second")
    sheet.append(["Different", "Data"])
    sheet.append(["Ștefan", 123])
    book.create_sheet("Empty")
    book.save(path)
    book.close()
    return str(path)


@pytest.fixture
def rtf(tmp_path):
    path = tmp_path / "sample.rtf"
    path.write_text(
        r"{\rtf1\ansi\deff0 {\fonttbl {\f0 Arial;}}\f0\fs24 ShiftWheel test\par Second paragraph.}"
    )
    return str(path)


@pytest.mark.parametrize(
    "extension,kind",
    [
        ("ppt", "presentation"),
        ("pptx", "presentation"),
        ("ppsx", "presentation"),
        ("odp", "presentation"),
        ("docx", "document"),
        ("doc", "document"),
        ("rtf", "document"),
        ("odt", "document"),
        ("xls", "spreadsheet"),
        ("xlsx", "spreadsheet"),
        ("ods", "spreadsheet"),
        ("csv", "table"),
        ("tsv", "table"),
        ("json", "json"),
        ("exe", "other"),
    ],
)
def test_format_routing(extension, kind):
    assert sw.file_kind("TEST." + extension.upper()) == kind
    actions = sw.actions_for(["TEST." + extension.upper()])
    if kind in sw.OFFICE_INPUTS:
        assert actions[0][1] == "PDF"
        assert not any(a[1].lower() == extension for a in actions)
    elif kind == "other":
        assert actions[0][1] == "Format info"


def test_mixed_office_pdf_actions():
    actions = sw.actions_for(["a.pptx", "b.docx", "c.pdf"])
    assert [a[1] for a in actions[:2]] == ["Each → PDF", "Merge PDF"]
    assert all(sw.action_requires_office(a, ["a.pptx", "b.docx"]) for a in actions[:2])


def test_csv_json_roundtrip(table):
    before = Path(table).read_bytes()
    result = sw.table_convert(table, "json")
    assert json.loads(Path(result).read_text())[1] == ["Paul, Andrei", "00123", "=2+2"]
    converted = sw.table_convert(result, "csv")
    assert sw.table_rows(converted) == sw.table_rows(table)
    assert Path(table).read_bytes() == before


def test_csv_xlsx_literal_preservation(table):
    book = load_workbook(sw.table_convert(table, "xlsx"), data_only=False)
    assert book.active["B2"].value == "00123"
    assert book.active["C2"].value == "=2+2" and book.active["C2"].data_type == "s"
    assert book.active["C3"].value == "two\nlines"
    book.close()


def test_semicolon_and_tsv(tmp_path):
    path = tmp_path / "table.csv"
    path.write_text("Name;City\nPaul;Iași\n", encoding="utf-8")
    rows = sw.table_rows(str(path))
    assert rows == [["Name", "City"], ["Paul", "Iași"]]
    assert sw.table_rows(sw.table_convert(str(path), "tsv")) == rows


def test_flat_json_records_and_large_int(tmp_path):
    path = tmp_path / "data.json"
    path.write_text(
        json.dumps(
            [
                {"name": "Paul", "n": 12345678901234567890},
                {"name": "Ana", "extra": True},
            ]
        )
    )
    result = sw.table_convert(str(path), "xlsx")
    book = load_workbook(result)
    assert book.active["B2"].value == "12345678901234567890"
    assert book.active["C3"].value is True
    book.close()


@pytest.mark.parametrize(
    "data",
    [
        {"a": 1},
        [{"a": {"nested": 1}}],
        [1, 2],
        [["ok"], {"a": 1}],
        [],
        [[float("nan")]],
    ],
)
def test_invalid_table_json(tmp_path, data):
    path = tmp_path / "bad.json"
    path.write_text(json.dumps(data))
    with pytest.raises(ValueError):
        sw.table_convert(str(path), "xlsx")
    assert not list(tmp_path.glob("*.xlsx"))


def test_all_sheets_export(workbook):
    for extension in ("csv", "tsv", "json"):
        last = sw.spreadsheet_tables(workbook, extension)
        assert Path(last).exists() and last.endswith("_sheet3." + extension)
    first = Path(workbook).with_name("multiple sheets_sheet1.csv")
    assert "=B2*2" in first.read_text(encoding="utf-8-sig")
    second = Path(workbook).with_name("multiple sheets_sheet2.json")
    assert json.loads(second.read_text())[1] == ["Ștefan", 123]


def test_missing_office_error(monkeypatch, rtf):
    monkeypatch.setattr(sw, "libreoffice_path", lambda: None)
    with pytest.raises(RuntimeError, match="needs LibreOffice"):
        sw.office_convert(rtf, "pdf")
    assert not Path(rtf).with_suffix(".pdf").exists()


def test_missing_office_gui_message(monkeypatch, rtf):
    app = QApplication.instance() or QApplication([])
    messages = []
    monkeypatch.setattr(sw, "libreoffice_path", lambda: None)
    monkeypatch.setattr(
        sw.QMessageBox, "information", lambda *args: messages.append(args)
    )
    jobs = sw.Jobs(sw.Bus())
    jobs.start(sw.OFFICE_PDF, [rtf])
    assert messages and "LibreOffice" in messages[0][2]
    assert not jobs.active and jobs.thread is None
    app.processEvents()


def test_office_does_not_accept_zero_exit_without_output(monkeypatch, rtf):
    monkeypatch.setattr(sw, "require_office", lambda: "fake-soffice")
    monkeypatch.setattr(
        sw,
        "run_office_command",
        lambda command: subprocess.CompletedProcess(command, 0, "", ""),
    )
    with pytest.raises(RuntimeError, match="did not produce"):
        sw.office_convert(rtf, "pdf")
    assert not Path(rtf).with_suffix(".pdf").exists()


def test_office_failure_diagnostic(monkeypatch, rtf):
    monkeypatch.setattr(sw, "require_office", lambda: "fake-soffice")
    monkeypatch.setattr(
        sw,
        "run_office_command",
        lambda command: subprocess.CompletedProcess(
            command, 1, "", "bad document details"
        ),
    )
    with pytest.raises(RuntimeError, match="bad document details"):
        sw.office_convert(rtf, "pdf")


def test_process_timeout():
    with pytest.raises(RuntimeError, match="timed out"):
        sw.run_office_command(
            [sys.executable, "-c", "import time; time.sleep(20)"], timeout=0.1
        )


def test_isolated_profile_and_unicode_path(monkeypatch, rtf):
    observed = []
    monkeypatch.setattr(sw, "require_office", lambda: "fake-soffice")

    def run(command):
        observed.append(command)
        profile = next(
            arg for arg in command if arg.startswith("-env:UserInstallation=")
        )
        assert profile.startswith("-env:UserInstallation=file:///")
        assert command[-1].endswith("input.rtf")
        assert "--headless" in command
        return subprocess.CompletedProcess(command, 1, "", "test only")

    monkeypatch.setattr(sw, "run_office_command", run)
    for _ in range(2):
        with pytest.raises(RuntimeError):
            sw.office_convert(rtf, "pdf")
    assert observed[0][1] != observed[1][1]


@pytest.mark.parametrize("extension", ["pdf", "docx", "odt", "txt"])
def test_real_document_exports(office, rtf, extension):
    before = hashlib.sha256(Path(rtf).read_bytes()).hexdigest()
    result = sw.office_convert(rtf, extension)
    assert Path(result).stat().st_size > 0
    if extension == "pdf":
        with sw._fitz().open(result) as document:
            assert len(document) == 1 and "ShiftWheel test" in document[0].get_text()
    elif extension == "txt":
        assert "Second paragraph" in Path(result).read_text()
    else:
        with ZipFile(result) as archive:
            assert archive.testzip() is None
    assert hashlib.sha256(Path(rtf).read_bytes()).hexdigest() == before


def test_real_docx_input(office, rtf):
    docx = sw.office_convert(rtf, "docx")
    result = sw.office_convert(docx, "pdf")
    with sw._fitz().open(result) as doc:
        assert "ShiftWheel test" in doc[0].get_text()
    assert Path(sw.office_pages(docx, "png")).exists()


def test_real_spreadsheet_exports(office, workbook):
    result = sw.office_convert(workbook, "pdf")
    with sw._fitz().open(result) as document:
        text = " ".join(page.get_text() for page in document)
        assert "Paul" in text and "Different" in text
    ods = sw.office_convert(workbook, "ods")
    back = sw.office_convert(ods, "xlsx")
    book = load_workbook(back)
    assert book.worksheets[0]["B2"].value == 25
    book.close()
    assert Path(sw.spreadsheet_tables(ods, "csv")).exists()


def test_real_mixed_document_merge(office, rtf, tmp_path):
    text = tmp_path / "note.txt"
    text.write_text("Second document")
    result = sw.merge_documents([rtf, str(text)])
    with sw._fitz().open(result) as document:
        assert len(document) == 2 and "Second document" in document[1].get_text()


def test_real_presentation_roundtrip(office, tmp_path):
    source = os.environ.get("SHIFTWHEEL_SAMPLE_PPTX")
    if not source:
        pytest.skip("Set SHIFTWHEEL_SAMPLE_PPTX to test a real deck")
    local = tmp_path / "presentation.pptx"
    local.write_bytes(Path(source).read_bytes())
    with ZipFile(local) as archive:
        root = ET.fromstring(archive.read("ppt/presentation.xml"))
        slides = len(
            root.find(
                "{http://schemas.openxmlformats.org/presentationml/2006/main}sldIdLst"
            )
        )
    result = sw.office_convert(str(local), "pdf")
    with sw._fitz().open(result) as document:
        assert len(document) == slides
    odp = sw.office_convert(str(local), "odp")
    back = sw.office_convert(odp, "pptx")
    with ZipFile(back) as archive:
        root = ET.fromstring(archive.read("ppt/presentation.xml"))
        assert (
            len(
                root.find(
                    "{http://schemas.openxmlformats.org/presentationml/2006/main}sldIdLst"
                )
            )
            == slides
        )


def test_missing_ffmpeg_gui_message(monkeypatch, tmp_path):
    app = QApplication.instance() or QApplication([])
    path = tmp_path / "video.mp4"
    path.write_bytes(b"fixture")
    messages = []
    monkeypatch.setattr(sw.shutil, "which", lambda name: None)
    monkeypatch.setattr(
        sw.QMessageBox, "information", lambda *args: messages.append(args)
    )
    jobs = sw.Jobs(sw.Bus())
    jobs.start(sw.SETS["video"][0], [str(path)])
    assert messages and "FFmpeg" in messages[0][2]
    assert not jobs.active
    app.processEvents()


def test_presentation_export_includes_hidden_slides_setting(monkeypatch, tmp_path):
    path = tmp_path / "sample.pptx"
    path.write_bytes(b"fixture")
    monkeypatch.setattr(sw, "require_office", lambda: "fake-soffice")

    def run(command):
        filter_spec = command[command.index("--convert-to") + 1]
        assert (
            json.loads(filter_spec.split(":", 2)[2])["ExportHiddenSlides"]["value"]
            == "true"
        )
        return subprocess.CompletedProcess(command, 1, "", "test only")

    monkeypatch.setattr(sw, "run_office_command", run)
    with pytest.raises(RuntimeError):
        sw.office_convert(str(path), "pdf")
