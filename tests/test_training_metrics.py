import json
from pathlib import Path
from types import SimpleNamespace

from orchestrator.training.metrics import (
    EarlyStoppingConfig,
    evaluate_early_stopping,
    load_metric_events,
)
from orchestrator.training.runtime_shims.metrics_capture import patch_summary_writer_module
from orchestrator.training.runtime_shims.tensorboardX import SummaryWriter


def test_tensorboardx_shim_records_scalar_events(tmp_path: Path, monkeypatch) -> None:
    history_path = tmp_path / "metrics_history.jsonl"
    monkeypatch.setenv("PCPP_METRICS_HISTORY_PATH", str(history_path))

    writer = SummaryWriter(str(tmp_path / "tb"))
    writer.add_scalar("Loss/Epoch/cd_p3", 0.125, 3)
    writer.close()

    events = load_metric_events(history_path)
    assert len(events) == 1
    assert events[0].tag == "Loss/Epoch/cd_p3"
    assert events[0].value == 0.125
    assert events[0].step == 3
    assert events[0].source == "tensorboardX"


def test_patch_summary_writer_module_wraps_real_writer_and_preserves_delegate(tmp_path: Path, monkeypatch) -> None:
    history_path = tmp_path / "metrics_history.jsonl"
    monkeypatch.setenv("PCPP_METRICS_HISTORY_PATH", str(history_path))
    recorded: list[tuple[str, float, int | None]] = []

    class FakeWriter:
        def __init__(self, *args, **kwargs) -> None:
            self.log_dir = args[0] if args else kwargs.get("log_dir")

        def add_scalar(self, tag, scalar_value, global_step=None, walltime=None, *args, **kwargs):
            recorded.append((tag, float(scalar_value), global_step))

        def close(self) -> None:
            return None

    fake_module = SimpleNamespace(SummaryWriter=FakeWriter, FileWriter=FakeWriter)
    patch_summary_writer_module(fake_module, "torch.utils.tensorboard")

    writer = fake_module.SummaryWriter(str(tmp_path / "real"))
    writer.add_scalar("val/loss", 1.5, 7)
    writer.close()

    assert recorded == [("val/loss", 1.5, 7)]
    events = load_metric_events(history_path)
    assert len(events) == 1
    assert events[0].source == "torch.utils.tensorboard"


def test_evaluate_early_stopping_triggers_after_patience(tmp_path: Path) -> None:
    history_path = tmp_path / "metrics_history.jsonl"
    lines = [
        {"tag": "val/loss", "value": 1.0, "step": 1, "wall_time": 1.0, "source": "tensorboardX"},
        {"tag": "val/loss", "value": 1.0, "step": 2, "wall_time": 2.0, "source": "tensorboardX"},
        {"tag": "val/loss", "value": 1.05, "step": 3, "wall_time": 3.0, "source": "tensorboardX"},
    ]
    history_path.write_text("\n".join(json.dumps(line) for line in lines) + "\n", encoding="utf-8")

    state = evaluate_early_stopping(
        EarlyStoppingConfig(
            enabled=True,
            metric="val/loss",
            mode="min",
            patience=2,
            min_delta=0.0,
        ),
        history_path,
    )

    assert state.supported is True
    assert state.triggered is True
    assert state.stopped_early is True
    assert state.best_metric_value == 1.0
    assert state.best_metric_step == 1
    assert state.bad_epochs == 2


def test_evaluate_early_stopping_ignores_missing_metric(tmp_path: Path) -> None:
    history_path = tmp_path / "metrics_history.jsonl"
    history_path.write_text("", encoding="utf-8")

    state = evaluate_early_stopping(
        EarlyStoppingConfig(
            enabled=True,
            metric="",
            mode="min",
            patience=1,
            min_delta=0.0,
        ),
        history_path,
    )

    assert state.enabled is True
    assert state.supported is False
    assert state.triggered is False
