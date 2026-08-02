# Portable Model Gateway Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Route worker model calls through a typed, auditable gateway that supports the hosted default and compatible local endpoints.

**Architecture:** A gateway owns provider selection, request execution, fallback, and provenance. The existing document-analysis provider remains a narrow adapter that supplies its domain prompt and schema, while future embedding and grounded-answer callers consume typed gateway contracts.

**Tech Stack:** Python 3.13, OpenAI Python SDK, pytest, Docker Compose.

## Global Constraints

- Active runtime modes are `openai` and `openai-compatible`; OpenAI is the default.
- A local server profile accepts only a user-supplied GGUF mount and must not download or commit weights.
- Record provider, endpoint kind, model, configuration version, latency, usage/cost, retry/fallback outcome, and safe failure reason.
- Keep Anthropic and Gemini as documented contracts only.

---

### Task 1: Gateway contracts and provider selection

**Files:**
- Create: `apps/worker/src/agreement_intelligence_worker/model_gateway.py`
- Test: `apps/worker/tests/test_model_gateway.py`

- [ ] Add typed configuration, request/result metadata, future embedding and grounded-answer contracts, and environment selection.
- [ ] Verify an absent credential disables the hosted default and a compatible endpoint requires its URL.

### Task 2: Gateway execution and provenance

**Files:**
- Modify: `apps/worker/src/agreement_intelligence_worker/model_gateway.py`
- Test: `apps/worker/tests/test_model_gateway.py`

- [ ] Add structured generation for hosted and compatible endpoints with safe error mapping.
- [ ] Verify a compatible endpoint connection failure uses an explicitly configured hosted fallback and records it.

### Task 3: Worker integration

**Files:**
- Modify: `apps/worker/src/agreement_intelligence_worker/analysis_provider.py`
- Modify: `apps/worker/src/agreement_intelligence_worker/document_processor.py`
- Test: `apps/worker/tests/test_analysis_provider.py`
- Test: `apps/worker/tests/test_document_processor.py`

- [ ] Route analysis and playbook comparison calls through the gateway.
- [ ] Persist gateway provenance and retain the deterministic fallback behavior.

### Task 4: Local profile and operator documentation

**Files:**
- Modify: `compose.yaml`
- Modify: `.env.example`
- Modify: `README.md`
- Test: `tests/stack/test-compose-contract.sh`

- [ ] Add a profile-gated local OpenAI-compatible server with a read-only user GGUF mount.
- [ ] Document setup, endpoint configuration, and the future-only provider contracts.
