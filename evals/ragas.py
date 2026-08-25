from __future__ import annotations

import argparse
import json
import math
import os
from collections.abc import Mapping
from pathlib import Path
from typing import cast

from openai import OpenAI
from ragas import EvaluationDataset, SingleTurnSample, evaluate
from ragas.embeddings import OpenAIEmbeddings
from ragas.llms import llm_factory
from ragas.metrics import Faithfulness, ResponseRelevancy


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Produce an opt-in model-assisted RAG quality report."
    )
    parser.add_argument("--results", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        raise SystemExit("OPENAI_API_KEY is required for the assisted Ragas evaluation.")
    payload = _object(json.loads(args.results.read_text()), "results")
    cases = [_case(item) for item in _list(payload.get("cases"), "results cases")]
    dataset = EvaluationDataset(samples=[case[1] for case in cases])

    client = OpenAI(api_key=api_key)
    llm = llm_factory(os.environ.get("OPENAI_MODEL", "gpt-5.4-mini"), client=client)
    embeddings = OpenAIEmbeddings(
        client=client,
        model=os.environ.get("EMBEDDING_MODEL", "text-embedding-3-small"),
    )
    result = evaluate(
        dataset,
        metrics=[
            Faithfulness(llm=llm),
            ResponseRelevancy(llm=llm, embeddings=embeddings),
        ],
        llm=llm,
        embeddings=embeddings,
        raise_exceptions=True,
        show_progress=False,
    )
    scores = [dict(score) for score in result.scores]
    report = {
        "version": "ragas-assisted-v1",
        "model": os.environ.get("OPENAI_MODEL", "gpt-5.4-mini"),
        "embedding_model": os.environ.get("EMBEDDING_MODEL", "text-embedding-3-small"),
        "cases": [
            {"id": identifier, "scores": score}
            for (identifier, _), score in zip(cases, scores, strict=True)
        ],
        "averages": _averages(scores),
    }
    rendered = json.dumps(report, indent=2, sort_keys=True, allow_nan=False)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(rendered + "\n")
    print(rendered)


def _case(value: object) -> tuple[str, SingleTurnSample]:
    item = _object(value, "result case")
    identifier = _string(item.get("id"), "result case id")
    contexts = [
        _string(context, "retrieved context")
        for context in _list(item.get("retrieved_contexts"), "retrieved contexts")
    ]
    return identifier, SingleTurnSample(
        user_input=_string(item.get("user_input"), "user input"),
        response=_string(item.get("response"), "response"),
        retrieved_contexts=contexts,
        reference=_optional_string(item.get("reference"), "reference"),
    )


def _averages(scores: list[dict[str, object]]) -> dict[str, float]:
    values: dict[str, list[float]] = {}
    for score in scores:
        for metric, raw_value in score.items():
            if isinstance(raw_value, int | float) and not isinstance(raw_value, bool):
                observed = float(raw_value)
                if not math.isfinite(observed):
                    raise ValueError(f"Ragas returned a non-finite score for {metric}")
                values.setdefault(metric, []).append(observed)
    return {
        metric: round(sum(observed) / len(observed), 8)
        for metric, observed in sorted(values.items())
        if observed
    }


def _object(value: object, label: str) -> Mapping[str, object]:
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be an object")
    return cast(Mapping[str, object], value)


def _list(value: object, label: str) -> list[object]:
    if not isinstance(value, list):
        raise ValueError(f"{label} must be a list")
    return cast(list[object], value)


def _string(value: object, label: str) -> str:
    if not isinstance(value, str) or not value:
        raise ValueError(f"{label} must be a non-empty string")
    return value


def _optional_string(value: object, label: str) -> str | None:
    if value is None:
        return None
    return _string(value, label)


if __name__ == "__main__":
    main()
