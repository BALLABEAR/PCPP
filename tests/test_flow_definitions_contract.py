from flows.flow_definitions import build_stage4_pointr_only_steps


def test_pointr_builder_uses_unified_cli_keys() -> None:
    steps = build_stage4_pointr_only_steps({})
    assert len(steps) == 1
    cli_args = steps[0].get("cli_args", {})
    assert "weights_path" in cli_args
    assert "config_path" in cli_args
    assert "weights" not in cli_args
    assert "config" not in cli_args
