from __future__ import annotations

import os
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from enum import StrEnum
from functools import lru_cache

from sqlalchemy import create_engine, text


class AIOperation(StrEnum):
    DOCUMENT_ANALYSIS = "document_analysis"
    EMBEDDING = "embedding"
    GROUNDED_QA = "grounded_qa"
    VERSION_MATERIALITY = "version_materiality"


@dataclass(frozen=True)
class ResolvedAIConfiguration:
    operation: str
    version: str
    prompt_template: str
    schema: Mapping[str, object]
    model_route: str
    parameters: Mapping[str, object]
    schema_checksum: str


ConfigurationSnapshot = ResolvedAIConfiguration
ConfigurationLoader = Callable[[AIOperation, str], ConfigurationSnapshot | None]


class ConfigurationResolver:
    def __init__(self, loader: ConfigurationLoader) -> None:
        self._loader = loader

    def resolve_configuration(
        self, operation: AIOperation, environment: str
    ) -> ResolvedAIConfiguration:
        return self._loader(operation, environment) or _BUILT_IN_CONFIGURATIONS[operation]


class DatabaseConfigurationResolver(ConfigurationResolver):
    def __init__(self, database_url: str) -> None:
        normalized_url = database_url.replace("postgresql://", "postgresql+psycopg://", 1)
        self._engine = create_engine(normalized_url)
        super().__init__(self._load)

    def _load(self, operation: AIOperation, environment: str) -> ConfigurationSnapshot | None:
        statement = text(
            """
            SELECT version.operation, version.version, version.prompt_template, version.schema_json,
                   version.model_route, version.parameters_json, version.schema_checksum
            FROM ai_configuration_promotions AS promotion
            JOIN ai_configuration_versions AS version ON version.id = promotion.configuration_id
            WHERE promotion.operation = :operation
              AND promotion.environment = :environment
              AND version.status = 'published'
            ORDER BY promotion.promoted_at DESC, promotion.id DESC
            LIMIT 1
            """
        )
        with self._engine.connect() as connection:
            row = (
                connection.execute(
                    statement, {"operation": operation.value, "environment": environment}
                )
                .mappings()
                .first()
            )
        if row is None:
            return None
        return ConfigurationSnapshot(
            operation=str(row["operation"]),
            version=str(row["version"]),
            prompt_template=str(row["prompt_template"]),
            schema=dict(row["schema_json"]),
            model_route=str(row["model_route"]),
            parameters=dict(row["parameters_json"]),
            schema_checksum=str(row["schema_checksum"]),
        )


def resolve_configuration(operation: AIOperation, environment: str) -> ResolvedAIConfiguration:
    return configuration_resolver_from_environment().resolve_configuration(operation, environment)


def model_for_route(configuration: ResolvedAIConfiguration, fallback_model: str) -> str:
    """Return the configured model only for an explicit provider-neutral route."""

    provider, separator, model = configuration.model_route.partition(":")
    if separator and provider in {"openai", "openai-compatible"} and model:
        return model
    return fallback_model


@lru_cache
def configuration_resolver_from_environment() -> ConfigurationResolver:
    database_url = os.environ.get("DATABASE_URL")
    if database_url:
        return DatabaseConfigurationResolver(database_url)
    return ConfigurationResolver(lambda _operation, _environment: None)


_BUILT_IN_CONFIGURATIONS: dict[AIOperation, ResolvedAIConfiguration] = {
    operation: ResolvedAIConfiguration(
        operation=operation.value,
        version=f"builtin.{operation.value}.v1",
        prompt_template="",
        schema={},
        model_route="environment-default",
        parameters={},
        schema_checksum="builtin",
    )
    for operation in AIOperation
}
