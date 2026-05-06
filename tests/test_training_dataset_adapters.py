import json
from pathlib import Path

import h5py
import numpy as np

from orchestrator.training.dataset_adapters import (
    SplitPercentages,
    prepare_dataset_artifacts,
    resolve_dataset,
)
from orchestrator.training.presets import load_training_preset


def _write_ascii_ply(path: Path, points: list[tuple[float, float, float]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        "ply",
        "format ascii 1.0",
        f"element vertex {len(points)}",
        "property float x",
        "property float y",
        "property float z",
        "end_header",
    ]
    lines.extend(f"{x} {y} {z}" for x, y, z in points)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _build_dataset_roots(tmp_path: Path) -> tuple[Path, Path]:
    target_root = tmp_path / "data" / "datasets" / "Full_Clouds"
    training_data_root = tmp_path / "data" / "datasets" / "Partial_Clouds"
    points = [(0.0, 0.0, 0.0), (1.0, 1.0, 1.0), (2.0, 2.0, 2.0)]
    for class_name, target_ids in {
        "lampposts": ["LampPosts_1", "LampPosts_2", "LampPosts_3"],
        "traffic signs": ["Signes_1", "Signes_2", "Signes_3"],
    }.items():
        for target_id in target_ids:
            _write_ascii_ply(target_root / class_name / f"{target_id}.ply", points)
            for partial_idx in range(2):
                _write_ascii_ply(
                    training_data_root / class_name / target_id / f"partial_{partial_idx:03d}.ply",
                    points[:2],
                )
    return target_root, training_data_root


def test_resolve_dataset_builds_deterministic_split_map(tmp_path: Path) -> None:
    target_root, training_data_root = _build_dataset_roots(tmp_path)
    split_percentages = SplitPercentages(train=80, val=10, test=10)

    first = resolve_dataset(
        target_root=target_root,
        training_data_root=training_data_root,
        split_percentages=split_percentages,
    )
    second = resolve_dataset(
        target_root=target_root,
        training_data_root=training_data_root,
        split_percentages=split_percentages,
    )

    assert first.split_map == second.split_map
    assert first.split_counts == {"train": 2, "val": 2, "test": 2}


def test_resolve_dataset_rejects_orphan_partials(tmp_path: Path) -> None:
    target_root, training_data_root = _build_dataset_roots(tmp_path)
    _write_ascii_ply(
        training_data_root / "lampposts" / "LampPosts_999" / "partial_000.ply",
        [(0.0, 0.0, 0.0)],
    )

    try:
        resolve_dataset(
            target_root=target_root,
            training_data_root=training_data_root,
            split_percentages=SplitPercentages(train=80, val=10, test=10),
        )
    except ValueError as exc:
        assert "without matching target" in str(exc)
    else:
        raise AssertionError("Expected orphan partial validation error")


def test_prepare_snowflake_adapter_writes_h5_and_category_file(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("WORKSPACE_ROOT", str(Path(__file__).resolve().parents[1]))
    target_root, training_data_root = _build_dataset_roots(tmp_path)
    preset = load_training_preset("snowflake_completion")
    dataset = resolve_dataset(
        target_root=target_root,
        training_data_root=training_data_root,
        split_percentages=SplitPercentages(train=80, val=10, test=10),
    )

    artifacts = prepare_dataset_artifacts(
        preset=preset,
        dataset=dataset,
        run_dir=tmp_path / "training_runs" / "snowflake" / "run123",
        geometry_normalization=False,
    )

    payload = json.loads(artifacts.category_file_path.read_text(encoding="utf-8"))
    assert payload
    first_sample = None
    for entry in payload:
        for split in ("train", "val", "test"):
            if entry[split]:
                first_sample = (split, entry["taxonomy_id"], entry[split][0])
                break
        if first_sample:
            break
    assert first_sample is not None

    split_name, taxonomy_id, sample_id = first_sample
    partial_path = artifacts.dataset_root / split_name / "partial" / taxonomy_id / f"{sample_id}.h5"
    gt_path = artifacts.dataset_root / split_name / "gt" / taxonomy_id / f"{sample_id}.h5"
    assert partial_path.exists()
    assert gt_path.exists()
    with h5py.File(partial_path, "r") as handle:
        assert handle["data"].shape == (2, 3)
    with h5py.File(gt_path, "r") as handle:
        assert handle["data"].shape == (3, 3)


def test_prepare_snowflake_adapter_normalizes_each_target_when_enabled(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("WORKSPACE_ROOT", str(Path(__file__).resolve().parents[1]))
    target_root = tmp_path / "data" / "datasets" / "Full_Clouds"
    training_data_root = tmp_path / "data" / "datasets" / "Partial_Clouds"
    base_target = [(0.0, 0.0, 0.0), (1.0, 2.0, 3.0), (2.0, 4.0, 6.0)]
    scaled_target = [(10.0, 20.0, 30.0), (12.0, 24.0, 36.0), (14.0, 28.0, 42.0)]
    _write_ascii_ply(target_root / "lampposts" / "LampPosts_1.ply", base_target)
    _write_ascii_ply(target_root / "lampposts" / "LampPosts_2.ply", scaled_target)
    _write_ascii_ply(training_data_root / "lampposts" / "LampPosts_1" / "partial_000.ply", base_target[:2])
    _write_ascii_ply(training_data_root / "lampposts" / "LampPosts_2" / "partial_000.ply", scaled_target[:2])

    preset = load_training_preset("snowflake_completion")
    dataset = resolve_dataset(
        target_root=target_root,
        training_data_root=training_data_root,
        split_percentages=SplitPercentages(train=100, val=0, test=0),
    )
    artifacts = prepare_dataset_artifacts(
        preset=preset,
        dataset=dataset,
        run_dir=tmp_path / "training_runs" / "snowflake" / "run124",
        geometry_normalization=True,
    )

    train_partial_dir = artifacts.dataset_root / "train" / "partial"
    train_gt_dir = artifacts.dataset_root / "train" / "gt"
    partial_files = sorted(train_partial_dir.rglob("*.h5"))
    gt_files = sorted(train_gt_dir.rglob("*.h5"))
    assert len(partial_files) == 2
    assert len(gt_files) == 2

    with h5py.File(partial_files[0], "r") as handle:
        first_partial = np.asarray(handle["data"], dtype=np.float32)
    with h5py.File(partial_files[1], "r") as handle:
        second_partial = np.asarray(handle["data"], dtype=np.float32)
    with h5py.File(gt_files[0], "r") as handle:
        first_gt = np.asarray(handle["data"], dtype=np.float32)
    with h5py.File(gt_files[1], "r") as handle:
        second_gt = np.asarray(handle["data"], dtype=np.float32)

    assert np.allclose(first_partial, second_partial, atol=1e-6)
    assert np.allclose(first_gt, second_gt, atol=1e-6)
