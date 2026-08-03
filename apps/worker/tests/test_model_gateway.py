from __future__ import annotations

import json
from typing import Any

from _pytest.monkeypatch import MonkeyPatch
from agreement_intelligence_worker.model_gateway import (
    EmbeddingConfiguration,
    EmbeddingRequest,
    GatewayConfigurationError,
    GatewayUnavailableError,
    ModelGatewayConfiguration,
    OpenAIModelGateway,
    embedding_configuration_from_environment,
    model_gateway_from_environment,
)
from pytest import raises


class _Response:
    def __init__(self, output_text: str) -> None:
        self.output_text = output_text
        self.usage = type(
            "Usage", (), {"input_tokens": 11, "output_tokens": 7, "total_tokens": 18}
        )()


class _HostedClient:
    def __init__(self, response: _Response) -> None:
        self.responses = self
        self.response = response

    def create(self, **kwargs: Any) -> _Response:
        return self.response


def test_environment_selects_openai_by_default(monkeypatch: MonkeyPatch) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.delenv("MODEL_GATEWAY_MODE", raising=False)

    gateway = model_gateway_from_environment(client_factory=lambda **_: object())

    assert gateway is not None
    assert gateway.configuration.mode == "openai"
    assert gateway.configuration.endpoint_kind == "hosted"


def test_embedding_configuration_is_independent_from_generation_configuration(
    monkeypatch: MonkeyPatch,
) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setenv("OPENAI_MODEL", "generation-model")
    monkeypatch.setenv("EMBEDDING_MODEL", "embedding-model")
    monkeypatch.setenv("EMBEDDING_DIMENSIONS", "1536")
    monkeypatch.setenv("EMBEDDING_INDEX_VERSION", "embedding-v1")
    monkeypatch.setenv("EMBEDDING_BATCH_SIZE", "2")
    monkeypatch.setenv("EMBEDDING_MAX_RETRIES", "3")

    configuration = embedding_configuration_from_environment()

    assert configuration == EmbeddingConfiguration(
        model="embedding-model",
        dimensions=1536,
        index_version="embedding-v1",
        batch_size=2,
        max_retries=3,
        configuration_version="embedding-gateway.v1",
        input_cost_per_million_tokens=0.02,
    )


def test_compatible_mode_requires_an_endpoint(monkeypatch: MonkeyPatch) -> None:
    monkeypatch.setenv("MODEL_GATEWAY_MODE", "openai-compatible")
    monkeypatch.delenv("MODEL_GATEWAY_BASE_URL", raising=False)

    with raises(GatewayConfigurationError, match="MODEL_GATEWAY_BASE_URL"):
        model_gateway_from_environment(client_factory=lambda **_: object())


def test_environment_selects_an_openai_compatible_endpoint(monkeypatch: MonkeyPatch) -> None:
    monkeypatch.setenv("MODEL_GATEWAY_MODE", "openai-compatible")
    monkeypatch.setenv("MODEL_GATEWAY_BASE_URL", "http://llama-cpp:8080/v1")
    monkeypatch.setenv("MODEL_GATEWAY_MODEL", "local-model.gguf")

    gateway = model_gateway_from_environment(client_factory=lambda **_: object())

    assert gateway is not None
    assert gateway.configuration.mode == "openai-compatible"
    assert gateway.configuration.endpoint_kind == "openai-compatible"
    assert gateway.configuration.base_url == "http://llama-cpp:8080/v1"


def test_unavailable_compatible_endpoint_uses_configured_hosted_fallback() -> None:
    configuration = ModelGatewayConfiguration(
        mode="openai-compatible",
        model="local-model.gguf",
        endpoint_kind="openai-compatible",
        base_url="http://llama:8080/v1",
        api_key="local-key",
        fallback_model="gpt-5.4-mini",
        fallback_api_key="hosted-key",
    )
    local_client = _FailingCompatibleClient()
    hosted_client = _HostedClient(_Response(json.dumps({"value": "fallback"})))
    gateway = OpenAIModelGateway(
        configuration,
        client=local_client,
        fallback_client=hosted_client,
    )

    response = gateway.generate_json(instruction="Return JSON.", payload={"input": "x"})

    assert response.payload == {"value": "fallback"}
    assert response.provenance.provider == "openai"
    assert response.provenance.endpoint_kind == "hosted"
    assert response.provenance.model == "gpt-5.4-mini"
    assert response.provenance.fallback_outcome == "hosted_fallback_succeeded"
    assert response.provenance.safe_failure_reason == "compatible_endpoint_unavailable"
    assert response.provenance.input_tokens == 11
    assert response.provenance.output_tokens == 7
    assert response.provenance.cost_usd is None


def test_embedding_falls_back_to_hosted_provider_when_compatible_endpoint_is_unavailable() -> None:
    configuration = ModelGatewayConfiguration(
        mode="openai-compatible",
        model="local-embedding-model.gguf",
        endpoint_kind="openai-compatible",
        base_url="http://llama:8080/v1",
        api_key="local-key",
        fallback_model="text-embedding-3-small",
        fallback_api_key="hosted-key",
    )
    local_client = _FailingEmbeddingClient()
    hosted_client = _EmbeddingClient(vectors=[[0.25, 0.75]])
    gateway = OpenAIModelGateway(
        configuration,
        client=local_client,
        fallback_client=hosted_client,
    )

    response = gateway.embed(EmbeddingRequest(inputs=("termination rights",), dimensions=2))

    assert response.vectors == [[0.25, 0.75]]
    assert local_client.calls == 1
    assert hosted_client.calls == 1
    assert response.provenance.provider == "openai"
    assert response.provenance.endpoint_kind == "hosted"
    assert response.provenance.model == "text-embedding-3-small"
    assert response.provenance.fallback_outcome == "hosted_fallback_succeeded"
    assert response.provenance.safe_failure_reason == "compatible_endpoint_unavailable"


def test_unavailable_compatible_endpoint_has_a_safe_failure_reason_without_fallback() -> None:
    gateway = OpenAIModelGateway(
        ModelGatewayConfiguration(
            mode="openai-compatible",
            model="local-model.gguf",
            endpoint_kind="openai-compatible",
            base_url="http://llama:8080/v1",
            api_key="local-key",
        ),
        client=_FailingCompatibleClient(),
    )

    with raises(GatewayUnavailableError) as error:
        gateway.generate_json(instruction="Return JSON.", payload={"input": "x"})

    assert error.value.safe_reason == "compatible_endpoint_unavailable"


class _FailingCompatibleClient:
    class chat:
        class completions:
            @staticmethod
            def create(**kwargs: Any) -> object:
                raise ConnectionError("connection refused")


class _FailingEmbeddingClient:
    def __init__(self) -> None:
        self.embeddings = self
        self.calls = 0

    def create(self, **kwargs: Any) -> object:
        del kwargs
        self.calls += 1
        raise ConnectionError("connection refused")


class _EmbeddingClient:
    def __init__(self, *, vectors: list[list[float]]) -> None:
        self.embeddings = self
        self.calls = 0
        self._vectors = vectors

    def create(self, **kwargs: Any) -> object:
        del kwargs
        self.calls += 1
        data = [type("Embedding", (), {"embedding": vector})() for vector in self._vectors]
        usage = type("Usage", (), {"prompt_tokens": 4, "total_tokens": 4})()
        return type("EmbeddingResponse", (), {"data": data, "usage": usage})()
