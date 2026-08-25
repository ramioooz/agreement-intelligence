"""Run the existing durable duplicate-delivery checks as one recovery contract."""

from __future__ import annotations

import subprocess


def main() -> None:
    subprocess.run(
        [
            "uv",
            "run",
            "pytest",
            "-q",
            "apps/worker/tests/test_processing.py::test_duplicate_delivery_does_not_duplicate_completed_artifacts",
            "apps/worker/tests/test_workflow_checkpointing.py::test_workflow_event_is_checkpointed_once_even_when_delivery_is_repeated",
            "apps/api/tests/test_review_workflow.py::test_stage_activation_assigns_each_eligible_actor_once",
        ],
        check=True,
    )


if __name__ == "__main__":
    main()
