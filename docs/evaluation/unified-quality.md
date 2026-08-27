# Unified AI quality gate

[Documentation index](../README.md) · [Project README](../../README.md) · [Top](#unified-ai-quality-gate)

The unified gate gives the local release one deterministic quality decision across document
classification, clause extraction, grounded answers, retrieval, version comparison, and model
guardrails. Frozen project datasets and deterministic graders are the release authority.

## Deterministic release gate

Run the same command used by pull-request CI:

```bash
make ai-eval
```

The command validates the frozen dataset checksums and executes the application classifiers,
extractors, grounded-answer validator, version alignment, materiality assessment, and evidence
guardrails. Retrieval uses a deterministic lexical adapter over frozen source documents and
applies the tenant/workspace scope declared by each case. Grounding uses a deterministic
extractive candidate so the release gate remains offline; opt-in Promptfoo and Ragas runs cover
provider-assisted behavior. Expected labels are used only when observations are scored and are
never copied into runtime observations. It writes:

- `artifacts/evaluation/unified-report.json`
- `artifacts/evaluation/unified-report.md`
- `artifacts/evaluation/unified-runtime-results.json`

It fails when any of these release invariants is violated:

- unauthorized retrieval count is non-zero;
- citation precision is below `1.0`;
- an unsupported claim is accepted;
- critical material-change recall is below `1.0`; or
- retrieval recall@5 regresses by more than five percentage points.

Changing a frozen dataset requires an explicit, reviewed update to its checksum and accepted
baseline. Case fingerprints are derived from the newly executed normalized outputs rather than
from dataset checksums. The evaluator never writes the accepted baseline.

## Assisted provider report

Promptfoo and Ragas are development-only evaluators. They are not part of the API, worker, or web
runtime, and their reports cannot promote or replace the deterministic baseline.

Prepare a JSON file with this shape for Ragas:

```json
{
  "cases": [
    {
      "id": "termination-notice",
      "user_input": "What is the termination notice period?",
      "response": "Either party may terminate on thirty days written notice.",
      "retrieved_contexts": [
        "Either party may terminate on thirty days written notice."
      ],
      "reference": "Thirty days."
    }
  ]
}
```

Create an ignored, owner-readable file without putting a credential in shell history or a
process argument:

```bash
umask 077
touch .env.ai-eval.local
chmod 600 .env.ai-eval.local
```

Open `.env.ai-eval.local` in an editor, enter `OPENAI_API_KEY`, `OPENAI_MODEL`, and the
absolute `RAGAS_RESULTS` path, then source it only for the owner-triggered run:

```bash
set -a
. ./.env.ai-eval.local
set +a
make ai-eval-assisted
unset OPENAI_API_KEY OPENAI_MODEL RAGAS_RESULTS
rm -f .env.ai-eval.local
```

The command writes Promptfoo and Ragas reports under `artifacts/evaluation/`. Agreement text is
sent to the configured provider only when the operator explicitly runs this assisted command.

## Dependency boundary

Ragas `0.3.9` and its compatible `langchain-community` pin are development-only transitive tooling.
The application does not use LangChain for retrieval, orchestration, or model calls. Promptfoo is
also development-only. Both dependencies are exact and lockfile-controlled.

The assisted evaluator dependency set currently carries two advisories without published fixed
versions. This repository's assisted command does not invoke multimodal URL/file retrieval, and it
runs only as an owner-triggered local tool over an explicit JSON file; its cache is not shared with
untrusted users. CI therefore suppresses only `PYSEC-2026-3046` and `PYSEC-2026-2447` while
continuing to fail on every other audited dependency advisory. Remove either suppression when an
upstream fixed release becomes available.

## Interpreting reports

- **Gate failures** block the local release until the code or reviewed baseline is corrected.
- **Changed cases** identify normalized outputs whose fingerprints differ from the accepted result.
- **Latency, tokens, and cost** are reporting fields and are not flaky CI thresholds.
- **Assisted scores** support investigation; they never silently update accepted values.

[Back to top](#unified-ai-quality-gate)
