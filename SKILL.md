---
name: pulsonix
description: Work with Pulsonix designs and libraries, including offline library attribute-name renames, native inspection, guarded .sch edits, PLX conversion, part creation, and PCB STEP cleanup. Use for Pulsonix tasks, library property renames, component variants, PLX extraction, or simplifying PCB STEP exports. Never invoke Advanced scripting operations.
---

# Pulsonix

Choose the workflow from the requested change before connecting to an application. **Renaming existing part attribute names in a supported `.pal` is an offline operation:** use the narrow CString edit below. It does not require Pulsonix, scripting, a server, a Toolkit import, or desktop automation. For creating parts, prefer deterministic text generation plus standard `AddToLibrary`; never rely on Advanced Scripting Features.

Standard scripting and **Scripting Advanced Features** are different capabilities. The established PLX import workflow uses standard scripting. Respect a user prohibition on scripting or desktop automation. A request to edit the native schematic binary authorizes the offline schematic workflow below; do not request scripting-server activation or repeat permission already given. A scripting prohibition alone does not select a different write method.

## PCB STEP cleanup

For simplifying or deduplicating `.stp`/`.step` board exports, follow [step_cleanup](subskills/step_cleanup/SKILL.md). Its offline helpers fill circular holes below a diameter threshold, remove `R_*` and `CC_*` components with their placements, prune obsolete records, and share repeated solids through native STEP instancing. The standard preset is holes below 0.8 mm plus those two prefixes, followed by **mandatory geometry deduplication**; the default command performs the entire sequence. Respect explicit limits on hole/component removal. Preserve retained geometry, colors, products, and placements; verify actual geometry sharing and report file-size reduction. The instancing method was confirmed working by the user. This workflow does not connect to Pulsonix or require a scripting licence.

## Rename existing library attributes offline

For requests such as `Mfg1` -> `Manufacturer_Name` and `Mfg1 Code` -> `Manufacturer_Part_Number`, read [offline library attribute renaming](references/offline-library-attribute-renaming.md) and use [rename_library_attributes.py](scripts/rename_library_attributes.py). A request to perform the rename authorizes preparing, verifying, backing up, and publishing that narrow edit; finish publication without another confirmation when its checks pass. Preparation alone is not completion.

The helper edits only complete existing `CAttributeName.name` CStrings in logical compound-file streams. It preserves every object/class ID, reference, attribute value, metadata field, record order, body/pin/symbol/footprint stream, and index byte. It verifies that reversing the name edits restores each original stream exactly. Use this route first for a supported existing-name rename, including when no application is running. Do not launch Pulsonix or ask for its scripting dashboard for this route.

Keep same-valued destination records if the destination name already exists, rather than deleting or reallocating archive objects. Report resulting identical duplicates; reject conflicting destination values. This case was published and checked **offline only** on 2026-10-15: 79 parts, 158 renamed definitions, 357 other streams preserved, identical destination records retained in 33 parts. Application loading and duplicate handling by Pulsonix were not tested; do not describe this as application-verified.

## Offline native schematic edits

For native binary inspection, property edits, or compatible component replacement, read [native schematic editing](references/native-schematic-editing.md). The bundled helpers use Windows compound-storage file IO, with no Pulsonix connection, scripting, UI automation, or licence-dependent calls.

- [inspect_native_design.py](scripts/inspect_native_design.py): snapshot a CFB file, extract streams, inventory strings and class declarations; native libraries can be inspected read-only.
- [map_native_properties.py](scripts/map_native_properties.py): map existing embedded-part properties with an explicit, hash-bound Pulsonix 14 profile; generate guarded plans for values, part names, and library links.
- [edit_native_design.py](scripts/edit_native_design.py): prepare a new `.sch` copy, verify exact edits and every stream, then publish with a fresh source check and immediate backup.

Preserve archive object/class allocation order. Edit complete CStrings or proven existing object-reference WORDs; do not add/remove records. Offsets are relative to the logical `Contents` stream and change after string edits. Calibrate maps for each saved file; runtime-class tags are not universal constants. Component replacement also requires pin/geometry compatibility, body links, instance assignments, local overrides, and duplicate-name checks. A property edit alone does not establish component replacement.

The successful CM-PV50-E1 case is documented in the reference: 94 passive instances across 15 part types, including retargeting one instance to an already embedded definition. The user confirmed it worked in Pulsonix. That evidence applies to the tested layout and edit recipe, not arbitrary archive reconstruction or native-library rewriting.

## Native-library integrity

The narrow existing-name CString workflow above is the supported offline exception for `.pal` files. Do not rebuild archive records or add, remove, merge, or reorder library objects through a custom serializer. These operations can renumber references used by the part body; an earlier attribute-addition writer produced an unreadable library. Use a supported importer or documented standard attribute methods for those broader changes. Do not generalize the name-only exception to `.pfl`/`.ssl`, attribute creation/deletion, values, component replacement, or unsupported archive layouts.

For the offline name-only route, publish after its exact-edit, file, backup, and freshness checks pass, and report verification as offline. Do not require application loading to finish an explicitly offline rename. For importer/API writes, have Pulsonix load and check the modified records before publishing. Keep preparation, publication, offline validation, successful import, and application readback distinct; matching hashes or a custom parser never establish application compatibility.

For changes to existing part attributes, read [attribute updates](references/attribute-updates.md). Use a properties-only read when structure is unchanged; do not traverse all pins and gates merely to copy attribute values. The snapshot reader must handle parts without footprints.

## Library locks and failed automation

Before any library write, check the exact target `.pal` and existing `.palx` for write access without modifying them. A sharing violation, read-only file, or denied write access is a stopping condition. Report the actual reason and path; do not assume a lock is caused by Pulsonix. Include whether the original has changed. For an established Pulsonix lock, say: **"Pulsonix has locked the original library, so I cannot write to it right now."**

Treat a locked library separately from a missing or busy scripting server. Starting the scripting server does not resolve a file lock. Do not repeatedly request server restarts when the target file is unwritable. Preserve prepared CSV/PLX files and stop until there is evidence that the relevant blocking condition has changed. Repeated requests to finish the same task do not authorize API experimentation or disrupting the user's application.

Use the established standard scripting pipe workflow only. For ordinary library tasks, do **not** try legacy COM/ActiveX, `win32com.client.Dispatch`, `CoCreateInstance`, `InvokeTypes`, speculative methods, live type-information probes, guessed object IDs, or experimental handle cleanup. A failed standard call is not a reason to switch interfaces or investigate them against the live application.

Do not automate the desktop, open menus or dialogs, restart the scripting server, or launch a second Pulsonix instance to work around a failed library write. Never close or terminate the user's Pulsonix process. If the user reports popups, interference, or a crash, stop application calls immediately, including metadata probes. The independent offline name-only workflow remains available when its checks pass; an unavailable scripting pipe does not block an offline edit. Otherwise continue only with offline preparation or an explicitly authorized, established recovery procedure.

Adding parts to a companion or staging library does not complete a request to update the original library. Do not substitute another target unless the user requests it. When a previously imported and verified native copy is already available, publish that copy after the original becomes writable: verify that the original `.pal`/`.palx` still match the pre-import baseline, back up both files immediately before replacement, copy both files, and compare their hashes with the verified copy. Never update `.palx` alone or overwrite concurrent library changes. This requires no further API calls; full details are in [standard library automation](references/standard-library-automation.md).

## Hard license boundary

Do not call methods marked **Advanced**, even speculatively. A missing Advanced licence can destabilize or terminate Pulsonix.

Avoid these known Advanced methods:

- `Part.Export`
- `Part.AddFootprintFromLibrary`
- `Part.AddGate`
- `Part.AddGateFromLibrary`
- `PartLibrary.Delete`
- `PartLibrary.Import`
- `SymbolLibrary.Delete`
- `SymbolLibrary.Import`

Use these standard methods for this workflow:

- `GetVersion`
- `OpenPartLibrary(path, True)`
- `OpenPartLibrary(path, False)` only for the guarded existing-attribute workflow below
- `Library.Contains`
- `PartLibrary.Find`
- read-only `Part`, `Gate`, `PartPin`, and `Attribute` properties
- inherited `Part.AddAttribute` and `PartLibrary.Write(part_handle)` for existing attributes, after a pilot and readback on a copy; see [attribute updates](references/attribute-updates.md)
- `AddToLibrary(plx_path, 1, pal_path, False)`
- `Delete(library_handle)` to release the temporary API helper object; this does not delete library contents

Read [standard library automation](references/standard-library-automation.md) before changing a part library.

## Variant-part workflow

Use this sequence when a table contains related parts:

1. Read the source table and the target `.palx`. Detect name collisions and check native-library write access before connecting to the API. Apply the stopping conditions above if the target is unwritable.
2. Query the available component-search MCP server for every exact manufacturer part number. Use the server the user identifies as Components even if its configured name differs; in the current setup this may appear as PCBParts. Prefer an exact-MPN lookup such as `pcbparts_jlc_get_part`; use catalogue-wide part search or distributor cross-reference only when the exact lookup has no record.
3. Treat catalogue results as sourced attributes. Preserve the exact MPN and record the provider identifier, such as an LCSC number. Normalize units for Pulsonix while retaining the meaning returned by the server.
4. Choose the structure source:
   - When a suitable part exists, inspect it with [inspect_part.py](scripts/inspect_part.py). Generate variants with `--library` and `--reference`; the generator copies its pin mapping, symbol, footprint, and designator stem.
   - When no complete part exists but the required symbol and footprint do, verify their exact names and pin counts in `.sslx` and `.pflx` with [verify_library_items.py](scripts/verify_library_items.py). For a simple single-gate part whose schematic pins, component pins, and footprint pads have identical names, use [generate_variant_plx.py](scripts/generate_variant_plx.py) with `--symbol`, `--footprint`, `--name-stem`, and `--pins`. For example, a two-pin capacitor can use `--symbol "Capacitor" --footprint "C0603" --name-stem C --pins "1,2"` after those links are verified.
   - When the symbol or footprint is absent, create or import it before generating the part.
5. Review the generated component-only PLX files. Do not use explicit structure mode for multi-gate parts, alternative symbols, multiple footprints, ungated pins, pin swaps, or non-identity pin mappings.
6. Back up the `.pal` and `.palx` immediately before mutation. [import_component_plx.py](scripts/import_component_plx.py) creates the backup, rejects collisions, imports through standard `AddToLibrary`, and reads each part back.
7. Confirm the final `.palx` rows and read back the part name, description, attributes, pin count, symbol, and footprint. Report the resulting paths and any fields that could not be sourced.

## Component catalogue attributes

Query exact MPNs in parallel when the MCP server permits it. For resistors and similar passives, capture at least:

- manufacturer and manufacturer part number
- value
- package
- tolerance
- power rating
- maximum voltage
- temperature coefficient
- operating temperature
- technology or construction
- dielectric or temperature characteristic for capacitors
- current rating for inductors when available
- supplier catalogue number when available

Every created component must contain these attributes, in this spelling, as the bare minimum:

- `Part Number`
- `Manufacturer`
- `Value`
- `Tolerance`
- `Voltage Rating`
- `Current Rating`
- `Power Rating`
- `Package`

Keep the attribute present with an empty value when it does not apply or the component has no meaningful value. For example, an IC normally has an empty `Value` attribute. Do not omit any of these eight attributes.

Use reference designator prefix `U` for every integrated circuit, overriding a copied or vendor default prefix such as `IC`. Use prefix `J` for every connector. Pass `--name-stem U` or `--name-stem J` to the generator when reference mode would otherwise copy a different prefix.

Prefer the component-search MCP record over a general web search for these attributes. Record which exact MPN matched, and treat an ambiguous or normalized-family match as unresolved until it is confirmed.

Do not invent missing ratings from a related part. A reference part supplies structure and library links; the component-search result supplies the new part's identity and electrical attributes.

Create an enriched CSV for the PLX generator. Keep the user's identifying columns and add catalogue fields with Pulsonix attribute names, for example `Description`, `Power Rating`, `Tolerance`, `Voltage Rating`, `Temperature Coefficient`, `Operating Temperature`, and `Technology`.

## Application handling

Respect the user's active desktop. Use an already running scripting server when available. The bundled reader and importer use [pipe_client.py](scripts/modules/pipe_client.py) and need no generated client. Keep one pipe connection open across collision checks, import, and readback so Pulsonix is not repeatedly reconnected.

If `\\.\pipe\PulsonixScripting` is unavailable or busy, stop application calls and preserve the CSV and PLX files. Report the connection failure separately from any file lock. Request server activation once only when a writable target actually requires that connection and no already verified copy can complete the write. The user operates **Tools > Scripting Dashboard**; do not operate it for them.

If an explicitly requested API development task needs standard APIs outside the bundled tools, consult documentation and look for the optional generated client with [find_client.py](scripts/find_client.py). A known development copy on this computer has been found under `C:\Development\PulsonixMcp\.tmp\pulsonix_client\pulsonix`. Missing client code is not a reason to probe other interfaces or drive the active application. The user can create the Python client package through **Tools > Scripting Dashboard**; Pulsonix documents Python 3.10 or later with `pywin32` for that client.

If the pipe disappears during a read-only operation, reconnect once after the server is restored. If it disappears during `AddToLibrary`, first inspect the `.palx` and query the intended part names before retrying, because the write may already have completed.

Start Pulsonix with `-hidden` only for a fresh unattended session when no Pulsonix instance is running, or when the user explicitly requests an isolated background session. Never use another instance to recover a locked file or broken connection. Record the process ID created by the task and close only that exact process after releasing all API handles. Never terminate a visible or pre-existing Pulsonix process.

Do not pass `.pgf` files to `AddToLibrary`; the installed API may return an unspecified error. Toolkit PGF import belongs to the Library Manager UI. Use component PLX files for unattended API imports.

## Other workflows

- For extracting `.plx` files from ZIP archives, follow [plx-from-zip](subskills/plx-from-zip/SKILL.md).
- Preserve intermediate PLX files for review and repeatability.
- Do not infer a footprint or symbol association from a similar name. Copy verified links from the chosen reference or obtain an explicit mapping from the user.
- Report unresolved links and unsupported geometry rather than guessing.
