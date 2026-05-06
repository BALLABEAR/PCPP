from pathlib import Path

from orchestrator.training.checkpoints import find_best_checkpoint


def test_find_best_checkpoint_prefers_best_pattern(tmp_path: Path) -> None:
    run_dir = tmp_path / "training_runs" / "snowflake" / "run123"
    best_path = run_dir / "artifacts" / "checkpoints" / "stamp" / "ckpt-best.pth"
    epoch_path = run_dir / "artifacts" / "checkpoints" / "stamp" / "ckpt-epoch-025.pth"
    best_path.parent.mkdir(parents=True, exist_ok=True)
    epoch_path.write_text("epoch", encoding="utf-8")
    best_path.write_text("best", encoding="utf-8")

    selected = find_best_checkpoint(run_dir, ["**/ckpt-best*.pth", "**/ckpt-epoch-*.pth"])

    assert selected == best_path
