from dataclasses import dataclass
from hashlib import sha256
from pathlib import PurePath

from agreement_intelligence_platform.document_safety import (
    MAX_DOCUMENT_COMPRESSED_BYTES,
    DocxArchiveSafetyError,
    validate_docx_archive,
)


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
    if len(content) > min(max_bytes, MAX_DOCUMENT_COMPRESSED_BYTES):
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
    if extension == ".docx":
        try:
            validate_docx_archive(content)
        except DocxArchiveSafetyError as error:
            if str(error) == "limits":
                raise DocumentValidationError(
                    "The DOCX archive exceeds document safety limits."
                ) from error
            raise DocumentValidationError(
                "The DOCX archive has an invalid internal structure."
            ) from error

    return ValidatedDocument(
        content=content,
        content_type=expected_type,
        extension=extension.removeprefix("."),
        filename=filename,
        sha256=sha256(content).hexdigest(),
    )
