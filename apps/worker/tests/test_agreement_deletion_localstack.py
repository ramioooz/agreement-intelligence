import os
from uuid import uuid4

import boto3
import pytest
from agreement_intelligence_worker.artifact_commit import (
    PreparedArtifact,
    write_or_read_canonical,
)
from agreement_intelligence_worker.document_processor import S3ObjectStorage
from agreement_intelligence_worker.processing import CompletedArtifact


def test_localstack_object_deletion_is_idempotent_for_real_key_shapes() -> None:
    endpoint_url = os.environ.get("AGREEMENT_INTELLIGENCE_TEST_LOCALSTACK_URL")
    if not endpoint_url:
        pytest.skip("LocalStack endpoint is required")
    client = boto3.client(
        "s3",
        endpoint_url=endpoint_url,
        region_name="us-east-1",
        aws_access_key_id="test",
        aws_secret_access_key="test",
    )
    bucket = f"agreement-deletion-{uuid4()}"
    client.create_bucket(Bucket=bucket)
    organization_id = uuid4()
    workspace_id = uuid4()
    agreement_id = uuid4()
    keys = (
        f"tenants/{organization_id}/workspaces/{workspace_id}/agreements/{agreement_id}/"
        f"analysis/{'a' * 64}/document-analysis.v1.json",
        f"comparisons/{uuid4()}/version-comparison.v1.json",
        f"reviews/{organization_id}/{workspace_id}/{uuid4()}/final-package/manifest.json",
    )
    try:
        for key in keys:
            client.put_object(Bucket=bucket, Key=key, Body=b"owned")
        storage = S3ObjectStorage(client=client, bucket=bucket)
        for key in keys:
            storage.delete(key)
            storage.delete(key)
        assert client.list_objects_v2(Bucket=bucket).get("KeyCount") == 0

        commit_key = f"comparisons/{uuid4()}/version-comparison.v1.json"
        artifact = CompletedArtifact(job_id=uuid4(), key=commit_key)
        first = PreparedArtifact(artifact, b"first", "application/json")
        second = PreparedArtifact(artifact, b"second", "application/json")
        assert write_or_read_canonical(storage, first) == b"first"
        assert write_or_read_canonical(storage, second) == b"first"
        assert storage.read(commit_key) == b"first"
    finally:
        for item in client.list_objects_v2(Bucket=bucket).get("Contents", []):
            client.delete_object(Bucket=bucket, Key=item["Key"])
        client.delete_bucket(Bucket=bucket)
