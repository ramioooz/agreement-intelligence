import os
from base64 import b64encode
from dataclasses import dataclass
from typing import Any, Protocol, cast

import boto3
from botocore.exceptions import ClientError


@dataclass(frozen=True)
class StoredDocument:
    content: bytes
    content_type: str


class DocumentStorage(Protocol):
    def put_immutable(
        self, key: str, content: bytes, *, content_type: str, sha256: str
    ) -> bool: ...

    def read(self, key: str) -> StoredDocument | None: ...

    def delete(self, key: str) -> None: ...


class ReadableBody(Protocol):
    def read(self) -> bytes: ...


class S3DocumentStorage:
    def __init__(
        self,
        *,
        client: Any,
        bucket: str,
        production: bool,
        kms_key_id: str | None,
    ) -> None:
        self._bucket = bucket
        self._client = client
        self._production = production
        self._kms_key_id = kms_key_id

    def put_immutable(self, key: str, content: bytes, *, content_type: str, sha256: str) -> bool:
        request: dict[str, object] = {
            "Bucket": self._bucket,
            "Key": key,
            "Body": content,
            "ContentType": content_type,
            "ChecksumSHA256": b64encode(bytes.fromhex(sha256)).decode("ascii"),
            "IfNoneMatch": "*",
        }
        if self._production:
            request["ServerSideEncryption"] = "aws:kms"
            if self._kms_key_id:
                request["SSEKMSKeyId"] = self._kms_key_id
        try:
            self._client.put_object(**request)
        except ClientError as error:
            if _error_code(error) in {
                "PreconditionFailed",
                "ConditionalRequestConflict",
                "409",
                "412",
            }:
                return False
            raise
        return True

    def read(self, key: str) -> StoredDocument | None:
        try:
            result = self._client.get_object(Bucket=self._bucket, Key=key)
        except ClientError as error:
            if _error_code(error) in {"NoSuchKey", "404", "NotFound"}:
                return None
            raise
        body = cast(ReadableBody, result["Body"])
        return StoredDocument(
            content=body.read(),
            content_type=cast(str, result.get("ContentType", "application/octet-stream")),
        )

    def delete(self, key: str) -> None:
        self._client.delete_object(Bucket=self._bucket, Key=key)


def storage_from_environment() -> S3DocumentStorage:
    bucket = os.environ.get("S3_DOCUMENT_BUCKET")
    region = os.environ.get("AWS_REGION")
    if not bucket or not region:
        raise RuntimeError("S3 document storage is not configured.")
    client = boto3.client(
        "s3",
        endpoint_url=os.environ.get("AWS_ENDPOINT_URL"),
        region_name=region,
    )
    return S3DocumentStorage(
        client=client,
        bucket=bucket,
        production=os.environ.get("APP_ENV", "development").lower() == "production",
        kms_key_id=os.environ.get("S3_DOCUMENT_KMS_KEY_ID"),
    )


def _error_code(error: ClientError) -> str:
    details = error.response.get("Error", {})
    return str(details.get("Code", ""))
