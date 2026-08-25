"""Run the existing safe provider-unavailability and lexical-fallback contracts."""

from __future__ import annotations

import subprocess


def main() -> None:
    subprocess.run(
        [
            "uv",
            "run",
            "pytest",
            "-q",
            "apps/worker/tests/test_document_processor.py::test_processor_propagates_provider_timeout_for_job_retry",
            "apps/worker/tests/test_model_gateway.py::test_unavailable_compatible_endpoint_has_a_safe_failure_reason_without_fallback",
            "apps/worker/tests/test_processing.py::test_transient_failure_is_requeued_with_bounded_backoff_without_sleeping",
            "apps/worker/tests/test_processing.py::test_transient_failure_stops_after_the_configured_attempt_bound",
            "apps/api/tests/test_hybrid_search.py::test_rrf_is_lexical_only_when_semantic_provider_is_unavailable",
            "apps/worker/tests/test_evidence_validation.py::test_returns_a_safe_model_unavailable_state",
        ],
        check=True,
    )


if __name__ == "__main__":
    main()
