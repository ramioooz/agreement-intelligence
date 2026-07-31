from dataclasses import dataclass
from hashlib import sha256
from io import BytesIO
from pathlib import PurePath
from zipfile import BadZipFile, ZipFile


class DocumentValidationError(ValueError):
    """The submitted document does not meet the upload policy."""


@dataclass(frozen=True)
class ValidatedDocument:
    content: bytes
    content_type: str
    extension: str
    filename: str
    sha256: str


_DOCUMENT_TYPES = {
    ".pdf": "application/pdf",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
}


def validate_document(
    *, filename: str | None, content: bytes, declared_content_type: str | None, max_bytes: int
) -> ValidatedDocument:
    if not filename:
        raise DocumentValidationError("A file name is required.")
    if PurePath(filename).name != filename:
        raise DocumentValidationError("The file name must not contain a path.")
    if not content:
        raise DocumentValidationError("The uploaded file is empty.")
    if len(content) > max_bytes:
        raise DocumentValidationError("The uploaded file exceeds the maximum allowed size.")

    extension = PurePath(filename).suffix.lower()
    expected_type = _DOCUMENT_TYPES.get(extension)
    if expected_type is None:
        raise DocumentValidationError("Only PDF and DOCX files are accepted.")
    if not declared_content_type:
        raise DocumentValidationError("A declared MIME type is required.")
    if declared_content_type.lower() != expected_type:
        raise DocumentValidationError("The declared MIME type does not match the file extension.")

    if extension == ".pdf" and not content.startswith(b"%PDF-"):
        raise DocumentValidationError("The file content is not a valid PDF signature.")
    if extension == ".docx" and not _is_docx(content):
        raise DocumentValidationError("The file content is not a valid DOCX signature.")

    return ValidatedDocument(
        content=content,
        content_type=expected_type,
        extension=extension.removeprefix("."),
        filename=filename,
        sha256=sha256(content).hexdigest(),
    )


def _is_docx(content: bytes) -> bool:
    if not content.startswith(b"PK\x03\x04"):
        return False
    try:
        with ZipFile(BytesIO(content)) as archive:
            names = set(archive.namelist())
    except BadZipFile:
        return False
    return "[Content_Types].xml" in names and "word/document.xml" in names
