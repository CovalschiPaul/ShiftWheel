# ShiftWheel 3.3 conversion boundaries

The menu offers supported source-to-target pairs. It cannot meaningfully convert every file to every format.

| Input family | Recognized inputs | Outputs / operations | Extra requirement |
|---|---|---|---|
| Presentations | PPT, PPTX, PPS, PPSX, ODP | PDF; all rendered slides as PNG/JPG; text; PPTX/ODP; merge PDF | LibreOffice |
| Documents | DOC, DOCX, ODT, RTF | PDF, DOCX, ODT, RTF, TXT; all pages as PNG/JPG; merge PDF | LibreOffice |
| Spreadsheets | XLS, XLSX, ODS | PDF, XLSX, ODS; every sheet to separate CSV/TSV/JSON | LibreOffice for format conversion; XLSX sheet export works without it |
| Delimited tables | CSV, TSV | XLSX, JSON arrays, CSV, TSV; raw-text PDF | openpyxl included by setup |
| JSON | JSON | Raw-text PDF; flat rows/objects to XLSX/CSV/TSV | openpyxl for XLSX |
| Images | PNG, JPG/JPEG/JPE, WebP, BMP, GIF, TIF/TIFF, HEIC/HEIF, AVIF, ICO | PNG, JPG, WebP, PDF, BMP, TIFF; resize, crop, watermark, rotation, flips, grayscale, metadata removal, OCR | Pillow; pillow-heif for HEIC/HEIF; codec availability can vary with Pillow version |
| PDFs | PDF | Page PNG/JPG, embedded text, OCR text, merge, page extraction, rotation, compression, metadata removal | Included Python libraries; Tesseract for OCR |
| Videos | MP4, MOV, MKV, AVI, WebM, M4V, MPG/MPEG, WMV, FLV, MTS/M2TS/TS, 3GP, OGV | MP4, WebM, GIF, extracted MP3, first-frame PNG, compression, 720p, speed, trim, mute | FFmpeg, with the input/output codec supported by its build |
| Audio | MP3, WAV/WAVE, M4A, FLAC, OGG, AAC, Opus, AIF/AIFF, WMA, AMR, AC3 | MP3, WAV, FLAC, M4A, OGG, Opus, trim, metadata removal | FFmpeg |
| Text and source | TXT, MD/Markdown, LOG, XML, INI, TEXT, PY, BAT/CMD, JS, HTML/HTM, CSS, YAML/YML, TOML, SQL, C/CPP/H, CS, JAVA, SH, PS1, SRT/VTT, RST | PDF of source text, merged text PDF | Included Python libraries |
| Any file/folder | Including unsupported types | ZIP, copy path, open folder; renamed copies for files | No format conversion implied |

## Fidelity and data limits

- The app converts extensions listed above; recognition is not a guarantee that every damaged, encrypted, mislabeled or codec-dependent variant can decode.
- LibreOffice rendering can differ from Microsoft Office because of fonts, chart features, embedded media or layout behavior. Presentation PDF/image exports include hidden slides. PDF/image outputs are static. Animations, slide transitions and interactive controls do not survive static exports.
- Office PDF conversion uses the document's print/export layout. Spreadsheet PDF pagination follows its existing page settings. This release does not force all columns onto one page.
- Macro-enabled modern formats (DOCM/XLSM/PPTM) are not offered. Macro execution is disabled in the temporary Office profile; conversion is not a sandbox for arbitrary untrusted documents.
- PDF-to-editable Word/Excel/PowerPoint is not included. It requires reconstruction and often loses layout; OCR here extracts plain text only.
- CSV/TSV/JSON worksheet exports preserve **formula expressions**, not recalculated numeric results. They discard charts, formatting, merged-cell appearance and workbook behavior. Filenames use worksheet order; no sheet is silently dropped, including empty sheets.
- CSV/TSV to JSON uses arrays of arrays, preserving duplicate headers and ragged rows. JSON objects use the union of keys as headers. Nested JSON is rejected for table export. An absent object key and a null value both become an empty spreadsheet cell.
- Tabular text imported into XLSX stays literal: dates and numbers from CSV are not automatically typed, so leading zeros survive. JSON scalar types are retained where possible; integer values of 15 or more decimal digits are saved as strings to avoid Excel precision loss.
- CSV text containing formula expressions remains formula text in the CSV. Spreadsheet programs may interpret it when opened; inspect data from untrusted sources.
- Image edits/conversions use the first frame/page of animated or multipage images. HTML and Markdown become a PDF of source text, not a rendered webpage.
- Directory ZIP archives are packaging. Executables, proprietary project files, CAD/3D formats, disk images and arbitrary binary formats do not gain document/image conversion by changing their extension.
- Password-protected files must be unlocked before conversion. Originals are never overwritten. Batch exports can retain completed outputs if a later file/page fails.

## Local dependencies

- Setup installs PySide6 Essentials, pynput, Pillow, pypdf, PyMuPDF and openpyxl.
- LibreOffice is a separate free installation for Office rendering/conversion.
- FFmpeg is separate for audio/video.
- OCR additionally needs pytesseract, Tesseract and the selected language data.
- HEIC/HEIF additionally needs pillow-heif.

LibreOffice references used for the implementation:
- https://help.libreoffice.org/latest/en-US/text/shared/guide/start_parameters.html
- https://help.libreoffice.org/latest/en-US/text/shared/guide/convertfilters.html
