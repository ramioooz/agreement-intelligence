"""Structural safety checks shared by document-upload and parsing boundaries."""

from __future__ import annotations

from io import BytesIO
from pathlib import PurePosixPath
from typing import Final
from zipfile import BadZipFile, ZipFile, ZipInfo

MAX_DOCX_ENTRY_COUNT: Final = 128
MAX_DOCUMENT_COMPRESSED_BYTES: Final = 10 * 1024 * 1024
MAX_DOCX_ENTRY_UNCOMPRESSED_BYTES: Final = 10 * 1024 * 1024
MAX_DOCX_TOTAL_UNCOMPRESSED_BYTES: Final = 25 * 1024 * 1024
MAX_DOCX_COMPRESSION_RATIO: Final = 100

_REQUIRED_DOCX_PARTS: Final = frozenset({"[Content_Types].xml", "_rels/.rels", "word/document.xml"})


class DocxArchiveSafetyError(ValueError):
    """A DOCX archive violates a structural resource or path policy."""


def validate_docx_archive(content: bytes) -> None:
    """Reject unsafe DOCX ZIP metadata without expanding untrusted entries."""
    if not content.startswith(b"PK\x03\x04"):
        raise DocxArchiveSafetyError("invalid")
    try:
        with ZipFile(BytesIO(content)) as archive:
            entries = archive.infolist()
    except BadZipFile as error:
        raise DocxArchiveSafetyError("invalid") from error

    if len(entries) > MAX_DOCX_ENTRY_COUNT:
        raise DocxArchiveSafetyError("limits")

    total_uncompressed = 0
    names: set[str] = set()
    for entry in entries:
        _validate_docx_entry(entry, names)
        if entry.is_dir():
            continue
        total_uncompressed += entry.file_size
        if total_uncompressed > MAX_DOCX_TOTAL_UNCOMPRESSED_BYTES:
            raise DocxArchiveSafetyError("limits")

    if not _REQUIRED_DOCX_PARTS.issubset(names):
        raise DocxArchiveSafetyError("structure")


def _validate_docx_entry(entry: ZipInfo, names: set[str]) -> None:
    name = entry.filename
    path = PurePosixPath(name)
    if (
        not name
        or "\\" in name
        or "\x00" in name
        or path.is_absolute()
        or ".." in path.parts
        or name in names
    ):
        raise DocxArchiveSafetyError("structure")
    names.add(name)
    if entry.is_dir():
        return
    if entry.file_size > MAX_DOCX_ENTRY_UNCOMPRESSED_BYTES:
        raise DocxArchiveSafetyError("limits")
    if entry.file_size and (
        not entry.compress_size
        or entry.file_size > entry.compress_size * MAX_DOCX_COMPRESSION_RATIO
    ):
        raise DocxArchiveSafetyError("limits")
