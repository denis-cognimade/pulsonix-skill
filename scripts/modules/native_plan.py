"""Strict external plans for existing fields only."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

HASH_PATTERN = r"^[0-9a-f]{64}$"
HEX_PATTERN = r"^(?:[0-9a-fA-F]{2})+$"


class StrictModel(BaseModel):
	model_config = ConfigDict(extra="forbid", strict=True)


class ByteGuard(StrictModel):
	offset: int = Field(ge=0)
	expected_hex: str = Field(pattern=HEX_PATTERN)
	reason: str = Field(min_length=1)


class FieldEdit(StrictModel):
	kind: Literal["cstring", "word"]
	offset: int = Field(ge=0)
	expected_hex: str = Field(pattern=HEX_PATTERN)
	replacement_hex: str = Field(pattern=HEX_PATTERN)
	reason: str = Field(min_length=1)
	guards: list[ByteGuard] = Field(min_length=1)


class ProtectedRange(StrictModel):
	start: int = Field(ge=0)
	end: int = Field(gt=0)
	allowed_word_offsets: list[int] = Field(default_factory=list)
	reason: str = Field(min_length=1)


class NativeEditPlan(StrictModel):
	format_version: Literal[1]
	source_sha256: str = Field(pattern=HASH_PATTERN)
	contents_sha256: str = Field(pattern=HASH_PATTERN)
	profile: str = Field(min_length=1)
	evidence: str = Field(min_length=1)
	edits: list[FieldEdit] = Field(min_length=1)
	protected_ranges: list[ProtectedRange] = Field(default_factory=list)


class NativeAudit(StrictModel):
	format_version: Literal[1]
	status: Literal["candidate_offline_verified", "published_offline_verified"]
	source: str
	candidate: str
	candidate_sha256: str = Field(pattern=HASH_PATTERN)
	contents_after_sha256: str = Field(pattern=HASH_PATTERN)
	plan: NativeEditPlan
	backup: str | None = None
	published_sha256: str | None = None
	application_validation: Literal["not_performed"] = "not_performed"


class CalibrationAnchor(StrictModel):
	part: str
	attribute: str
	expected: str


class ArchiveProfile(StrictModel):
	format_version: Literal[1]
	source_sha256: str = Field(pattern=HASH_PATTERN)
	archive_schema: Literal[7308]
	part_class_tag: int = Field(ge=32768, le=65534)
	name_class_tag: int = Field(ge=32768, le=65534)
	first_name_object_id: int = Field(gt=0, lt=32768)
	expected_part_count: int = Field(gt=0)
	anchors: list[CalibrationAnchor] = Field(min_length=2)
	evidence: str = Field(min_length=1)


class PropertyChange(StrictModel):
	part: str = Field(min_length=1)
	field: Literal["attribute", "part_name", "library_name"] = "attribute"
	attribute: str | None = None
	expected: str
	value: str


class PropertyChanges(StrictModel):
	changes: list[PropertyChange] = Field(min_length=1)
