from uuid import uuid4

from agreement_intelligence_worker.main import ProfileProcessor
from agreement_intelligence_worker.processing import CompletedArtifact, ProcessingJob


class _Processor:
    def __init__(self, key: str) -> None:
        self.key = key
        self.calls = 0

    def process(self, job: ProcessingJob) -> CompletedArtifact:
        self.calls += 1
        return CompletedArtifact(job_id=job.id, key=self.key)


def test_version_comparison_profile_routes_to_comparison_processor() -> None:
    document = _Processor("document")
    comparison = _Processor("comparison")
    job = ProcessingJob(
        id=uuid4(),
        agreement_id=uuid4(),
        state="processing",
        attempt_count=1,
        profile="version-comparison",
    )

    completed = ProfileProcessor(document, comparison).process(job)  # type: ignore[arg-type]

    assert completed.key == "comparison"
    assert document.calls == 0
    assert comparison.calls == 1


def test_embedding_reindex_profile_does_not_reprocess_the_source_document() -> None:
    document = _Processor("document")
    comparison = _Processor("comparison")
    configuration_id = uuid4()
    job = ProcessingJob(
        id=uuid4(),
        agreement_id=uuid4(),
        state="processing",
        attempt_count=1,
        profile=f"embedding-reindex:{configuration_id}",
    )

    completed = ProfileProcessor(document, comparison).process(job)  # type: ignore[arg-type]

    assert completed.key == f"embedding-reindex/{configuration_id}.json"
    assert document.calls == 0
    assert comparison.calls == 0
