def test_phase_one_contracts_import() -> None:
    import websockets

    from friendly_filter import config, models

    assert websockets.version.version
    assert config.RULE_VERSION == models.VersionedRecord().schema_version
