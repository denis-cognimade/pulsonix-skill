# Rename existing library attribute names offline

Use this workflow for a supported Pulsonix `.pal` when the user asks to rename existing attributes, including across all parts. It needs Windows Python with `pywin32` from `scripts/requirements-native.txt`; `pythoncom.StgOpenStorage` is compound-file IO, not Pulsonix COM/ActiveX or application scripting.

## Execute the requested rename

Run the bundled helper with the exact library, old/new name pairs, a new task directory, and `--publish`:

```powershell
python C:\Development\skills\pulsonix\scripts\rename_library_attributes.py --library "C:\path\Parts.pal" --rename "Mfg1=Manufacturer_Name" --rename "Mfg1 Code=Manufacturer_Part_Number" --output "C:\path\attribute-rename-task" --publish
```

Omit `--publish` only if the user requested a preview or prepared copy. When the user asks to perform the edit, apply it after the helper's checks; do not stop after preparation or ask again for already granted permission. No application or scripting server is needed. Respect a real file lock; do not close the user's application to release it.

The helper accepts the observed part-attribute archive layout with a 29-byte prefix and initial shared class/object ID 47. It parses the complete attribute and name arrays, including metadata and opaque suffix. Unsupported classes, truncated strings, invalid references, unexpected source data, conflicting destination values, stale source hashes, and failed readback stop publication. Do not infer this profile applies to every Pulsonix version or native library type.

## What can change

- Replace only the complete CString occupying the `name` field of an existing `CAttributeName`, including its UTF-16 code-unit length.
- Apply edits by recorded logical-stream offsets, from last to first. Do not replace raw bytes globally or write at physical `.pal` offsets.
- Preserve class/object allocation IDs, reference targets, record order/count, flags, values/defaults, opaque data, and every other compound stream. Do not reserialize the archive graph.
- Verify the parsed graph with only the requested names changed. Reverse precisely those CString edits and require byte-for-byte recovery of the original stream.
- Read the staged CFB again and compare all logical streams with the plan; leave `.palx` unchanged when none of its column names changed.

Only this existing-name operation is covered. Adding/removing attributes, merging records, or changing references requires another established workflow.

## Collisions and repeat runs

If the destination attribute already exists with the same value, preserve both native records and report the identical duplicates. Removing either record can change archive allocation and is outside this method. A logical dictionary can hide duplicates, so validation must also inspect the ordered record graph. If values conflict, stop and explain the conflicting part and field instead of silently discarding a value.

A repeat run with no matching old names should report `already_renamed` and leave the source untouched. Missing fields remain missing; do not create empty attributes or invent manufacturer codes. Skip and report parts without matching fields.

## Publication and reporting

Before publication, check write access to `.pal` and `.palx`, verify both source hashes still match the baseline, and make an immediate verified backup of both. Install the verified `.pal`; retain the byte-identical `.palx`. Compare installed hashes and all logical streams with the verified copy. Preserve the report, staged copy, and backup. Never overwrite concurrent source changes or automatically restore a backup over later edits.

State whether the original was published, the number of parts and definitions changed, duplicate destination records, and the backup location. Describe these checks as **offline verification**, and do not claim Pulsonix loading was tested unless it actually was. Do not launch Pulsonix to strengthen that claim when the user requested the offline route.

## Observed case and regression

On 2026-10-15, the CM-PV50-E1 library had 79 parts. Renaming the two manufacturer fields changed 158 existing name definitions and preserved all 357 other compound streams and every index byte. The edit retained identical destination records in 33 parts. This was published with an immediate backup and verified offline; Pulsonix loading and its handling of the duplicate names were not tested or confirmed by the user.

The separate earlier failed offline operation **added** attribute/name objects through a serializer and shifted IDs used by the body. Do not reuse that failed writer, mistake it for this name-only operation, or turn that failure into a blanket requirement to start scripting for a rename.
