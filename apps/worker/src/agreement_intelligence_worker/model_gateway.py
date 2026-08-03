from __future__ import annotations

import json
import os
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from time import perf_counter
from typing import Any, Literal, Protocol, cast

from openai import APIConnectionError, APIError, APIStatusError, OpenAI, OpenAIError

type GatewayMode = Literal["openai", "openai-compatible"]
type EndpointKind = Literal["hosted", "openai-compatible"]


class GatewayConfigurationError(ValueError):
    """Raised when a selected gateway mode lacks safe operator configuration."""


class GatewayUnavailableError(RuntimeError):
    """Raised when a model endpoint is unavailable and no configured fallback succeeds."""

    def __init__(self, safe_reason: str) -> None:
        super().__init__(safe_reason.replace("_", " "))
        self.safe_reason = safe_reason


class GatewayResponseError(RuntimeError):
    """Raised when a model endpoint returns a response that cannot be used safely."""


@dataclass(frozen=True)
class ModelGatewayConfiguration:
    mode: GatewayMode
    model: str
    endpoint_kind: EndpointKind
    base_url: str | None
    api_key: str
    configuration_version: str = "model-gateway.v1"
    fallback_model: str | None = None
    fallback_api_key: str | None = None


@dataclass(frozen=True)
class EmbeddingConfiguration:
    """Versioned embedding settings, deliberately separate from generation settings."""

    model: str
    dimensions: int
    index_version: str
    batch_size: int
    max_retries: int
    configuration_version: str
    input_cost_per_million_tokens: float


@dataclass(frozen=True)
class GatewayProvenance:
    provider: str
    endpoint_kind: EndpointKind
    model: str
    configuration_version: str
    latency_ms: int
    input_tokens: int | None
    output_tokens: int | None
    total_tokens: int | None
    cost_usd: float | None
    retry_outcome: str
    fallback_outcome: str
    safe_failure_reason: str | None


@dataclass(frozen=True)
class GatewayJsonResponse:
    payload: dict[str, object]
    provenance: GatewayProvenance


@dataclass(frozen=True)
class EmbeddingRequest:
    inputs: Sequence[str]
    model: str | None = None
    dimensions: int | None = None


@dataclass(frozen=True)
class EmbeddingResponse:
    vectors: list[list[float]]
    provenance: GatewayProvenance


@dataclass(frozen=True)
class GroundedAnswerRequest:
    question: str
    evidence: Sequence[tuple[str, str]]
    model: str | None = None


@dataclass(frozen=True)
class GroundedAnswerResponse:
    answer: str
    citation_ids: list[str]
    provenance: GatewayProvenance


class ModelGateway(Protocol):
    """Provider-neutral boundary for document analysis, embeddings, and grounded answers.

    Anthropic and Gemini adapters are deliberately future contracts. Adding either requires a
    separately tested implementation of this protocol rather than an unconfigured dependency.
    """

    configuration: ModelGatewayConfiguration

    def generate_json(
        self,
        *,
        instruction: str,
        payload: Mapping[str, object],
        schema: Mapping[str, object] | None = None,
    ) -> GatewayJsonResponse: ...

    def embed(self, request: EmbeddingRequest) -> EmbeddingResponse: ...

    def answer(self, request: GroundedAnswerRequest) -> GroundedAnswerResponse: ...


class OpenAIModelGateway:
    """Gateway implementation for OpenAI and OpenAI-compatible HTTP endpoints."""

    def __init__(
        self,
        configuration: ModelGatewayConfiguration,
        *,
        client: Any,
        fallback_client: Any | None = None,
    ) -> None:
        self.configuration = configuration
        self._client = client
        self._fallback_client = fallback_client

    def generate_json(
        self,
        *,
        instruction: str,
        payload: Mapping[str, object],
        schema: Mapping[str, object] | None = None,
    ) -> GatewayJsonResponse:
        started_at = perf_counter()
        try:
            response = self._generate_json(
                self._client,
                self.configuration,
                instruction=instruction,
                payload=payload,
                schema=schema,
            )
        except GatewayUnavailableError as error:
            return self._fallback_json(
                error,
                started_at=started_at,
                instruction=instruction,
                payload=payload,
                schema=schema,
            )
        return GatewayJsonResponse(
            payload=_json_object(response[0]),
            provenance=_provenance(
                self.configuration,
                response[1],
                started_at=started_at,
                fallback_outcome="not_needed",
                safe_failure_reason=None,
            ),
        )

    def embed(self, request: EmbeddingRequest) -> EmbeddingResponse:
        started_at = perf_counter()
        try:
            vectors, usage = self._embed(
                self._client,
                self.configuration,
                request,
                use_requested_model=True,
            )
        except GatewayUnavailableError as error:
            return self._fallback_embed(error, started_at=started_at, request=request)
        return EmbeddingResponse(
            vectors=vectors,
            provenance=_provenance(
                self.configuration,
                usage,
                started_at=started_at,
                fallback_outcome="not_needed",
                safe_failure_reason=None,
            ),
        )

    def _fallback_embed(
        self,
        primary_error: GatewayUnavailableError,
        *,
        started_at: float,
        request: EmbeddingRequest,
    ) -> EmbeddingResponse:
        if self._fallback_client is None or self.configuration.fallback_model is None:
            raise primary_error
        fallback_configuration = ModelGatewayConfiguration(
            mode="openai",
            model=self.configuration.fallback_model,
            endpoint_kind="hosted",
            base_url=None,
            api_key=cast(str, self.configuration.fallback_api_key),
            configuration_version=self.configuration.configuration_version,
        )
        try:
            vectors, usage = self._embed(
                self._fallback_client,
                fallback_configuration,
                request,
                use_requested_model=False,
            )
        except Exception as fallback_error:
            raise GatewayUnavailableError("primary_and_fallback_unavailable") from fallback_error
        return EmbeddingResponse(
            vectors=vectors,
            provenance=_provenance(
                fallback_configuration,
                usage,
                started_at=started_at,
                fallback_outcome="hosted_fallback_succeeded",
                safe_failure_reason=primary_error.safe_reason,
            ),
        )

    def _embed(
        self,
        client: Any,
        configuration: ModelGatewayConfiguration,
        request: EmbeddingRequest,
        *,
        use_requested_model: bool,
    ) -> tuple[list[list[float]], object]:
        request_options: dict[str, object] = {
            "model": request.model
            if use_requested_model and request.model
            else configuration.model,
            "input": list(request.inputs),
        }
        if request.dimensions is not None:
            request_options["dimensions"] = request.dimensions
        try:
            response = client.embeddings.create(**request_options)
        except Exception as error:
            raise _gateway_error(error) from error
        vectors = [list(cast(Sequence[float], item.embedding)) for item in response.data]
        return vectors, getattr(response, "usage", None)

    def answer(self, request: GroundedAnswerRequest) -> GroundedAnswerResponse:
        result = self.generate_json(
            instruction=(
                "Answer only from the supplied evidence. Return JSON with answer and citation_ids. "
                "Only cite supplied anchor IDs."
            ),
            payload={
                "question": request.question,
                "evidence": [
                    {"anchor_id": anchor_id, "text": text} for anchor_id, text in request.evidence
                ],
            },
        )
        answer = result.payload.get("answer")
        citation_ids = result.payload.get("citation_ids")
        if (
            not isinstance(answer, str)
            or not isinstance(citation_ids, list)
            or not all(isinstance(citation_id, str) for citation_id in citation_ids)
        ):
            raise GatewayResponseError("Model response has an invalid grounded-answer shape")
        return GroundedAnswerResponse(
            answer=answer,
            citation_ids=cast(list[str], citation_ids),
            provenance=result.provenance,
        )

    def _fallback_json(
        self,
        primary_error: GatewayUnavailableError,
        *,
        started_at: float,
        instruction: str,
        payload: Mapping[str, object],
        schema: Mapping[str, object] | None,
    ) -> GatewayJsonResponse:
        if self._fallback_client is None or self.configuration.fallback_model is None:
            raise primary_error
        fallback_configuration = ModelGatewayConfiguration(
            mode="openai",
            model=self.configuration.fallback_model,
            endpoint_kind="hosted",
            base_url=None,
            api_key=cast(str, self.configuration.fallback_api_key),
            configuration_version=self.configuration.configuration_version,
        )
        try:
            response = self._generate_json(
                self._fallback_client,
                fallback_configuration,
                instruction=instruction,
                payload=payload,
                schema=schema,
            )
        except Exception as fallback_error:
            raise GatewayUnavailableError("primary_and_fallback_unavailable") from fallback_error
        return GatewayJsonResponse(
            payload=_json_object(response[0]),
            provenance=_provenance(
                fallback_configuration,
                response[1],
                started_at=started_at,
                fallback_outcome="hosted_fallback_succeeded",
                safe_failure_reason=primary_error.safe_reason,
            ),
        )

    def _generate_json(
        self,
        client: Any,
        configuration: ModelGatewayConfiguration,
        *,
        instruction: str,
        payload: Mapping[str, object],
        schema: Mapping[str, object] | None,
    ) -> tuple[str, object]:
        try:
            if configuration.mode == "openai":
                response = client.responses.create(
                    model=configuration.model,
                    input=_messages(instruction, payload),
                    text={"format": _hosted_response_format(schema)},
                )
                return cast(str, response.output_text), getattr(response, "usage", None)
            response = client.chat.completions.create(
                model=configuration.model,
                messages=_chat_messages(instruction, payload),
                response_format=_compatible_response_format(schema),
            )
            content = response.choices[0].message.content
            if not isinstance(content, str):
                raise GatewayResponseError("Compatible endpoint returned an empty response")
            return content, getattr(response, "usage", None)
        except GatewayResponseError:
            raise
        except Exception as error:
            raise _gateway_error(error) from error


def model_gateway_from_environment(
    *,
    client_factory: Callable[..., Any] = OpenAI,
    model_override: str | None = None,
    configuration_version_override: str | None = None,
    fallback_model_override: str | None = None,
) -> OpenAIModelGateway | None:
    mode = cast(GatewayMode, os.environ.get("MODEL_GATEWAY_MODE", "openai"))
    if mode not in {"openai", "openai-compatible"}:
        raise GatewayConfigurationError("MODEL_GATEWAY_MODE must be openai or openai-compatible")
    model = model_override or os.environ.get(
        "MODEL_GATEWAY_MODEL", os.environ.get("OPENAI_MODEL", "gpt-5.4-mini")
    )
    version = configuration_version_override or os.environ.get(
        "MODEL_GATEWAY_CONFIG_VERSION", "model-gateway.v1"
    )
    if mode == "openai":
        api_key = os.environ.get("MODEL_GATEWAY_API_KEY", os.environ.get("OPENAI_API_KEY"))
        if not api_key:
            return None
        configuration = ModelGatewayConfiguration(
            mode="openai",
            model=model,
            endpoint_kind="hosted",
            base_url=None,
            api_key=api_key,
            configuration_version=version,
        )
        return OpenAIModelGateway(configuration, client=client_factory(api_key=api_key))

    base_url = os.environ.get("MODEL_GATEWAY_BASE_URL")
    if not base_url:
        raise GatewayConfigurationError(
            "MODEL_GATEWAY_BASE_URL is required for openai-compatible mode"
        )
    fallback_mode = os.environ.get("MODEL_GATEWAY_FALLBACK_MODE")
    fallback_key = os.environ.get("OPENAI_API_KEY") if fallback_mode == "openai" else None
    if fallback_mode not in {None, "", "openai"}:
        raise GatewayConfigurationError("MODEL_GATEWAY_FALLBACK_MODE must be openai when set")
    if fallback_mode == "openai" and not fallback_key:
        raise GatewayConfigurationError("OPENAI_API_KEY is required for an openai fallback")
    configuration = ModelGatewayConfiguration(
        mode="openai-compatible",
        model=model,
        endpoint_kind="openai-compatible",
        base_url=base_url,
        api_key=os.environ.get("MODEL_GATEWAY_API_KEY", "not-required"),
        configuration_version=version,
        fallback_model=(
            fallback_model_override
            or os.environ.get("MODEL_GATEWAY_FALLBACK_MODEL", os.environ.get("OPENAI_MODEL", model))
            if fallback_key
            else None
        ),
        fallback_api_key=fallback_key,
    )
    return OpenAIModelGateway(
        configuration,
        client=client_factory(api_key=configuration.api_key, base_url=base_url),
        fallback_client=client_factory(api_key=fallback_key) if fallback_key else None,
    )


def embedding_configuration_from_environment() -> EmbeddingConfiguration:
    """Read explicit, independently-versioned embedding configuration."""

    dimensions = _positive_environment_integer("EMBEDDING_DIMENSIONS", 1536)
    batch_size = _positive_environment_integer("EMBEDDING_BATCH_SIZE", 32)
    max_retries = _non_negative_environment_integer("EMBEDDING_MAX_RETRIES", 2)
    input_cost = _non_negative_environment_float("EMBEDDING_INPUT_COST_PER_MILLION_TOKENS", 0.02)
    return EmbeddingConfiguration(
        model=os.environ.get("EMBEDDING_MODEL", "text-embedding-3-small"),
        dimensions=dimensions,
        index_version=os.environ.get("EMBEDDING_INDEX_VERSION", "embedding-v1"),
        batch_size=batch_size,
        max_retries=max_retries,
        configuration_version=os.environ.get("EMBEDDING_CONFIG_VERSION", "embedding-gateway.v1"),
        input_cost_per_million_tokens=input_cost,
    )


def embedding_gateway_from_environment(
    *, client_factory: Callable[..., Any] = OpenAI
) -> OpenAIModelGateway | None:
    """Build an embedding gateway without inheriting the generation-model choice."""

    configuration = embedding_configuration_from_environment()
    return model_gateway_from_environment(
        client_factory=client_factory,
        model_override=configuration.model,
        configuration_version_override=configuration.configuration_version,
        fallback_model_override=os.environ.get("EMBEDDING_FALLBACK_MODEL") or configuration.model,
    )


def _messages(instruction: str, payload: Mapping[str, object]) -> list[dict[str, object]]:
    return [
        {
            "role": "system",
            "content": [{"type": "input_text", "text": instruction}],
        },
        {
            "role": "user",
            "content": [{"type": "input_text", "text": json.dumps(payload)}],
        },
    ]


def _chat_messages(instruction: str, payload: Mapping[str, object]) -> list[dict[str, str]]:
    return [
        {"role": "system", "content": instruction},
        {"role": "user", "content": json.dumps(payload)},
    ]


def _hosted_response_format(schema: Mapping[str, object] | None) -> dict[str, object]:
    if schema is None:
        return {"type": "json_object"}
    return {
        "type": "json_schema",
        "name": "gateway_response",
        "strict": True,
        "schema": dict(schema),
    }


def _compatible_response_format(schema: Mapping[str, object] | None) -> dict[str, object]:
    if schema is None:
        return {"type": "json_object"}
    return {
        "type": "json_schema",
        "json_schema": {"name": "gateway_response", "strict": True, "schema": dict(schema)},
    }


def _json_object(text: str) -> dict[str, object]:
    try:
        payload = json.loads(text)
    except json.JSONDecodeError as error:
        raise GatewayResponseError("Model response was not valid JSON") from error
    if not isinstance(payload, dict):
        raise GatewayResponseError("Model response must be a JSON object")
    return cast(dict[str, object], payload)


def _gateway_error(error: Exception) -> GatewayUnavailableError | GatewayResponseError:
    if isinstance(error, GatewayUnavailableError | GatewayResponseError):
        return error
    if isinstance(error, (ConnectionError, TimeoutError, APIConnectionError)):
        return GatewayUnavailableError("compatible_endpoint_unavailable")
    if isinstance(error, APIStatusError):
        if error.status_code >= 500 or error.status_code in {408, 409, 429}:
            return GatewayUnavailableError("endpoint_retryable_response")
        return GatewayResponseError("Model endpoint rejected the request")
    if isinstance(error, APIError):
        return GatewayUnavailableError("endpoint_unavailable")
    if isinstance(error, OpenAIError):
        return GatewayResponseError("Model endpoint rejected the request")
    return GatewayResponseError("Model endpoint returned an invalid response")


def _provenance(
    configuration: ModelGatewayConfiguration,
    usage: object,
    *,
    started_at: float,
    fallback_outcome: str,
    safe_failure_reason: str | None,
) -> GatewayProvenance:
    input_tokens = _usage_integer(usage, "input_tokens", "prompt_tokens")
    output_tokens = _usage_integer(usage, "output_tokens", "completion_tokens")
    total_tokens = _usage_integer(usage, "total_tokens")
    return GatewayProvenance(
        provider="openai" if configuration.mode == "openai" else "openai-compatible",
        endpoint_kind=configuration.endpoint_kind,
        model=configuration.model,
        configuration_version=configuration.configuration_version,
        latency_ms=round((perf_counter() - started_at) * 1_000),
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        total_tokens=total_tokens,
        cost_usd=None,
        retry_outcome="not_retried",
        fallback_outcome=fallback_outcome,
        safe_failure_reason=safe_failure_reason,
    )


def _usage_integer(usage: object, *names: str) -> int | None:
    for name in names:
        value = getattr(usage, name, None)
        if isinstance(value, int) and value >= 0:
            return value
    return None


def _positive_environment_integer(name: str, default: int) -> int:
    value = _environment_integer(name, default)
    if value < 1:
        raise GatewayConfigurationError(f"{name} must be a positive integer")
    return value


def _non_negative_environment_integer(name: str, default: int) -> int:
    value = _environment_integer(name, default)
    if value < 0:
        raise GatewayConfigurationError(f"{name} must be zero or a positive integer")
    return value


def _environment_integer(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if raw is None:
        return default
    try:
        return int(raw)
    except ValueError as error:
        raise GatewayConfigurationError(f"{name} must be an integer") from error


def _non_negative_environment_float(name: str, default: float) -> float:
    raw = os.environ.get(name)
    if raw is None:
        return default
    try:
        value = float(raw)
    except ValueError as error:
        raise GatewayConfigurationError(f"{name} must be a number") from error
    if value < 0:
        raise GatewayConfigurationError(f"{name} must be zero or positive")
    return value
