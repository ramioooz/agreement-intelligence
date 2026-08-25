from __future__ import annotations

import os
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from enum import StrEnum
from functools import lru_cache
from typing import cast
from uuid import UUID

from sqlalchemy import create_engine, text
from sqlalchemy.engine import RowMapping


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
ConfigurationLoader = Callable[
    [AIOperation, str, UUID | None, UUID | None], ConfigurationSnapshot | None
]
ConfigurationByIdLoader = Callable[
    [AIOperation, UUID, UUID | None, UUID | None], ConfigurationSnapshot | None
]
ConfigurationByVersionLoader = Callable[
    [AIOperation, str, UUID | None, UUID | None], ConfigurationSnapshot | None
]


class ConfigurationResolver:
    def __init__(
        self,
        loader: ConfigurationLoader,
        configuration_by_id_loader: ConfigurationByIdLoader | None = None,
        configuration_by_version_loader: ConfigurationByVersionLoader | None = None,
    ) -> None:
        self._loader = loader
        self._configuration_by_id_loader = configuration_by_id_loader
        self._configuration_by_version_loader = configuration_by_version_loader

    def resolve_configuration(
        self,
        operation: AIOperation,
        environment: str,
        *,
        organization_id: UUID | None = None,
        workspace_id: UUID | None = None,
    ) -> ResolvedAIConfiguration:
        return (
            self._loader(operation, environment, organization_id, workspace_id)
            or _BUILT_IN_CONFIGURATIONS[operation]
        )

    def resolve_configuration_by_id(
        self,
        operation: AIOperation,
        configuration_id: UUID,
        *,
        organization_id: UUID | None = None,
        workspace_id: UUID | None = None,
    ) -> ResolvedAIConfiguration | None:
        if self._configuration_by_id_loader is None:
            return None
        return self._configuration_by_id_loader(
            operation,
            configuration_id,
            organization_id,
            workspace_id,
        )

    def resolve_configuration_by_version(
        self,
        operation: AIOperation,
        version: str,
        *,
        organization_id: UUID | None = None,
        workspace_id: UUID | None = None,
    ) -> ResolvedAIConfiguration | None:
        built_in = _BUILT_IN_CONFIGURATIONS[operation]
        if version == built_in.version:
            return built_in
        if self._configuration_by_version_loader is None:
            return None
        return self._configuration_by_version_loader(
            operation,
            version,
            organization_id,
            workspace_id,
        )


class DatabaseConfigurationResolver(ConfigurationResolver):
    def __init__(self, database_url: str) -> None:
        normalized_url = database_url.replace("postgresql://", "postgresql+psycopg://", 1)
        self._engine = create_engine(normalized_url)
        super().__init__(self._load, self._load_by_id, self._load_by_version)

    def _load(
        self,
        operation: AIOperation,
        environment: str,
        organization_id: UUID | None,
        workspace_id: UUID | None,
    ) -> ConfigurationSnapshot | None:
        if organization_id is None or workspace_id is None:
            return None
        statement = text(
            """
            SELECT version.operation, version.version, version.prompt_template, version.schema_json,
                   version.model_route, version.parameters_json, version.schema_checksum
            FROM ai_configuration_promotions AS promotion
            JOIN ai_configuration_versions AS version ON version.id = promotion.configuration_id
            WHERE promotion.operation = :operation
              AND promotion.environment = :environment
              AND promotion.organization_id = :organization_id
              AND promotion.workspace_id = :workspace_id
              AND version.organization_id = :organization_id
              AND version.workspace_id = :workspace_id
              AND version.status = 'published'
            ORDER BY promotion.promoted_at DESC, promotion.id DESC
            LIMIT 1
            """
        )
        with self._engine.connect() as connection:
            if connection.dialect.name == "postgresql":
                connection.execute(
                    text("SELECT set_config('app.organization_id', :organization_id, true)"),
                    {"organization_id": str(organization_id)},
                )
            row = (
                connection.execute(
                    statement,
                    {
                        "operation": operation.value,
                        "environment": environment,
                        "organization_id": str(organization_id),
                        "workspace_id": str(workspace_id),
                    },
                )
                .mappings()
                .first()
            )
        if row is None:
            return None
        return _snapshot(row)

    def _load_by_id(
        self,
        operation: AIOperation,
        configuration_id: UUID,
        organization_id: UUID | None,
        workspace_id: UUID | None,
    ) -> ConfigurationSnapshot | None:
        if organization_id is None or workspace_id is None:
            return None
        statement = text(
            """
            SELECT operation, version, prompt_template, schema_json, model_route,
                   parameters_json, schema_checksum
            FROM ai_configuration_versions
            WHERE id = :configuration_id
              AND operation = :operation
              AND organization_id = :organization_id
              AND workspace_id = :workspace_id
              AND status = 'published'
            LIMIT 1
            """
        )
        with self._engine.connect() as connection:
            if connection.dialect.name == "postgresql":
                connection.execute(
                    text("SELECT set_config('app.organization_id', :organization_id, true)"),
                    {"organization_id": str(organization_id)},
                )
            row = (
                connection.execute(
                    statement,
                    {
                        "configuration_id": str(configuration_id),
                        "operation": operation.value,
                        "organization_id": str(organization_id),
                        "workspace_id": str(workspace_id),
                    },
                )
                .mappings()
                .first()
            )
        return _snapshot(row) if row is not None else None

    def _load_by_version(
        self,
        operation: AIOperation,
        version: str,
        organization_id: UUID | None,
        workspace_id: UUID | None,
    ) -> ConfigurationSnapshot | None:
        if organization_id is None or workspace_id is None:
            return None
        statement = text(
            """
            SELECT operation, version, prompt_template, schema_json, model_route,
                   parameters_json, schema_checksum
            FROM ai_configuration_versions
            WHERE version = :version
              AND operation = :operation
              AND organization_id = :organization_id
              AND workspace_id = :workspace_id
              AND status = 'published'
            LIMIT 1
            """
        )
        with self._engine.connect() as connection:
            if connection.dialect.name == "postgresql":
                connection.execute(
                    text("SELECT set_config('app.organization_id', :organization_id, true)"),
                    {"organization_id": str(organization_id)},
                )
            row = (
                connection.execute(
                    statement,
                    {
                        "version": version,
                        "operation": operation.value,
                        "organization_id": str(organization_id),
                        "workspace_id": str(workspace_id),
                    },
                )
                .mappings()
                .first()
            )
        return _snapshot(row) if row is not None else None


def _snapshot(row: RowMapping) -> ConfigurationSnapshot:
    return ConfigurationSnapshot(
        operation=str(row["operation"]),
        version=str(row["version"]),
        prompt_template=str(row["prompt_template"]),
        schema=dict(cast(Mapping[str, object], row["schema_json"])),
        model_route=str(row["model_route"]),
        parameters=dict(cast(Mapping[str, object], row["parameters_json"])),
        schema_checksum=str(row["schema_checksum"]),
    )


def resolve_configuration(
    operation: AIOperation,
    environment: str,
    *,
    organization_id: UUID | None = None,
    workspace_id: UUID | None = None,
) -> ResolvedAIConfiguration:
    return configuration_resolver_from_environment().resolve_configuration(
        operation,
        environment,
        organization_id=organization_id,
        workspace_id=workspace_id,
    )


def resolve_configuration_by_id(
    operation: AIOperation,
    configuration_id: UUID,
    *,
    organization_id: UUID | None = None,
    workspace_id: UUID | None = None,
) -> ResolvedAIConfiguration | None:
    return configuration_resolver_from_environment().resolve_configuration_by_id(
        operation,
        configuration_id,
        organization_id=organization_id,
        workspace_id=workspace_id,
    )


def resolve_configuration_by_version(
    operation: AIOperation,
    version: str,
    *,
    organization_id: UUID | None = None,
    workspace_id: UUID | None = None,
) -> ResolvedAIConfiguration | None:
    return configuration_resolver_from_environment().resolve_configuration_by_version(
        operation,
        version,
        organization_id=organization_id,
        workspace_id=workspace_id,
    )


def model_for_route(
    configuration: ResolvedAIConfiguration, fallback_model: str, *, endpoint_mode: str
) -> str:
    """Return only a route compatible with the configured provider endpoint."""

    provider, separator, model = configuration.model_route.partition(":")
    if configuration.model_route == "environment-default" and configuration.version.startswith(
        "builtin."
    ):
        return fallback_model
    if separator and provider == endpoint_mode and model:
        return model
    raise ValueError("unsupported AI configuration route")


@lru_cache
def configuration_resolver_from_environment() -> ConfigurationResolver:
    database_url = os.environ.get("DATABASE_URL")
    if database_url:
        return DatabaseConfigurationResolver(database_url)
    return ConfigurationResolver(
        lambda _operation, _environment, _organization_id, _workspace_id: None
    )


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
