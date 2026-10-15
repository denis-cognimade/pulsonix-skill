"""Prepare, reverify and publish exact typed edits without application calls."""

import json
import os
from pathlib import Path
import shutil
import tempfile

from .native_archive import ByteEdit, NativeArchive
from .native_plan import NativeAudit, NativeEditPlan
from .native_storage import NativeStorage


class NativeEditor:
	@staticmethod
	def writeJson(path: Path, data: dict, exclusive: bool = True) -> None:
		with path.open("x" if exclusive else "w", encoding="utf-8", newline="\n") as output:
			output.write(json.dumps(data, indent=2, ensure_ascii=False) + "\n")

	@staticmethod
	def validatePaths(source: Path, candidate: Path, audit: Path) -> None:
		if source.suffix.lower() != ".sch" or candidate.suffix.lower() != ".sch":
			raise ValueError("Writer is limited to .sch schematics; native libraries are read-only")
		if len({source.resolve(), candidate.resolve(), audit.resolve()}) != 3:
			raise ValueError("Source, candidate and audit must have distinct paths")

	@staticmethod
	def decodePlan(data: bytes, plan: NativeEditPlan) -> list[ByteEdit]:
		if NativeStorage.hashBytes(data) != plan.contents_sha256:
			raise ValueError("Contents hash differs from plan; map offsets again")
		edits = []
		for field in plan.edits:
			for guard in field.guards:
				expected = bytes.fromhex(guard.expected_hex)
				if data[guard.offset:guard.offset + len(expected)] != expected:
					raise ValueError(f"Record/context guard failed at {guard.offset}: {guard.reason}")
			edits.append(ByteEdit(field.offset, bytes.fromhex(field.expected_hex),
				bytes.fromhex(field.replacement_hex), field.kind, field.reason))
		ordered = NativeArchive.orderedEdits(data, edits)
		for region in plan.protected_ranges:
			if not 0 <= region.start < region.end <= len(data):
				raise ValueError("Protected range outside Contents")
			if any(not region.start <= offset <= region.end - 2 for offset in region.allowed_word_offsets):
				raise ValueError("Allowed WORD is outside its protected range")
			for edit in ordered:
				if edit.offset < region.end and edit.end > region.start:
					if edit.kind != "word" or edit.offset not in region.allowed_word_offsets:
						raise ValueError(f"Edit crosses protected range: {region.reason}")
		return ordered

	@staticmethod
	def verifyStreams(source_bytes: bytes, candidate_bytes: bytes, plan: NativeEditPlan) -> bytes:
		if NativeStorage.hashBytes(source_bytes) != plan.source_sha256:
			raise ValueError("Source changed since plan was mapped")
		source_streams = NativeStorage.readBytes(source_bytes)
		candidate_streams = NativeStorage.readBytes(candidate_bytes)
		if ("Contents",) not in source_streams:
			raise ValueError("Schematic has no Contents stream")
		original = source_streams[("Contents",)]
		edits = NativeEditor.decodePlan(original, plan)
		updated = NativeArchive.splice(original, edits)
		NativeArchive.verify(original, updated, edits)
		if candidate_streams != {**source_streams, ("Contents",): updated}:
			raise ValueError("Candidate stream readback differs from exact plan or unrelated streams")
		return updated

	@staticmethod
	def prepare(source: Path, candidate: Path, audit_path: Path, plan: NativeEditPlan) -> NativeAudit:
		NativeEditor.validatePaths(source, candidate, audit_path)
		if candidate.exists() or audit_path.exists():
			raise FileExistsError("Candidate and audit must be new files")
		source_bytes = source.read_bytes()
		if NativeStorage.hashBytes(source_bytes) != plan.source_sha256:
			raise ValueError("Source hash differs from plan; refusing stale offsets")
		streams = NativeStorage.readBytes(source_bytes)
		original = streams[("Contents",)]
		edits = NativeEditor.decodePlan(original, plan)
		updated = NativeArchive.splice(original, edits)
		NativeArchive.verify(original, updated, edits)
		# All plan checks finish before creating the output copy.
		with candidate.open("xb") as output:
			output.write(source_bytes)
		NativeStorage.writeContents(candidate, updated)
		candidate_bytes = candidate.read_bytes()
		NativeEditor.verifyStreams(source_bytes, candidate_bytes, plan)
		if source.read_bytes() != source_bytes:
			raise ValueError("Source changed during preparation; candidate has not been published")
		audit = NativeAudit(format_version=1, status="candidate_offline_verified",
			source=str(source.resolve()), candidate=str(candidate.resolve()),
			candidate_sha256=NativeStorage.hashBytes(candidate_bytes),
			contents_after_sha256=NativeStorage.hashBytes(updated), plan=plan)
		NativeEditor.writeJson(audit_path, audit.model_dump(mode="json"))
		return audit

	@staticmethod
	def verify(source: Path, candidate: Path, audit: NativeAudit) -> bytes:
		candidate_bytes = candidate.read_bytes()
		if NativeStorage.hashBytes(candidate_bytes) != audit.candidate_sha256:
			raise ValueError("Candidate file differs from audit")
		updated = NativeEditor.verifyStreams(source.read_bytes(), candidate_bytes, audit.plan)
		if NativeStorage.hashBytes(updated) != audit.contents_after_sha256:
			raise ValueError("Candidate Contents hash differs from audit")
		return candidate_bytes

	@staticmethod
	def publish(source: Path, candidate: Path, audit_path: Path, backup: Path, in_place: bool = False) -> NativeAudit:
		NativeEditor.validatePaths(source, candidate, audit_path)
		audit = NativeAudit.model_validate_json(audit_path.read_text(encoding="utf-8-sig"))
		if audit.status != "candidate_offline_verified":
			raise ValueError("Audit is not an unpublished, verified candidate")
		if source.resolve() != Path(audit.source) or candidate.resolve() != Path(audit.candidate):
			raise ValueError("Publication paths differ from preparation audit")
		if backup.exists() or backup.resolve() in {source.resolve(), candidate.resolve(), audit_path.resolve()}:
			raise FileExistsError("Backup must be a new, distinct file")
		candidate_bytes = NativeEditor.verify(source, candidate, audit)
		source_bytes = source.read_bytes()
		if NativeStorage.hashBytes(source_bytes) != audit.plan.source_sha256:
			raise ValueError("Original changed immediately before publication")
		# Opening with write access is a preflight, not a mutation.
		with source.open("r+b") as target:
			if target.read() != source_bytes:
				raise ValueError("Original changed during write-access check")
		with backup.open("xb") as output:
			output.write(source_bytes)
			output.flush()
			os.fsync(output.fileno())
		if backup.read_bytes() != source_bytes:
			raise IOError("Backup does not match source")
		if in_place:
			# Explicit mode for a writable, open Windows file whose file object must survive.
			# A failed write can leave a partial file; never hide that by automatic retry.
			with source.open("r+b") as target:
				if target.read() != source_bytes:
					raise ValueError("Original changed at publication")
				target.seek(0)
				if target.write(candidate_bytes) != len(candidate_bytes):
					raise IOError(f"Partial publication; recover from {backup}")
				target.truncate()
				target.flush()
				os.fsync(target.fileno())
		else:
			with tempfile.TemporaryDirectory(prefix="pulsonix_native_publish_", dir=source.parent) as directory:
				staged = Path(directory) / source.name
				with staged.open("xb") as output:
					output.write(candidate_bytes)
					output.flush()
					os.fsync(output.fileno())
				shutil.copymode(source, staged)
				if staged.read_bytes() != candidate_bytes:
					raise IOError("Staged publication copy differs from verified candidate")
				if source.read_bytes() != source_bytes:
					raise ValueError("Original changed before atomic publication")
				os.replace(staged, source)
		if source.read_bytes() != candidate_bytes:
			raise IOError(f"Publication verification failed; backup retained at {backup}")
		if NativeStorage.readFile(source) != NativeStorage.readBytes(candidate_bytes):
			raise IOError(f"Published stream verification failed; backup retained at {backup}")
		audit.status = "published_offline_verified"
		audit.backup = str(backup.resolve())
		audit.published_sha256 = NativeStorage.hashBytes(candidate_bytes)
		# Replace the audit atomically after the file and stream checks pass.
		with tempfile.TemporaryDirectory(prefix="pulsonix_native_audit_", dir=audit_path.parent) as directory:
			report_copy = Path(directory) / "audit.json"
			NativeEditor.writeJson(report_copy, audit.model_dump(mode="json"))
			os.replace(report_copy, audit_path)
		return audit
