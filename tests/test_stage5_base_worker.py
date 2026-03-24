"""
Предусловие:
    docker compose up -d --build

Запуск:
    pytest tests/test_stage5_base_worker.py -v
"""

from pathlib import Path

import pytest

from workers.base.base_worker import BaseWorker
from workers.base.point_cloud_io import load_points, save_points


class EchoWorker(BaseWorker):
    def __init__(self, model_card_path: str) -> None:
        super().__init__(model_id="echo_worker", model_card_path=model_card_path)

    def process(self, input_path: Path, output_dir: Path) -> Path:
        output_path = output_dir / f"{input_path.stem}_echo{input_path.suffix or '.xyz'}"
        output_path.write_bytes(input_path.read_bytes())
        return output_path


def _write_model_card(path: Path, batching_mode: str, max_points_per_batch: int | None) -> None:
    lines = [
        "id: echo_worker",
        "name: EchoWorker",
        "task_type: completion",
        f"batching_mode: {batching_mode}",
    ]
    if max_points_per_batch is not None:
        lines.append(f"max_points_per_batch: {max_points_per_batch}")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def test_stage5_auto_batching_merges_outputs(tmp_path: Path) -> None:
    model_card = tmp_path / "model_card.yaml"
    _write_model_card(model_card, batching_mode="auto", max_points_per_batch=2)

    input_xyz = tmp_path / "input.xyz"
    points = [
        (0.0, 0.0, 0.0),
        (1.0, 1.0, 1.0),
        (2.0, 2.0, 2.0),
        (3.0, 3.0, 3.0),
        (4.0, 4.0, 4.0),
    ]
    save_points(input_xyz, points)

    worker = EchoWorker(model_card_path=str(model_card))
    output = Path(worker.run(str(input_xyz), str(tmp_path / "out")))
    output_points = load_points(output)
    assert output.exists()
    assert len(output_points) == 5


def test_stage5_disabled_batching_raises_clear_error(tmp_path: Path) -> None:
    model_card = tmp_path / "model_card.yaml"
    _write_model_card(model_card, batching_mode="disabled", max_points_per_batch=2)

    input_xyz = tmp_path / "input.xyz"
    save_points(
        input_xyz,
        [(0.0, 0.0, 0.0), (1.0, 1.0, 1.0), (2.0, 2.0, 2.0)],
    )

    worker = EchoWorker(model_card_path=str(model_card))
    with pytest.raises(ValueError, match="batching_mode=disabled"):
        worker.run(str(input_xyz), str(tmp_path / "out"))


def test_stage5_format_validation_rejects_unknown_extension(tmp_path: Path) -> None:
    model_card = tmp_path / "model_card.yaml"
    _write_model_card(model_card, batching_mode="auto", max_points_per_batch=64)

    invalid = tmp_path / "input.bin"
    invalid.write_bytes(b"\x00\x01")
    worker = EchoWorker(model_card_path=str(model_card))
    with pytest.raises(ValueError, match="Unsupported input format"):
        worker.run(str(invalid), str(tmp_path / "out"))
