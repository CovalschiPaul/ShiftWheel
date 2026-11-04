"""Regression tests: run python -m pytest -q (Qt uses an offscreen surface)."""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
import hashlib
import math
from pathlib import Path
import subprocess
import threading
import time
import zipfile

import pytest
from PIL import Image, ImageDraw, ImageFont
from PySide6.QtCore import QPointF, QMimeData, QUrl, Qt, QThread
from PySide6.QtGui import QDragEnterEvent, QDropEvent
from PySide6.QtWidgets import QApplication
from PySide6.QtTest import QTest
import shiftwheel as sw


@pytest.fixture(scope="session")
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture(autouse=True)
def config(tmp_path, monkeypatch):
    monkeypatch.setitem(sw.cfg, "folder", False)
    monkeypatch.setitem(sw.cfg, "ocr_language", "eng")
    monkeypatch.setitem(sw.cfg, "quick", True)
    monkeypatch.setattr(sw, "LOG_FILE", str(tmp_path / "debug.log"))
    monkeypatch.setattr(sw, "DEBUG", False)


@pytest.fixture
def photo(tmp_path):
    p = tmp_path / "photo.png"
    Image.new("RGBA", (80, 60), (220, 40, 60, 100)).save(p)
    return str(p)


@pytest.fixture
def pdf(tmp_path):
    p = tmp_path / "sample.pdf"
    with sw._fitz().open() as doc:
        for n in range(3):
            page = doc.new_page(width=300, height=300)
            page.insert_text((30, 50), f"Page {n + 1} test text")
        doc.save(p)
    return str(p)


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


@pytest.mark.parametrize(
    "value", ["0", "-1", "nan", "inf", "0%", "-2%", "1001%", "3.5", "hello", "32769"]
)
def test_bad_resize(value):
    with pytest.raises(ValueError):
        sw.parse_size(value)


@pytest.mark.parametrize("speed", [0, -1, float("nan"), float("inf"), 0.01, 17])
def test_bad_speed(speed):
    with pytest.raises(ValueError):
        sw._atempo_chain(speed)


@pytest.mark.parametrize("speed", [0.05, 0.5, 1, 2, 3, 16])
def test_audio_speed_chain(speed):
    values = [float(x.split("=")[1]) for x in sw._atempo_chain(speed).split(",")]
    assert all(0.5 <= v <= 2 for v in values)
    assert math.prod(values) == pytest.approx(speed, rel=1e-3)


@pytest.mark.parametrize(
    "value", ["0", "-1", "4", "3-1", "1-5", "1,", "1,,2", "a", "1.5", ""]
)
def test_bad_page_ranges(value):
    with pytest.raises(ValueError):
        sw.parse_pages(value, 3)


def test_pages_order():
    assert sw.parse_pages("3, 1-2", 3) == [2, 0, 1]


@pytest.mark.parametrize(
    "pattern",
    [
        "../bad",
        "{name!r}",
        "{name:20}",
        "{n.__class__}",
        "{oops}",
        "{",
        "CON",
        "AUX.txt",
        "bad?",
        "bad.",
        "bad ",
        "",
    ],
)
def test_bad_rename(photo, pattern):
    with pytest.raises((ValueError, KeyError)):
        sw.rename_plan([photo], pattern)


def test_rename_copy_preserves_original(photo):
    before = digest(photo)
    source, target = sw.rename_plan([photo], "{name}_{n}")[0]
    sw.copy_named(source, target)
    assert digest(photo) == digest(target) == before
    with pytest.raises(ValueError):
        sw.rename_plan([photo], "{name}_{n}")
    with pytest.raises(ValueError):
        sw.copy_named(source, target)


def test_collision_safe_atomic_output(photo, tmp_path):
    before = digest(photo)
    results = []

    def work():
        results.append(sw.im_save("PNG", "png")(photo))

    threads = [threading.Thread(target=work) for _ in range(6)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert len(set(results)) == 6
    assert all(Image.open(p).size == (80, 60) for p in results)
    assert digest(photo) == before
    assert not list(tmp_path.glob(".shiftwheel-*"))


def test_failed_output_not_published(photo, tmp_path):
    def bad(target):
        Path(target).write_text("incomplete")
        raise RuntimeError("failed")

    before = set(tmp_path.iterdir())
    with pytest.raises(RuntimeError):
        sw.write_output(photo, "txt", bad)
    assert set(tmp_path.iterdir()) == before


@pytest.mark.parametrize("ext", ["png", "jpg", "webp", "pdf"])
def test_image_convert(photo, ext):
    before = digest(photo)
    result = sw.im_save("", ext)(photo)
    assert Path(result).stat().st_size > 0 and digest(photo) == before
    if ext == "jpg":
        with Image.open(result) as im:
            assert im.mode == "RGB" and im.getpixel((1, 1))[0] > 200


def test_image_resize_crop_watermark(photo):
    assert Image.open(sw.resize_file(photo, sw.parse_size("50%"))).size == (40, 30)
    assert Image.open(sw.crop_file(photo, (0, 0, 80, 60))).size == (80, 60)
    result = sw.watermark_file(photo, ("Test", "Center", 12, 0.6))
    with Image.open(result) as im:
        assert im.mode == "RGBA"
    with pytest.raises(ValueError):
        sw.crop_file(photo, (0, 0, 90, 60))


def test_exif_orientation_and_clean(tmp_path):
    p = tmp_path / "phone.jpg"
    im = Image.new("RGB", (80, 40), "red")
    exif = im.getexif()
    exif[274] = 6
    exif[315] = "Author"
    im.save(p, exif=exif)
    assert sw.load_image(p).size == (40, 80)
    cleaned = sw.im_edit("_clean", lambda x: x)(str(p))
    with Image.open(cleaned) as result:
        assert result.size == (40, 80) and not result.getexif()


def test_heic_conversion(tmp_path, app):
    pytest.importorskip("pillow_heif")
    p = tmp_path / "phone.heic"
    Image.new("RGB", (80, 40), "red").save(p, "HEIF")
    result = sw.im_edit("_rot", lambda x: x.rotate(90, expand=True))(str(p))
    assert result.endswith(".png") and Image.open(result).size == (40, 80)
    dialog = sw.CropDlg(str(p))
    wait_for(app, lambda: dialog.full is not None)
    assert dialog.full.width() == 80
    dialog.close()


def test_pdf_actions(pdf, photo):
    before = digest(pdf)
    assert "Page 1" in Path(sw.pdf_text(pdf)).read_text()
    assert len(sw._fitz().open(sw.split_file(pdf, "3,1"))) == 2
    assert len(sw._fitz().open(sw.merge([pdf, photo]))) == 4
    assert len(sw._fitz().open(sw.pdf_small(pdf))) == 3
    assert sw._fitz().open(sw.pdf_rotate90(pdf))[0].rotation == 90
    assert len(sw._fitz().open(sw.clean_pdf(pdf))) == 3
    for ext in ["png", "jpg"]:
        assert Path(sw.pdf_pages(ext)(pdf)).exists()
    assert digest(pdf) == before


def test_blank_pdf_text_error(tmp_path):
    p = tmp_path / "blank.pdf"
    with sw._fitz().open() as doc:
        doc.new_page()
        doc.save(p)
    with pytest.raises(ValueError, match="OCR"):
        sw.pdf_text(str(p))


def test_text_conversion_unicode(tmp_path):
    p = tmp_path / "text.txt"
    p.write_text("Română și español\n" * 100, encoding="utf-8")
    result = sw.txt_pdf(str(p))
    with sw._fitz().open(result) as doc:
        assert len(doc) > 1 and "Română" in doc[0].get_text()
    assert len(sw._fitz().open(sw.txt_merge([str(p), str(p)]))) >= 4


def test_zip_folders_and_output_exclusion(tmp_path, monkeypatch):
    directory = tmp_path / "source"
    directory.mkdir()
    (directory / "empty").mkdir()
    (directory / "a.txt").write_text("hello")
    monkeypatch.setitem(sw.cfg, "folder", True)
    result = sw.zipit([str(directory)])
    with zipfile.ZipFile(result) as archive:
        assert archive.namelist() == ["source/", "source/empty/", "source/a.txt"]
        assert archive.read("source/a.txt") == b"hello"


def test_zip_duplicate_names(tmp_path):
    a = tmp_path / "a"
    b = tmp_path / "b"
    a.mkdir()
    b.mkdir()
    (a / "x.txt").write_text("a")
    (b / "x.txt").write_text("b")
    with pytest.raises(ValueError):
        sw.zipit([str(a / "x.txt"), str(b / "x.txt")])


def test_action_routing(photo, pdf, tmp_path):
    assert [x[1] for x in sw.actions_for([photo, pdf])] == [
        "Merge PDF",
        "Zip",
        "Rename copies",
        "Copy path",
        "Open folder",
    ]
    assert sw.actions_for([photo, str(tmp_path / "song.mp3")]) == sw.COMMON
    folder = tmp_path / "folder.png"
    folder.mkdir()
    assert sw.actions_for([str(folder)]) == sw.COMMON


@pytest.mark.parametrize("kind", list(sw.SETS))
def test_pages_include_every_action(kind):
    actions = sw.SETS[kind]
    pages = sw.action_pages(actions)
    assert all(len(page) <= 8 for page in pages)
    assert [action for page in pages for action in page if action[2]] == actions


def wait_for(app, predicate, timeout=5):
    end = time.monotonic() + timeout
    while not predicate() and time.monotonic() < end:
        app.processEvents()
        # Yield the GIL so the Python worker can progress on Windows too.
        time.sleep(0.005)
    assert predicate()


def test_wheel_animation_paging_and_gap(app):
    wheel = sw.Wheel(sw.Bus())
    wheel.pop(True)
    for _ in range(70):
        wheel.step()
    assert not wheel.tick.isActive()
    assert wheel.idx(QPointF(wheel.S / 2, wheel.S / 2)) == -2
    angle = math.radians(22.5)
    assert (
        wheel.idx(
            QPointF(
                wheel.S / 2 + 130 * math.sin(angle), wheel.S / 2 - 130 * math.cos(angle)
            )
        )
        == -1
    )
    wheel.next_page()
    assert wheel.page == 1 and wheel.more_blocked
    wheel.bus.dismiss.emit()
    app.processEvents()
    assert not wheel.isVisible()


def test_real_drop_copy_action(app, photo):
    bus = sw.Bus()
    wheel = sw.Wheel(bus)
    wheel.pop(True)
    mime = QMimeData()
    mime.setUrls([QUrl.fromLocalFile(photo)])
    point = QPointF(wheel.S / 2, wheel.S / 2 - 130)
    enter = QDragEnterEvent(
        point.toPoint(),
        Qt.CopyAction | Qt.MoveAction,
        mime,
        Qt.LeftButton,
        Qt.ShiftModifier,
    )
    wheel.dragEnterEvent(enter)
    assert enter.isAccepted() and enter.dropAction() == Qt.CopyAction
    drop = QDropEvent(
        point, Qt.CopyAction | Qt.MoveAction, mime, Qt.LeftButton, Qt.ShiftModifier
    )
    wheel.dropEvent(drop)
    assert drop.isAccepted() and drop.dropAction() == Qt.CopyAction
    wait_for(app, lambda: bool(list(Path(photo).parent.glob("photo_*.png"))))
    wait_for(app, lambda: not wheel.jobs.active)
    assert Path(photo).exists()


def test_empty_nonlocal_drag_rejected(app):
    wheel = sw.Wheel(sw.Bus())
    mime = QMimeData()
    mime.setUrls([QUrl("https://example.org/a.png")])
    event = QDragEnterEvent(
        QPointF(100, 100).toPoint(), Qt.CopyAction, mime, Qt.LeftButton, Qt.NoModifier
    )
    wheel.dragEnterEvent(event)
    assert not event.isAccepted()


def test_jobs_worker_and_busy_guard(app, photo):
    bus = sw.Bus()
    jobs = sw.Jobs(bus)
    seen = []
    release = threading.Event()
    started = threading.Event()

    def operation(path):
        seen.append(QThread.currentThread() != app.thread())
        started.set()
        release.wait(3)
        return path

    jobs.start(sw.H("", "Slow", operation), [photo])
    assert jobs.active and started.wait(1)
    jobs.start(sw.H("", "Second", lambda p: seen.append("second")), [photo])
    timer = []
    sw.QTimer.singleShot(0, lambda: timer.append(True))
    app.processEvents()
    assert timer
    release.set()
    wait_for(app, lambda: not jobs.active)
    assert seen == [True]


def test_clipboard_on_main_thread(app, photo):
    jobs = sw.Jobs(sw.Bus())
    jobs.start(next(a for a in sw.COMMON if a[1] == "Copy path"), [photo])
    assert app.clipboard().text() == os.path.normpath(photo) and not jobs.active


def test_worker_partial_failures_report_all(app, photo, tmp_path, monkeypatch):
    bus = sw.Bus()
    jobs = sw.Jobs(bus)
    reports = []
    messages = []
    monkeypatch.setattr(
        sw,
        "make_report",
        lambda *args: reports.append(args) or str(tmp_path / "report.txt"),
    )
    bus.done.connect(lambda *args: messages.append(args))
    other = tmp_path / "bad.png"
    other.write_text("bad")
    jobs.start(sw.H("", "Convert", sw.im_save("PNG", "png")), [photo, str(other)])
    wait_for(app, lambda: not jobs.active)
    assert reports and str(other) in reports[0][3]
    assert any("1/2 completed" in message for message, _ in messages)


@pytest.fixture
def video(tmp_path):
    p = tmp_path / "with_audio.mp4"
    sw._ff(
        [
            "-f",
            "lavfi",
            "-i",
            "color=c=blue:s=160x120:r=20:d=2",
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=440:duration=2",
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "aac",
            "-shortest",
            str(p),
        ]
    )
    return str(p)


def streams(path):
    import json

    data = subprocess.check_output(
        ["ffprobe", "-v", "error", "-show_streams", "-show_format", "-of", "json", path]
    )
    return json.loads(data)


def test_real_video_speed_with_audio(video):
    result = sw.speed_file(video, 2)
    info = streams(result)
    assert {s["codec_type"] for s in info["streams"]} == {"audio", "video"}
    assert 0.8 < float(info["format"]["duration"]) < 1.3


def test_real_video_speed_silent(video):
    silent = sw.ffm("mp4", ["-an", "-c:v", "copy"], "_silent")(video)
    result = sw.speed_file(silent, 2)
    assert [s["codec_type"] for s in streams(result)["streams"]] == ["video"]


def test_video_actions(video):
    assert Image.open(sw.vid_frame(video)).size == (160, 120)
    assert Path(sw.ffm("gif", ["-vf", "fps=12,scale=80:-1"])(video)).stat().st_size > 0
    assert float(streams(sw.trim_file(video, 0.5, 1.5))["format"]["duration"]) < 1.7
    assert Path(sw.clean_av(video)).exists()


def test_ffmpeg_failure_has_details(tmp_path):
    p = tmp_path / "invalid.mp4"
    p.write_bytes(b"bad")
    with pytest.raises(sw.MediaError, match="FFmpeg could not"):
        sw.ffm("mp4", sw.V264)(str(p))
    assert list(tmp_path.iterdir()) == [p]


def test_ocr_missing_engine(monkeypatch, photo):
    monkeypatch.setattr(sw, "tesseract_path", lambda: None)
    with pytest.raises(RuntimeError, match="Tesseract OCR is missing"):
        sw.ocr_image(photo)


def test_pdf_ocr_error_does_not_fallback(monkeypatch, pdf, tmp_path):
    class Engine:
        def image_to_string(self, *a, **kw):
            raise RuntimeError("recognition crashed")

    monkeypatch.setattr(sw, "ocr_engine", lambda: (Engine(), "eng"))
    with pytest.raises(RuntimeError, match="OCR failed on page 1"):
        sw.ocr_pdf(pdf)
    assert not list(tmp_path.glob("*_ocr.txt"))


def test_real_ocr(tmp_path):
    if not sw.tesseract_path():
        pytest.skip("Tesseract not installed")
    image = Image.new("RGB", (1000, 160), "white")
    draw = ImageDraw.Draw(image)
    font = ImageFont.truetype(sw._FONT, 48)
    draw.text((25, 40), "SHIFTWHEEL TEST 12345", fill="black", font=font)
    p = tmp_path / "scan.png"
    image.save(p)
    assert "12345" in Path(sw.ocr_image(str(p))).read_text()
    pdf = tmp_path / "scan.pdf"
    image.save(pdf, "PDF")
    assert "12345" in Path(sw.ocr_pdf(str(pdf))).read_text()


def test_no_console_does_not_crash(monkeypatch):
    monkeypatch.setattr(sw.sys, "stdout", None)
    monkeypatch.setattr(sw, "DEBUG", True)
    sw.dbg("safe pythonw logging")


@pytest.mark.parametrize(
    "position", ["Bottom-right", "Bottom-left", "Top-right", "Top-left", "Center"]
)
def test_watermark_positions(photo, position):
    result = sw.watermark_file(photo, ("ABC", position, 16, 0.8))
    assert Image.open(result).size == (80, 60)


@pytest.mark.parametrize(
    "label",
    [
        "Rot 90°",
        "Rot -90°",
        "Flip H",
        "Flip V",
        "Grayscale",
        "Clear metadata",
        "Compress",
    ],
)
def test_remaining_image_actions(photo, label):
    action = next(a for a in sw.SETS["image"] if a[1] == label)
    result = action[2](photo)
    with Image.open(result) as image:
        expected = (60, 80) if label.startswith("Rot ") else (80, 60)
        assert image.size == expected


@pytest.mark.parametrize("label", ["MP4", "WebM", "MP3", "Compress", "720p", "Mute"])
def test_video_menu_conversions(video, label):
    action = next(a for a in sw.SETS["video"] if a[1] == label)
    output = action[2](video)
    info = streams(output)
    if label == "Mute":
        assert all(s["codec_type"] != "audio" for s in info["streams"])
    if label == "720p":
        assert (
            next(s for s in info["streams"] if s["codec_type"] == "video")["height"]
            == 720
        )
    assert info["streams"]


@pytest.mark.parametrize("label", ["MP3", "WAV", "FLAC", "M4A", "Small MP3"])
def test_audio_menu_conversions(video, label):
    audio = sw.ffm("wav", ["-vn"])(video)
    action = next(a for a in sw.SETS["audio"] if a[1] == label)
    output = action[2](audio)
    assert [s["codec_type"] for s in streams(output)["streams"]] == ["audio"]


def test_real_hover_dwell_requires_exit(app, photo):
    from PySide6.QtGui import QDragMoveEvent

    wheel = sw.Wheel(sw.Bus())
    wheel.pop(True)
    wheel.files = [photo]
    # More is always slot seven, including the last page.
    angle = math.radians(315)
    point = QPointF(
        wheel.S / 2 + 130 * math.sin(angle), wheel.S / 2 - 130 * math.cos(angle)
    ).toPoint()
    mime = QMimeData()
    mime.setUrls([QUrl.fromLocalFile(photo)])

    def move(point):
        event = QDragMoveEvent(
            point, Qt.CopyAction | Qt.MoveAction, mime, Qt.LeftButton, Qt.ShiftModifier
        )
        wheel.dragMoveEvent(event)

    move(point)
    wait_for(app, lambda: wheel.page == 1)
    move(point)
    QTest.qWait(650)
    app.processEvents()
    assert wheel.page == 1
    move(QPointF(wheel.S / 2, wheel.S / 2 - 130).toPoint())
    move(point)
    wait_for(app, lambda: wheel.page == 2)
    wheel.hide()


def test_drop_more_runs_no_job(app, photo):
    wheel = sw.Wheel(sw.Bus())
    wheel.pop(True)
    wheel.files = [photo]
    angle = math.radians(315)
    point = QPointF(
        wheel.S / 2 + 130 * math.sin(angle), wheel.S / 2 - 130 * math.cos(angle)
    )
    mime = QMimeData()
    mime.setUrls([QUrl.fromLocalFile(photo)])
    event = QDropEvent(
        point, Qt.CopyAction | Qt.MoveAction, mime, Qt.LeftButton, Qt.ShiftModifier
    )
    wheel.dropEvent(event)
    app.processEvents()
    assert event.dropAction() == Qt.CopyAction and not wheel.jobs.active
    assert not list(Path(photo).parent.glob("photo_*.png"))


def test_crop_coordinates_include_last_pixel(app, photo):
    dialog = sw.CropDlg(photo)
    wait_for(app, lambda: dialog.full is not None)
    dialog.sel = sw.QRect(0, 0, dialog.pm.width(), dialog.pm.height())
    assert dialog.box() == (0, 0, 80, 60)
    dialog.close()


def test_malformed_configuration_ignored(tmp_path):
    base = tmp_path / "settings"
    folder = base / "ShiftWheel"
    folder.mkdir(parents=True)
    (folder / "config.json").write_text(
        '{"trigger": [], "hotkey": {}, "folder": "true", "quick": null}'
    )
    env = dict(os.environ, APPDATA=str(base), PYTHONPATH=str(Path(sw.__file__).parent))
    result = subprocess.run(
        [
            sw.sys.executable,
            "-c",
            'import shiftwheel as s; assert s.cfg["trigger"]=="shift"; assert s.cfg["folder"] is False',
        ],
        env=env,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr


def test_cancelled_dialog_resets_busy(app, photo, monkeypatch):
    monkeypatch.setattr(sw, "_ask", lambda *a: None)
    jobs = sw.Jobs(sw.Bus())
    jobs.start(sw.H("", "Resize", sw.resize_img, "ui"), [photo])
    assert not jobs.active and jobs.thread is None


def test_snapshot_settings(app, photo, tmp_path, monkeypatch):
    release = threading.Event()
    started = threading.Event()

    def work(p):
        started.set()
        release.wait(3)
        return sw.im_save("PNG", "png")(p)

    jobs = sw.Jobs(sw.Bus())
    jobs.start(sw.H("", "Convert", work), [photo])
    assert started.wait(1)
    monkeypatch.setitem(sw.cfg, "folder", True)
    release.set()
    wait_for(app, lambda: not jobs.active)
    assert (tmp_path / "photo_1.png").exists() and not (tmp_path / "Converted").exists()


def test_real_input_dialog_accept_and_cancel(app):
    def accept():
        dialog = next(
            w
            for w in app.topLevelWidgets()
            if isinstance(w, sw.QInputDialog) and w.isVisible()
        )
        dialog.setTextValue("50%")
        dialog.accept()

    sw.QTimer.singleShot(0, accept)
    assert sw._ask("Resize", "Size", "100") == "50%"

    def cancel():
        dialog = next(
            w
            for w in app.topLevelWidgets()
            if isinstance(w, sw.QInputDialog) and w.isVisible()
        )
        dialog.reject()

    sw.QTimer.singleShot(0, cancel)
    assert sw._ask("Resize", "Size", "100") is None


def test_watermark_dialog(app):
    dialog = sw.WatermarkDlg()
    dialog.txt.setText("Paul")
    dialog.pos.setCurrentText("Center")
    assert dialog.values() == ("Paul", "Center", 24, 0.6)
    dialog.close()


def test_diagnostic_selftest(tmp_path):
    assert sw.selftest()


def test_move_only_drag_rejected(app, photo):
    wheel = sw.Wheel(sw.Bus())
    mime = QMimeData()
    mime.setUrls([QUrl.fromLocalFile(photo)])
    event = QDragEnterEvent(
        QPointF(230, 100).toPoint(),
        Qt.MoveAction,
        mime,
        Qt.LeftButton,
        Qt.ShiftModifier,
    )
    wheel.dragEnterEvent(event)
    assert not event.isAccepted()
