def test_phase_one_contracts_import() -> None:
    from friendly_filter import config, models

    assert config.RULE_VERSION == models.VersionedRecord().schema_version
