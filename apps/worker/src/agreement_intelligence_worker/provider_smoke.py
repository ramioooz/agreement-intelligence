from __future__ import annotations

import json
import os
import sys

from agreement_intelligence_worker.analysis_provider import provider_from_environment
from agreement_intelligence_worker.analysis_validation import validate_provider_analysis

_SMOKE_BLOCKS = [
    (
        "smoke-termination",
        "Either party may terminate this Client Agreement on 30 days' written notice.",
    )
]


def main() -> None:
    if not os.environ.get("OPENAI_API_KEY"):
        print("OPENAI_API_KEY is required for provider smoke checks", file=sys.stderr)
        raise SystemExit(1)

    provider = provider_from_environment()
    if provider is None:
        print("Provider smoke configuration is unavailable", file=sys.stderr)
        raise SystemExit(1)

    try:
        analysis = provider.analyze(_SMOKE_BLOCKS)
        validate_provider_analysis(analysis, {anchor_id for anchor_id, _ in _SMOKE_BLOCKS})
    except Exception as error:
        print(f"Provider smoke check failed: {type(error).__name__}", file=sys.stderr)
        raise SystemExit(1) from error

    print(
        json.dumps(
            {
                "model": analysis.model,
                "latency_ms": analysis.latency_ms,
                "input_tokens": analysis.input_tokens,
                "output_tokens": analysis.output_tokens,
                "validation_status": "passed",
            },
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
