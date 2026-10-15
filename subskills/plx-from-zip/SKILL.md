---
name: plx-from-zip
description: Extract Pulsonix `.plx` files from ZIP archives. Use whenever the user asks to extract, collect, or find `.plx` files in ZIP archives under a folder, including recursive searches.
---

# Extract PLX files from ZIP archives

Use the bundled script to recursively find `.zip` archives under the current directory and extract only their `.plx` entries directly into the current directory.

Run from the folder to scan with:
python "C:\Development\skills\pulsonix\subskills\plx-from-zip\scripts\extract_plx.py"

The script uses only Python's standard library. It preserves the ZIP files, does not create extraction folders, and skips output names that already exist so it does not overwrite files. If multiple archives contain a `.plx` file with the same name, the first archive in sorted path order wins and later duplicates are reported as skipped.

