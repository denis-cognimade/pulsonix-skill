# Standard-license part-library automation

## Purpose

Use this workflow to add related parts to a native Pulsonix `.pal` library without Advanced Scripting Features. It was verified with Pulsonix 14.0.11.0.

## Native files

- `.pal` is the binary part library and source of truth.
- `.palx` is the derived tab-separated part index. It exposes part names, storage groups, pin counts, footprints, and symbols.
- `.pfl` / `.pflx` contain footprints and their index.
- `.ssl` / `.sslx` contain schematic symbols and their index.

Back up the `.pal` and `.palx` pair together immediately before an import. Pulsonix regenerates indexes when the native library changes.

## Write-access preflight

Check the requested `.pal` and its existing `.palx` before connecting to Pulsonix for an import. The check must not change file contents. On Windows, open each existing file with `CreateFileW`, `GENERIC_WRITE`, `FILE_SHARE_READ | FILE_SHARE_WRITE | FILE_SHARE_DELETE`, and `OPEN_EXISTING`, then immediately close the handle. Never use truncation, appending, or creation as a write-access test.

The bundled [import_component_plx.py](../scripts/import_component_plx.py) enforces this through [library_access.py](../scripts/modules/library_access.py) before acquiring a scripting client. The check performs no Pulsonix calls.

Windows sharing errors 32/33 mean that the file is locked; error 5 or a read-only file means that write access is denied. Stop and report the exact file and reason. Do not attempt `AddToLibrary`, a different interface, desktop automation, or another application instance to bypass the condition. A file lock and a busy scripting pipe are separate failures; report whichever the evidence establishes.

## Safe read pattern

The bundled utilities use the standard scripting named pipe directly. They send the same JSON requests as Pulsonix's generated Python client and do not require that package:

```python
library_id = client.call("OpenPartLibrary", part_library_path, True)
part_id = client.call("Find", part_name, object_id=library_id)
client.get(part_id, "Name")
client.call("Delete", library_id)
```

At the protocol level, an application call is `{"func":"GetVersion","id":0,"args":[]}`, an object call carries the returned integer object ID, and a property request is `{"get":"Name","id":123}`. A successful response contains `val`; an error contains `err` and `code`. Use [pipe_client.py](../scripts/modules/pipe_client.py) rather than creating another pipe implementation.

`Delete(library_id)` releases the API helper object. It is unrelated to the Advanced `PartLibrary.Delete(part_name)` operation.

Useful reference data includes:

- `part.Name`, `Description`, `NameStem`, and `PinCount`
- `part.DefaultFootprintName` and `Footprints`
- `part.Gates`; for each gate, `Name`, `DefaultSymbolName`, `Symbols`, and `Pins`
- for each gate pin, `Name`, `LogicName`, `PcbPinName`, `ScmPinName`, `SignalName`, and `SwapGroup`
- `{attribute.Name: attribute.Value for attribute in part.Attributes}`

## Component-only PLX

A related single-gate part can be created without redefining its existing symbol or footprint. The PLX contains one `compDef`, its pin map, and name references to the verified existing items:

```text
PULSONIX_LIBRARY_ASCII "Example.Part"
(asciiHeader (fileUnits MM))
(library Generated_Parts
  (compDef "Example.Part" (originalName "Example.Part")
    (compHeader (numPins 2) (numParts 1) (refDesPrefix R))
    (compPin "1" (pinName "") (partNum 1) (symPinNum 1) (gateEq 0) (pinEq 0) (pinType Unknown))
    (compPin "2" (pinName "") (partNum 1) (symPinNum 2) (gateEq 0) (pinEq 0) (pinType Unknown))
    (attachedSymbol (partNum 1) (altType Normal) (symbolName "Resistor"))
    (attachedPattern (patternNum 1) (patternName "R0603")
      (numPads 2)
      (padPinMap
        (padNum 1) (compPinRef "1")
        (padNum 2) (compPinRef "2")
      )
    )
    (attr "Description" "Example description")
    (attr "Value" "1k")
    (attr "Part Number" "EXACT-MPN")
    (attr "Manufacturer" "Example Manufacturer")
  )
)
```

The `Description` attribute becomes the Pulsonix part description. Other attributes become part attributes. Escape embedded backslashes and double quotes in PLX strings.

Use this component-only form only when the referenced symbol and footprint already exist. For multi-gate parts, alternative representations, multiple footprints, ungated pins, or pin swap groups, stop and inspect the full reference structure before generating PLX.

## No complete reference part

A complete part is not required for a simple component when its symbol and footprint already exist. Confirm the exact symbol name and pin count in `.sslx` and the exact footprint name and pad count in `.pflx`:

```powershell
python scripts/verify_library_items.py `
  --symbol-index "C:\path\Symbols.sslx" `
  --symbol "Capacitor" `
  --footprint-index "C:\path\Footprints.pflx" `
  --footprint "C0603" `
  --expected-pins 2
```

The index files do not expose individual pin names. Confirm the intended pin order from the library item or another trusted mapping before using explicit structure mode. That mode maps each listed component pin to the schematic pin ordinal and the footprint pad with the same name.

For example, if `Capacitor` and `C0603` exist and both use pins `1` and `2`:

```powershell
python scripts/generate_variant_plx.py `
  --symbol "Capacitor" `
  --footprint "C0603" `
  --name-stem C `
  --pins "1,2" `
  --parts-csv "C:\path\enriched-parts.csv" `
  --output "C:\path\generated-plx"
```

This mode is deliberately limited to one gate, one symbol, one footprint, and identity pin mapping. Create a purpose-built PLX when those conditions do not hold.

## Standard import pattern

Import each component PLX with:

```python
client.call("AddToLibrary", plx_path, 1, part_library_path, False)
```

Library type `1` is Component. Keep `overwrite=False`; detect collisions before the first write. Keep the same pipe connection alive through preflight, all imports, and readback. After import, reopen the library read-only and compare each created part with the expected PLX fields.

## Publishing an already verified copy

Use this only when the native copy has already passed full standard-API readback of its new parts, including their attributes and structural links. Keep the original `.pal` and `.palx` baseline from before that import.

1. Confirm that both original files are writable. If either is locked, report the lock and stop.
2. Compare both original files with the baseline, using hashes. If either changed, stop; the copy cannot safely replace concurrent changes.
3. Confirm that the copy preserves all original index entries and adds only the intended missing names. A staging or companion library is not the requested destination.
4. Back up the current original `.pal` and `.palx` immediately before replacement, then copy both verified native files to the original paths.
5. Compare the installed files' hashes with the verified copy and confirm the intended rows in the final `.palx`. Matching native-file hashes preserve the earlier full readback validation; no new API session is needed.

Keep the backup and prepared artifacts. If replacement is only partially successful, report the exact files changed and the backup path. Do not automatically overwrite later user changes. Never fabricate entries by editing only an index, and never claim that parts in a separate library have been added to the original.

## Bundled utility sequence

Inspect the chosen reference:

```powershell
python scripts/inspect_part.py `
  --library "C:\path\Parts.pal" `
  --part "REFERENCE-MPN" `
  --output "C:\path\reference.json"
```

Create an enriched CSV after exact-MPN component-search MCP queries. The generator recognizes the following columns case-insensitively:

- `Pulsonix part name`, `Manufacturer`, `Manufacturer part number`, `Package`
- optional structural override check: `Pulsonix footprint` or `Footprint`
- `Value`, `Value (ohm)`, `Resistance`, `Capacitance`, or `Inductance`
- `LCSC part number`
- `Description`, `Power Rating` or `Power(Watts)`, `Tolerance`
- `Voltage Rating` or `Voltage-Supply(Max)`
- `Temperature Coefficient`, `Operating Temperature`, `Technology` or `Type`
- `Dielectric` or `Temperature Characteristic`, and `Current Rating`
- any extra column named `Attribute:<Pulsonix attribute name>`

`Package` is stored as the catalogue package attribute. The verified reference or explicit `--footprint` selects the Pulsonix footprint link. When the CSV includes `Pulsonix footprint` or `Footprint`, the generator checks that it matches the selected link.

Every generated part includes the following minimum Pulsonix attributes: `Part Number`, `Manufacturer`, `Value`, `Tolerance`, `Voltage Rating`, `Current Rating`, `Power Rating`, and `Package`. The generator writes an empty string when a field is absent or does not apply, including `Value` for ICs without a meaningful value.

Use designator prefix `U` for integrated circuits and `J` for connectors. In reference mode, `--name-stem U` or `--name-stem J` overrides the prefix copied from the reference part.

Generate component-only PLX files from the live reference:

```powershell
python scripts/generate_variant_plx.py `
  --library "C:\path\Parts.pal" `
  --reference "REFERENCE-MPN" `
  --parts-csv "C:\path\enriched-parts.csv" `
  --output "C:\path\generated-plx"
```

Review the generated text, then back up, import, and verify:

```powershell
python scripts/import_component_plx.py `
  --library "C:\path\Parts.pal" `
  --plx-directory "C:\path\generated-plx"
```

The generator skips a CSV row whose exact MPN matches the reference. Pass `--include-reference` only when a separately named duplicate is intentional. It refuses multi-gate, multi-symbol, multi-footprint, swapped-pin, and ungated-pin references because those structures require a purpose-built mapping.

## Optional generated Python client

The bundled inspection, generation, and import sequence does not need Pulsonix's generated Python package. Use it only for standard API areas the bundled direct-pipe modules do not cover.

Search bounded locations with:

```powershell
python scripts/find_client.py
python scripts/find_client.py --root "C:\path\to\likely-parent"
```

The result is the directory containing both `pulsonix/__init__.py` and `pulsonix/psxutils.py`. A known development copy on this machine has been located at `C:\Development\PulsonixMcp\.tmp\pulsonix_client\pulsonix`.

If the client is missing, report it and let the user create the package through **Tools > Scripting Dashboard** when needed. Do not open that dialog or experiment with alternative interfaces. The generated package requires Python 3.10 or later with `pywin32`. Do not search the whole drive first.

## Failure handling

- If the native target is locked or unwritable, report that immediately and stop library writes and application calls. Do not treat a server restart as a file-lock remedy.
- If the scripting pipe is missing, busy, or times out, stop application calls and preserve the prepared inputs. Request user-operated server activation once only if the target is writable and no already verified copy can finish the task.
- If the pipe disappears during `AddToLibrary`, inspect `.palx` offline and report the confirmed and uncertain imports. Reconnect only after evidence that the server has been restored, then query every intended part name before another write because the request may have committed before the response was lost.
- If a standard import returns an unspecified error, stop that attempt and report the error and target. Do not probe COM/ActiveX, live type libraries, undocumented methods, or object handles. Do not start another Pulsonix instance or use GUI automation as recovery.
- If the user reports an unexpected dialog, application interference, or a crash, stop all application calls immediately, including read-only metadata probes. Offline preparation may continue within the requested task.
- If an API call reports `missing_licence`, stop using that operation. Do not retry it.
- If an import fails after earlier PLX files succeeded, report the partial list and backup path. Do not automatically overwrite the library with the backup because the user may have made concurrent changes.
- Do not call `Part.Export` to obtain a template. Inspect the reference read-only and generate component-only PLX instead.
