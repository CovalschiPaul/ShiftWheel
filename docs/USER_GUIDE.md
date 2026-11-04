# Using ShiftWheel

## First launch

Install the preview or follow the source setup in the [README](../README.md). Launch ShiftWheel and look for the orange icon in the Windows notification area; Windows may place it in the hidden-icons menu.

Start with a disposable copy of a small image. Hold Shift and drag it in Explorer, then drop it on a conversion wedge. The app creates a new output file. Existing filenames are protected by generating unique output names.

## Finding an action

The wheel adapts to the input family. Each page has at most eight wedges, including **More** when another page exists. While dragging, hover over More for roughly half a second. Move away before hovering again to advance another page. The center shows the page number.

Press Esc to dismiss. The tray menu also offers **Show wheel** and **Convert files… (no dragging)**. The default wheel shortcut is Ctrl+Alt+W and can be changed in the tray menu.

## Where results go

By default results are saved beside the source. Enable **Save into a 'Converted' folder** to keep them together. Rename creates copies rather than changing the original files.

Only one job runs at a time. A working notification indicates activity; completion or an error follows. Large conversions can take time. A batch may leave completed outputs when a later item fails—inspect the result report before retrying.

## Configure the tray menu

- **Trigger key:** choose the key used with dragging.
- **Start with Windows:** enable or disable startup.
- **Locate LibreOffice…:** point the app to an Office conversion engine.
- **OCR language…:** select language data installed in Tesseract.
- **Open log file / Show debugger:** inspect failures.

## Troubleshooting

| Symptom | What to check |
|---|---|
| Wheel does not appear | Confirm the tray app is running and the configured trigger is held. Try the tray file picker to separate conversion from Explorer interaction. |
| Office conversion fails | Install LibreOffice, use Locate LibreOffice, and check fonts and whether the original opens correctly. |
| Video/audio conversion fails | Confirm FFmpeg is installed and available on PATH; restart ShiftWheel after changing PATH. Codec support depends on the FFmpeg build. |
| OCR fails or produces poor text | Install Tesseract and the selected language data. Check scan resolution and orientation. OCR is text extraction, not layout reconstruction. |
| A format or action is missing | Check the [format matrix](../SUPPORTED_FORMATS.md). Changing an extension does not convert a file. |
| Output looks different | Office fonts and rendering, PDF export settings and image first-frame behavior affect fidelity. See the documented limitations. |
| Some batch outputs exist after an error | Completed files are retained. Read the error report and retry only the missing items. |

For a reproducible bug, include Windows version, ShiftWheel version, conversion pair, engine versions, steps and the relevant error. Remove private filenames and document content from logs. Prefer a small synthetic sample that reproduces the problem.

## Preview limitations

The installer is unsigned. Automated Windows builds and packaged smoke checks have passed; actual Explorer interaction, high-DPI/multiple monitors, startup, upgrade and uninstall still require acceptance testing. See [VALIDATION.md](../VALIDATION.md).

There is no job queue, cancellation control or persistent conversion history yet.
