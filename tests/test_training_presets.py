from pathlib import Path

from orchestrator.training.presets import list_training_presets


def test_snowflake_training_preset_is_available(monkeypatch) -> None:
    monkeypatch.setenv("WORKSPACE_ROOT", str(Path(__file__).resolve().parents[1]))
    presets = list_training_presets()
    by_id = {preset.profile_id: preset for preset in presets}
    assert "snowflake_completion" in by_id

    preset = by_id["snowflake_completion"]
    assert preset.model_id == "snowflake"
    assert preset.task_type == "completion"
    assert preset.dataset_kind == "completion3d"
    assert "scratch" in preset.modes
    assert "finetune" in preset.modes
    assert preset.default_train_script.name == "train.py"
