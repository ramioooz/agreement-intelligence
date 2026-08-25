from agreement_intelligence_worker.ai_configuration import (
    AIOperation,
    ConfigurationResolver,
    ConfigurationSnapshot,
)


def test_historical_resolution_keeps_original_version_after_a_new_promotion() -> None:
    promotions = {
        (AIOperation.GROUNDED_QA, "production"): ConfigurationSnapshot(
            operation=AIOperation.GROUNDED_QA,
            version="1.0.0",
            prompt_template="Answer only from supplied evidence.",
            schema={"type": "object"},
            model_route="openai:gpt-5.4-mini",
            parameters={"temperature": 0},
            schema_checksum="schema-v1",
        )
    }
    resolver = ConfigurationResolver(
        lambda operation, environment: promotions.get((operation, environment))
    )

    original = resolver.resolve_configuration(AIOperation.GROUNDED_QA, "production")
    promotions[(AIOperation.GROUNDED_QA, "production")] = ConfigurationSnapshot(
        operation=AIOperation.GROUNDED_QA,
        version="2.0.0",
        prompt_template="Answer only from current supplied evidence.",
        schema={"type": "object"},
        model_route="openai:gpt-5.4-mini",
        parameters={"temperature": 0},
        schema_checksum="schema-v2",
    )

    current = resolver.resolve_configuration(AIOperation.GROUNDED_QA, "production")

    assert original.version == "1.0.0"
    assert original.schema_checksum == "schema-v1"
    assert current.version == "2.0.0"
    assert current.schema_checksum == "schema-v2"
