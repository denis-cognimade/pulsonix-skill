# Updating attributes on existing parts

## Choose the operation first

**Rename existing attribute names:** use [offline library attribute renaming](offline-library-attribute-renaming.md). This edits existing name CStrings with preserved archive allocation and does not need Pulsonix or a scripting server. Read the source, prepare and verify a copy, back up, then publish the original library when authorized checks pass. A prepared PGF is unnecessary for this operation and is not a completed rename.

**Add/delete attributes or change values:** use the standard API or Toolkit workflows below. Do not confuse the earlier failed attribute-addition serializer with the narrow offline existing-name edit. Do not use the offline rename helper to add/delete records or merge duplicate definitions.

Existing-attribute edits are different from creating new parts. Do not rebuild an existing part from a simple PLX template merely to change attributes: that can discard gates, representations, alternatives, pin mappings, swaps, or metadata.

## Properties-only reads

When standard scripting is authorized and the application is healthy, use `PartSnapshotReader.readAttributesFromOpenLibrary` to obtain the part name and attributes through documented read-only calls. It does not request the footprint, gates, or pins. Keep one connection and release the library helper after reading.

Normalize attribute-name casing for comparison. Prefer the exact requested source field, including when its value is empty. Use equivalent field names only when the requested field is absent and the user has authorized that mapping. Preserve missing values as blank; do not substitute a part name for a missing manufacturer code.

The existing `AddToLibrary(..., False)` importer deliberately rejects duplicate names. It is a creation workflow, not an existing-attribute updater. Do not change it to overwrite existing complex parts without preserving and validating their complete definitions.

## Standard API attribute update

When standard scripting is authorized, the documented `DesignItem.AddAttribute` (inherited by `Part`) can add or update an attribute. `PartLibrary.Write` writes that existing part back through Pulsonix's native serializer. These operations are not marked Advanced in the official API reference and passed a staged pilot with Pulsonix 14.0.11.0.

1. Copy the current `.pal`/`.palx` to an isolated task directory, retain baseline hashes and complete original part snapshots, and check write access. Keep the original untouched.
2. Read the source attributes from the copy with the properties-only reader.
3. Open the copy with `OpenPartLibrary(copy_path, False)`, retrieve the existing part with `Find`, call `AddAttribute(name, value)` for only the requested fields, then `Write(part_handle)` on the library helper. Do not replace its structure or call Advanced operations.
4. Release the helper and reopen the copy read-only. First test one ordinary part; verify its attributes and complete original pin mapping, gates, symbols, footprints, designator stem, and description. Stop on an application, licence, or readback error.
5. Only after the pilot passes, update the remaining parts. Reopen and verify all intended names, source values, new values, existing attributes, and complete original structures. Save the application verification report and native hashes.
6. Publish the verified pair using the baseline, backup, and hash checks in [standard library automation](standard-library-automation.md). A copy with only partial verification is not ready to publish.

Pulsonix may allocate new storage groups and renumber references when saving a part. Compare structural meaning through Pulsonix; do not require unchanged part-body bytes or unchanged group numbers. Index pin counts and links are supplementary checks. Never use this serializer behavior as permission to patch binary references yourself.

Sources: [DesignItem.AddAttribute](https://pulsonix.com/docs/14.0/Scripting/Reference/DesignItem#addattribute) and [PartLibrary.Write](https://pulsonix.com/docs/14.0/Scripting/Reference/PartLibrary#write).

## Library Toolkit import

Pulsonix documents an attribute-only edit through the Library Integration Toolkit. A `.pgf` file can locate existing parts and add fields without redefining their structure:

```text
FORMAT,PGF,4
FINDPART,"EXISTING-PART"
ADDATTR,"Mfg1","Existing manufacturer"
ADDATTR,"Mfg1 Code","Existing manufacturer code"
```

Use `FINDPART` for every named part followed by only the intended `ADDATTR` lines. Avoid part-creation, rename, delete, regroup, symbol, footprint, and pin commands for this task. Reject line breaks or unconfirmed quoting syntax in field values rather than emitting additional commands.

Import the file into the exact target `.pal` using **Setup > Libraries > Parts > Import**. Do not pass PGF to `AddToLibrary`; this installation previously rejected it. Do not guess command-line import switches. If the user prohibits Pulsonix scripting, prepare the PGF offline and use this documented UI import only within existing desktop authorization. The failure-handling restrictions in `SKILL.md` still apply.

Before import, compare the current target pair with the source baseline, check write access, and back up both files. After import, have Pulsonix load every affected part and check the requested values and preserved structure. Counts in `.palx` and offline parser results are supplementary evidence only. Keep the original target intact when preparation is complete but import or readback is unavailable.

Sources: [Library Toolkit help](https://pulsonix.com/docs/14.0/Libraries/idh_library_toolkit) and [Library Integration Toolkit manual](https://pulsonix.com/downloads/manuals/Pulsonix%20Library%20Toolkit.pdf), Part Files chapter (`FINDPART`, `ADDATTR`).
