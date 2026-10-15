# Offline native schematic editing

Use this route when the user requests native `.sch` binary editing or offline format investigation. It requires no Pulsonix scripting server or application calls. Native libraries may be inspected to obtain source definitions; this schematic writer deliberately accepts only `.sch` files. For renaming existing `.pal` attribute names, use the separate [offline library attribute rename](offline-library-attribute-renaming.md) helper. Other native-library integrity rules still apply.

## Helpers and environment

Run from any workspace using absolute script paths. On Windows, use a Python environment with the pinned dependencies in `scripts/requirements-native.txt`:

```powershell
uv venv .venv-native
uv pip install --python .venv-native\Scripts\python.exe -r C:\Development\skills\pulsonix\scripts\requirements-native.txt
.venv-native\Scripts\python.exe C:\Development\skills\pulsonix\scripts\inspect_native_design.py --source "project.sch" --output "native-inspection"
```

`pythoncom.StgOpenStorage` is Windows compound-storage file IO, not the legacy Pulsonix COM/ActiveX interface. Reads use byte-identical temporary snapshots so an application's structured-storage lock need not prevent inspection. Never close the user's application or change its server state for these helpers.

JSON inputs accept UTF-8 with or without a BOM, including Windows PowerShell UTF-8 output. Generated JSON uses UTF-8 without a BOM.

The inspector creates a new investigation directory, a source snapshot, a hash manifest, logical stream binaries, and inventories. String/class matches are candidates, not proof of their semantic role. It can inspect `.pal` and nested part streams read-only; it does not modify their index companions. No whole-document serializer is supplied.

After extending a codec or edit path, run the bundled tests in that environment:

```powershell
python -m unittest discover -s C:\Development\skills\pulsonix\tests -v
```

The fixtures are synthetic; keep project files and full circuit snapshots outside the skill package. For a real regression, replay a retained typed plan on an isolated source backup and compare all logical streams with its known successful output.

## Established archive facts

The tested Pulsonix 14.0.11 schematic uses an OLE Compound File beginning `D0 CF 11 E0 A1 B1 1A E1`. Its streams include `Contents`, `\x05File_Type`, and `\x05SummaryInformation`. Preserve every stream except the exact intended `Contents` edits. Logical stream offsets are **not physical file offsets**; use structured-storage IO to write a copy.

The MFC archive encodes object records using WORD tags:

- `0`: null pointer.
- `FFFF`: new runtime-class declaration, followed by WORD schema, WORD ASCII class-name length, and class bytes.
- High bit set: reused runtime class followed by a new object record.
- Other nonzero WORD: reference to an existing archive object.

Classes and objects share allocation accounting. Adding a class, attribute-name definition, attribute, body, gate, or pin can shift later reference IDs throughout the document. An attribute-only reconstruction of a native library previously left its body references invalid despite a custom round trip. Preserve existing allocation order; never infer validity merely from your own parser accepting your output.

Unicode CString encoding:

```text
FF FE FF | encoded length | UTF-16LE payload without terminator
length < 255:                 one byte
255 <= length < 65535:        FF + little-endian WORD
length >= 65535:              FF FF FF + little-endian DWORD
```

Length counts UTF-16 code units (`len(value.encode("utf-16le")) // 2`), including surrogate pairs. Replace a whole CString including its length, rather than padding or raw substring replacement. The helpers reject truncated encodings and overlapping edits. Candidate positions shift by the sum of earlier edit length deltas. Binary regions without edits must remain byte-identical after accounting for those shifts.

## Calibrating existing properties

`map_native_properties.py` supports the **observed schema 7308 CPart prefix**, with an explicit file-specific profile. It rejects a different source hash, failed anchors, wrong part coverage, duplicate names/owner IDs, unknown attribute IDs, and unsupported layouts. Its output covers embedded part definitions, not component overrides or geometry.

Determine profile values from a current snapshot. Locate the `CAttributeNameArray` declaration and read its entries. In the tested layout, each reused `CAttributeName` is a class WORD, 12-byte header, name CString, 12-byte metadata, default CString, and 2-byte tail. Name IDs form a contiguous sequence in this layout. Infer the first ID from a uniquely known attribute (e.g. exact MPN): `attribute.name_id - index_of_name_in_global_array`. Check multiple independent value/manufacturer anchors, then compare all available known part snapshots. Do not assume an ID base from a previous project.

Each tested embedded `CPart` has a 29-byte prefix, `CAttributeArray` class WORD, owning-part WORD, attributes, null terminator, 10 opaque bytes, part-name CString, and library-path CString. Each `CAttribute` has a class WORD, 12-byte header, attribute-name reference WORD, value CString, and 2-byte tail. The first header WORD is the owning part; verify it. In the test saves the CPart tag was `0x800c`, CAttributeName `0x8029`, and schema `0x1c8c` (7308). These are observations, not defaults baked into the mapper.

Example profile structure (replace the hash and all calibration values with evidence from the current file):

```json
{
  "format_version": 1,
  "source_sha256": "<64 lowercase hexadecimal characters>",
  "archive_schema": 7308,
  "part_class_tag": 32780,
  "name_class_tag": 32809,
  "first_name_object_id": 77,
  "expected_part_count": 41,
  "anchors": [
    {"part": "Cap.0402.100n", "attribute": "Part Number", "expected": "CC0402KRX7R7BB104"},
    {"part": "Cap.0402.100n", "attribute": "Manufacturer", "expected": "YAGEO"},
    {"part": "Cap.0402.100n", "attribute": "Value", "expected": "100nF"}
  ],
  "evidence": "Describe calibration and the snapshot/readback used to establish coverage"
}
```

Generate a fresh map:

```powershell
python C:\Development\skills\pulsonix\scripts\map_native_properties.py --source "project.sch" --profile "profile.json" --output "properties.json"
```

To edit existing properties, supply a changes file:

```json
{
  "changes": [
    {"part": "Cap.0402.100n", "field": "attribute", "attribute": "Voltage Rating", "expected": "16V", "value": "25V"},
    {"part": "Cap.0402.100n", "field": "part_name", "expected": "Cap.0402.100n", "value": "My_Cap_0402"},
    {"part": "Cap.0402.100n", "field": "library_name", "expected": "C:\\old\\parts.pal", "value": "C:\\project\\parts.pal"}
  ]
}
```

```powershell
python C:\Development\skills\pulsonix\scripts\map_native_properties.py --source "project.sch" --profile "profile.json" --changes "changes.json" --output "edit-plan.json"
```

The helper rebuilds the map from the current source and adds guards for class, owner, attribute-name reference, and global name text. It cannot add an attribute or silently create a duplicate embedded part name. Updating a shared CPart affects every instance referencing it; check local instance overrides before reporting effective values. Part name, manufacturer part number, and reference designator are separate fields.

## Compatible component replacement

Plan from both the current schematic and verified source-library definitions. For two-pin passives, establish exact pin identities/mapping, single-gate structure, footprint/pad mapping, and compatible schematic geometry. Check manufacturer identity, value, tolerance, ratings, and package from the actual replacement; source structure is not evidence for another part's electrical ratings.

In the successful case, old and new bodies had the same 14-object sequence:

```text
CPartBody, CPartRepList, CPartRep, CGateArray, CGate,
CAttributeArray, CAttribute, CLibItemRefList, CLibItemRef(symbol),
CPartPinList, CPartPin(1), CPartPin(2),
CLibItemRefList, CLibItemRef(footprint)
```

Starting at body ID B, those objects used IDs B through B+13. Their parent/owner WORDs, class tags, pin maps, and all opaque headers were preserved. Existing description/footprint/stem strings were changed at proven field offsets. Original compatible schematic symbols were retained to preserve placement/geometry; this was not a byte-for-byte clone of the entire source library part. Do not assume every two-pin body has this sequence.

The tested CPart suffix resolves its body pointer by: after library CString, skip 8 bytes, read 3 CStrings, skip 32 bytes, read 2 CStrings, then a body-reference WORD. Confirm each step and the target owner's identity before use. A repeated byte signature is insufficient to establish an object ID.

For component instances, the observed prefix was CComponent class WORD and 2-byte header, null or populated attribute array, 8 opaque bytes for null / 10 for populated arrays, CPart reference WORD, **CPartRep** reference WORD, and reference-designator CString. The suffix includes a null WORD and a CSymbolInstanceArray (new or reused runtime class), owning-component ID, symbol-instance references, and null. Check every component ID against CComponentArray and all requested references against the current part assignments. CPartRep is not the CSymbol definition ID.

If the destination part is already embedded, do not rename the old definition to a duplicate name. Retarget the selected instance to the existing part and representation only with complete reference/geometry evidence. Symbol-instance, shape-source, attribute-source, or pad-source references may also need changing. In the successful R48 case, six previously application-replaced zero-ohm instances supplied exact reference conventions; normalized old/new symbol geometry matched. Six WORDs were changed, including two pad-source references set to zero as observed in those application-written examples. Merely changing the component's two part links would not establish correctness. Keep an unused old definition in place when removing it would shift allocation IDs.

To provide new attribute names without allocations, an **explicitly chosen** expendable existing metadata slot may be rebound to an already existing global attribute-name ID. Audit the removed metadata, reject duplicate property names, preserve required properties, and retain full source metadata separately. This case reused `(AccelReferenceName)` and an old supplier-number slot for `Mfg1` / `Mfg1 Code`; do not make that automatic. If a required name has no existing global definition/slot, this helper does not support adding it.

## Low-level plan and validation

For researched body strings or proven reference retargeting, generate a strict `NativeEditPlan` JSON using `modules/native_plan.py`. Fields:

- `format_version: 1`, `source_sha256`, `contents_sha256`: exact current snapshot hashes.
- `profile`, `evidence`: layout and calibration/geometry/ownership provenance.
- `edits`: each has `kind` (`cstring` or `word`), logical `offset`, full `expected_hex`, `replacement_hex`, `reason`, and nonempty `guards`.
- Each guard has `offset`, `expected_hex`, `reason`; guard typed record headers, owners, name references, and any observed replacement context.
- Optional `protected_ranges`: `start`, exclusive `end`, `reason`, and `allowed_word_offsets` (default none). This can protect the full net/wire/placement/instance tail with a small explicit whitelist of researched reference edits.

Use `NativeArchive.encodeCString`, `ByteEdit`, and `shiftedOffset` when generating plans or independent semantic validators. WORD editing accepts only two-byte ordinary object references/zero below `0x8000`; it cannot change runtime-class tags. Class declarations and all bytes outside planned fields must stay identical. These guards do not infer whether a newly chosen reference points to a compatible object: that evidence remains the planner's responsibility.

```powershell
python C:\Development\skills\pulsonix\scripts\edit_native_design.py prepare --source "project.sch" --plan "edit-plan.json" --candidate "project-candidate.sch" --audit "native-audit.json"
python C:\Development\skills\pulsonix\scripts\edit_native_design.py verify --source "project.sch" --candidate "project-candidate.sch" --audit "native-audit.json"
```

All output files must be new. The original stays untouched during preparation. Verification reconstructs every planned splice, checks shifted string readback and preserved class declarations, and compares every compound stream. Add task-specific semantic readback before publication: required attributes, unique names, counts, all instance assignments, body owners/links, geometry and pin maps, and protected net/placement bytes. A verified typed plan is not a universal object-graph proof.

## Publication and application validation

Within the user's authorized editing scope, publish the concrete verified candidate:

```powershell
python C:\Development\skills\pulsonix\scripts\edit_native_design.py publish --source "project.sch" --candidate "project-candidate.sch" --audit "native-audit.json" --backup "project-before-native.sch"
```

The helper reverifies the source/candidate/plan, checks write access, makes an exclusive byte-identical immediate backup, checks the original again, and publishes using a staged atomic replacement. A lock/sharing violation stops publication; it does not authorize application interference. Do not save concurrent application edits during publication. If the original changed, re-snapshot and remap; never bypass the hash guard.

`--in-place` is available for the proven Windows situation where the original is writable but its open file object must remain. It performs a fresh check, full write, truncate, flush/fsync, and readback while retaining that file object. Select this mode deliberately; interruption can leave a partial file. Preserve the immediate backup and report any failure without automatic retry or overwriting concurrent changes.

Tell the user to reopen the schematic from disk when an open application still holds cached content. Do not drive its UI when prohibited. Reports distinguish `candidate_offline_verified`, `published_offline_verified`, and application validation. The helper records `application_validation: not_performed`; record later user confirmation separately rather than claiming the agent performed application readback.

## Successful reference case and limits

On 2026-10-14, CM-PV50-E1 rev1.sch was updated directly with **194 typed edits**, 15 Cognimade passive types, 88 changed instances plus 6 already changed (94 total). All 141 components were read back offline. The global attribute definitions, body allocation counts/owners, six existing native replacement instances, all unrelated streams, and net/placement tail were preserved, except six explicitly validated R48 reference WORDs. The logical `Contents` length changed from 623687 to 620675 bytes. The original was backed up immediately and published without scripting or UI calls. The user subsequently reported: **“That worked flawlessly.”**

Evidence fingerprints for identifying this case, not reusable defaults:

- Before: `fb555c19c802dfb7950dce1963790ac263537a23152c2cb517964e783e85f76e`.
- Successful published file: `36c0a6b181754f108e0c301ba073470b9f21d56ebfd3ccbd6f3def745fcd3482`.
- Attribute array/attribute class tags changed across two application saves (`0x822b`/`0x822d` versus `0x8230`/`0x8232`); symbol-array tags changed too. Static offsets/tags must not be transplanted to another save.

Do not extrapolate to new allocations, general multi-gate replacement, arbitrary geometry edits, compressed/encrypted files, unsupported schemas, PCB files, or rewriting standalone native libraries. Unsupported mapping is a reason to extend and validate the offline profile against concrete evidence, or report that specific unsupported operation; it is not a reason to override the user's prohibition on scripting.
