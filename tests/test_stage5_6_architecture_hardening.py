from pathlib import Path

import pytest

from flows.flow_definitions import (
    FLOW_DEFINITIONS,
    _load_symbol,
    get_flow_definition,
    get_flow_step_builder,
    get_pipeline_templates,
)
from orchestrator.flow_validation import validate_flow_formats
from workers.base.format_converter import FormatConverter


def test_stage56_flow_registry_contains_split_modules() -> None:
    flow_files = [
        Path("flows/stage2_test_flow.py"),
        Path("flows/stage4_segmentation_completion_flow.py"),
        Path("flows/stage4_real_two_model_flow.py"),
        Path("flows/stage4_snowflake_only_flow.py"),
        Path("flows/stage4_shape_as_points_only_flow.py"),
        Path("flows/stage4_cloudcompare_only_flow.py"),
    ]
    for file_path in flow_files:
        assert file_path.exists(), f"Missing split flow file: {file_path}"


def test_stage56_flow_definitions_have_unique_ids() -> None:
    flow_ids = [item.flow_id for item in FLOW_DEFINITIONS]
    assert len(flow_ids) == len(set(flow_ids))
    assert "stage4_real_two_model_flow" in flow_ids


def test_stage56_loader_resolves_module_symbol() -> None:
    path_cls = _load_symbol("pathlib:Path")
    assert path_cls.__name__ == "Path"


def test_stage56_templates_are_generated_from_definitions() -> None:
    templates = get_pipeline_templates()
    ids = {item["flow_id"] for item in templates}
    assert "stage2_test_flow" in ids
    assert "stage4_real_two_model_flow" in ids


def test_stage56_step_builder_available_for_stage4_flows() -> None:
    definition = get_flow_definition("stage4_snowflake_only_flow")
    assert definition is not None
    builder = get_flow_step_builder("stage4_snowflake_only_flow")
    assert builder is not None
    steps = builder({})
    assert len(steps) == 1
    assert steps[0]["worker_module"] == "workers.completion.snowflake_net.worker"


def test_stage56_format_validation_rejects_incompatible_input() -> None:
    with pytest.raises(ValueError, match="Input format"):
        validate_flow_formats(
            flow_id="stage4_snowflake_only_flow",
            flow_params={},
            input_key="uploads/input.obj",
            input_keys=None,
        )


def test_stage56_format_validation_accepts_batch_input_keys() -> None:
    validate_flow_formats(
        flow_id="stage4_real_two_model_flow",
        flow_params={},
        input_key="uploads/fallback.xyz",
        input_keys=["uploads/a.xyz", "uploads/b.pcd", "uploads/c.las"],
    )


def test_stage56_converter_strategy_supports_explicit_conversion() -> None:
    converter = FormatConverter()
    assert converter.can_convert_format(".pcd", ".ply")
    assert converter.can_convert_format(".las", ".xyz")
    assert not converter.can_convert_format(".obj", ".ply")


def test_stage56_converter_converts_to_target_suffix(tmp_path: Path) -> None:
    source = tmp_path / "source.xyz"
    source.write_text("0 0 0\n1 1 1\n", encoding="utf-8")
    converted = FormatConverter().convert(source, ".ply", tmp_path / "work")
    assert converted.suffix == ".ply"
    assert converted.exists()
