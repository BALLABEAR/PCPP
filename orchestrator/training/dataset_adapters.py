from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

import h5py
import numpy as np

from orchestrator.training.presets import TrainingPreset, to_container_path, to_workspace_relative


IGNORED_DIRECTORY_NAMES = {
    "__pycache__",
}

COMPAT_COMPLETION_TAXONOMY_IDS = (
    "02691156",
    "02747177",
    "02773838",
    "02801938",
    "02808440",
    "02818832",
    "02828884",
    "02843684",
    "02871439",
    "02876657",
    "02880940",
    "02924116",
    "02933112",
    "02942699",
    "02946921",
    "02954340",
    "02958343",
    "02992529",
    "03001627",
    "03046257",
    "03085013",
    "03207941",
    "03211117",
    "03261776",
    "03325088",
    "03337140",
    "03467517",
    "03513137",
    "03593526",
    "03624134",
    "03636649",
    "03642806",
    "03691459",
    "03710193",
    "03759954",
    "03761084",
    "03790512",
    "03797390",
    "03928116",
    "03938244",
    "03948459",
    "03991062",
    "04004475",
    "04074963",
    "04090263",
    "04099429",
    "04225987",
    "04256520",
    "04330267",
    "04379243",
    "04401088",
    "04460130",
    "04468005",
    "04530566",
    "04554684",
)


@dataclass(frozen=True)
class SplitPercentages:
    train: int
    val: int
    test: int

    def __post_init__(self) -> None:
        total = self.train + self.val + self.test
        if total != 100:
            raise ValueError("Split percentages must sum to 100.")
        for label, value in (("train", self.train), ("val", self.val), ("test", self.test)):
            if value < 0:
                raise ValueError(f"Split percentage '{label}' must be non-negative.")


@dataclass(frozen=True)
class DatasetRecord:
    taxonomy_id: str
    taxonomy_name: str
    target_id: str
    target_path: Path
    partial_paths: tuple[Path, ...]


@dataclass(frozen=True)
class ResolvedDataset:
    target_root: Path
    training_data_root: Path
    split_percentages: SplitPercentages
    records: tuple[DatasetRecord, ...]
    split_map: dict[str, str]
    split_counts: dict[str, int]


@dataclass(frozen=True)
class PreparedDatasetArtifacts:
    adapter_id: str
    adapter_name: str
    dataset_root: Path
    category_file_path: Path
    partial_points_path_template: str
    complete_points_path_template: str
    split_counts: dict[str, int]
    sample_counts: dict[str, int]


class TrainingDatasetAdapter(Protocol):
    adapter_id: str

    def resolve_dataset(
        self,
        *,
        target_root: Path,
        training_data_root: Path,
        split_percentages: SplitPercentages,
    ) -> ResolvedDataset:
        ...

    def prepare_artifacts(
        self,
        *,
        preset: TrainingPreset,
        dataset: ResolvedDataset,
        run_dir: Path,
        geometry_normalization: bool,
    ) -> PreparedDatasetArtifacts:
        ...

    def patch_config(
        self,
        *,
        payload: dict[str, Any],
        preset: TrainingPreset,
        dataset_artifacts: PreparedDatasetArtifacts,
        checkpoint_path: Path | None,
        artifacts_dir: Path,
        use_gpu: bool,
        mode_settings: dict[str, Any],
    ) -> dict[str, Any]:
        ...


class Completion3DH5Adapter:
    adapter_id = "completion3d_h5_v1"

    def resolve_dataset(
        self,
        *,
        target_root: Path,
        training_data_root: Path,
        split_percentages: SplitPercentages,
    ) -> ResolvedDataset:
        records = _index_dataset(target_root=target_root, training_data_root=training_data_root)
        split_map = _assign_splits(records=records, split_percentages=split_percentages)
        split_counts = {"train": 0, "val": 0, "test": 0}
        for split in split_map.values():
            split_counts[split] += 1
        return ResolvedDataset(
            target_root=target_root,
            training_data_root=training_data_root,
            split_percentages=split_percentages,
            records=records,
            split_map=split_map,
            split_counts=split_counts,
        )

    def prepare_artifacts(
        self,
        *,
        preset: TrainingPreset,
        dataset: ResolvedDataset,
        run_dir: Path,
        geometry_normalization: bool,
    ) -> PreparedDatasetArtifacts:
        dataset_root = run_dir / "adapter_dataset"
        category_file_path = dataset_root / "Completion3D.json"
        taxonomy_id_map = _build_compat_taxonomy_map(dataset.records)
        taxonomy_payload: dict[str, dict[str, Any]] = {}
        split_sample_counts = {"train": 0, "val": 0, "test": 0}

        for record in dataset.records:
            compat_taxonomy_id = taxonomy_id_map[record.taxonomy_id]
            taxonomy = taxonomy_payload.setdefault(
                compat_taxonomy_id,
                {
                    "taxonomy_id": compat_taxonomy_id,
                    "taxonomy_name": record.taxonomy_name,
                    "train": [],
                    "val": [],
                    "test": [],
                },
            )
            split = dataset.split_map[_record_key(record)]
            gt_points = _read_ascii_ply_points(record.target_path)
            if geometry_normalization:
                centroid, scale = _compute_normalization_from_target(gt_points)
                gt_points = _apply_normalization(gt_points, centroid, scale)

            for partial_idx, partial_path in enumerate(record.partial_paths):
                sample_id = f"{record.target_id}__partial_{partial_idx:03d}"
                partial_points = _read_ascii_ply_points(partial_path)
                if geometry_normalization:
                    partial_points = _apply_normalization(partial_points, centroid, scale)
                partial_out = dataset_root / split / "partial" / compat_taxonomy_id / f"{sample_id}.h5"
                gt_out = dataset_root / split / "gt" / compat_taxonomy_id / f"{sample_id}.h5"
                _write_h5_points(partial_out, partial_points)
                _write_h5_points(gt_out, gt_points)
                taxonomy[split].append(sample_id)
                split_sample_counts[split] += 1

        payload = [taxonomy_payload[key] for key in sorted(taxonomy_payload)]
        category_file_path.parent.mkdir(parents=True, exist_ok=True)
        category_file_path.write_text(json.dumps(payload, indent=2, ensure_ascii=True), encoding="utf-8")

        return PreparedDatasetArtifacts(
            adapter_id=self.adapter_id,
            adapter_name=self.adapter_id,
            dataset_root=dataset_root,
            category_file_path=category_file_path,
            partial_points_path_template="{dataset_root}/%s/partial/%s/%s.h5",
            complete_points_path_template="{dataset_root}/%s/gt/%s/%s.h5",
            split_counts=dict(dataset.split_counts),
            sample_counts=split_sample_counts,
        )

    def patch_config(
        self,
        *,
        payload: dict[str, Any],
        preset: TrainingPreset,
        dataset_artifacts: PreparedDatasetArtifacts,
        checkpoint_path: Path | None,
        artifacts_dir: Path,
        use_gpu: bool,
        mode_settings: dict[str, Any],
    ) -> dict[str, Any]:
        dataset_cfg = payload.setdefault("dataset", {})
        train_cfg = payload.setdefault("train", {})
        test_cfg = payload.setdefault("test", {})
        container_dataset_root = to_container_path(dataset_artifacts.dataset_root)

        dataset_cfg["category_file_path"] = to_container_path(dataset_artifacts.category_file_path)
        dataset_cfg["partial_points_path"] = dataset_artifacts.partial_points_path_template.format(dataset_root=container_dataset_root)
        dataset_cfg["complete_points_path"] = dataset_artifacts.complete_points_path_template.format(dataset_root=container_dataset_root)
        train_cfg["out_path"] = to_container_path(artifacts_dir)
        train_cfg["resume"] = bool(mode_settings.get("resume", False))
        train_cfg["model_path"] = to_container_path(checkpoint_path) if checkpoint_path else ""
        test_cfg["model_path"] = to_container_path(checkpoint_path) if checkpoint_path else ""
        if use_gpu:
            train_cfg["gpu"] = [0]
            test_cfg["gpu"] = [0]
        else:
            train_cfg["gpu"] = []
            test_cfg["gpu"] = []
        return payload


ADAPTERS: dict[str, TrainingDatasetAdapter] = {
    Completion3DH5Adapter.adapter_id: Completion3DH5Adapter(),
}


def get_training_adapter(adapter_id: str) -> TrainingDatasetAdapter:
    adapter = ADAPTERS.get(str(adapter_id or "").strip())
    if adapter is None:
        raise ValueError(f"Unknown training adapter: {adapter_id}")
    return adapter


def _build_compat_taxonomy_map(records: tuple[DatasetRecord, ...]) -> dict[str, str]:
    taxonomy_names = sorted({record.taxonomy_id for record in records})
    if len(taxonomy_names) > len(COMPAT_COMPLETION_TAXONOMY_IDS):
        raise ValueError("Too many taxonomy classes for adapter compatibility mapping.")
    return {
        taxonomy_name: COMPAT_COMPLETION_TAXONOMY_IDS[idx]
        for idx, taxonomy_name in enumerate(taxonomy_names)
    }


def _index_dataset(*, target_root: Path, training_data_root: Path) -> tuple[DatasetRecord, ...]:
    if not target_root.exists():
        raise ValueError(f"Target path not found: {target_root}")
    if not training_data_root.exists():
        raise ValueError(f"Training data path not found: {training_data_root}")
    if not target_root.is_dir():
        raise ValueError(f"Target path must be a directory: {target_root}")
    if not training_data_root.is_dir():
        raise ValueError(f"Training data path must be a directory: {training_data_root}")

    targets: dict[tuple[str, str], Path] = {}
    for class_dir in sorted(
        path for path in target_root.iterdir() if path.is_dir() and path.name not in IGNORED_DIRECTORY_NAMES
    ):
        ply_files = sorted(path for path in class_dir.glob("*.ply") if path.is_file())
        if not ply_files:
            raise ValueError(f"Target class folder is empty: {class_dir}")
        for ply_path in ply_files:
            key = (class_dir.name, ply_path.stem)
            targets[key] = ply_path

    if not targets:
        raise ValueError(f"No target .ply files found under: {target_root}")

    partials: dict[tuple[str, str], tuple[Path, ...]] = {}
    for class_dir in sorted(
        path for path in training_data_root.iterdir() if path.is_dir() and path.name not in IGNORED_DIRECTORY_NAMES
    ):
        target_dirs = sorted(path for path in class_dir.iterdir() if path.is_dir() and path.name not in IGNORED_DIRECTORY_NAMES)
        if not target_dirs:
            raise ValueError(f"Training class folder is empty: {class_dir}")
        for target_dir in target_dirs:
            partial_files = sorted(path for path in target_dir.glob("partial_*.ply") if path.is_file())
            if not partial_files:
                raise ValueError(f"No partial_*.ply files found under: {target_dir}")
            partials[(class_dir.name, target_dir.name)] = tuple(partial_files)

    if not partials:
        raise ValueError(f"No partial point clouds found under: {training_data_root}")

    missing_partials = sorted(key for key in targets if key not in partials)
    if missing_partials:
        preview = ", ".join(f"{cls}/{target}" for cls, target in missing_partials[:5])
        raise ValueError(f"Targets without training partials: {preview}")

    orphan_partials = sorted(key for key in partials if key not in targets)
    if orphan_partials:
        preview = ", ".join(f"{cls}/{target}" for cls, target in orphan_partials[:5])
        raise ValueError(f"Training partials without matching target: {preview}")

    records: list[DatasetRecord] = []
    for (taxonomy_id, target_id), target_path in sorted(targets.items()):
        records.append(
            DatasetRecord(
                taxonomy_id=taxonomy_id,
                taxonomy_name=taxonomy_id,
                target_id=target_id,
                target_path=target_path,
                partial_paths=partials[(taxonomy_id, target_id)],
            )
        )
    return tuple(records)


def _assign_splits(
    *,
    records: tuple[DatasetRecord, ...],
    split_percentages: SplitPercentages,
) -> dict[str, str]:
    by_taxonomy: dict[str, list[DatasetRecord]] = {}
    for record in records:
        by_taxonomy.setdefault(record.taxonomy_id, []).append(record)

    split_map: dict[str, str] = {}
    for taxonomy_id, items in by_taxonomy.items():
        ordered = sorted(items, key=lambda item: _stable_sort_key(f"{taxonomy_id}/{item.target_id}"))
        counts = _calculate_split_counts(len(ordered), split_percentages)
        cursor = 0
        for split in ("train", "val", "test"):
            next_cursor = cursor + counts[split]
            for record in ordered[cursor:next_cursor]:
                split_map[_record_key(record)] = split
            cursor = next_cursor
    return split_map


def _calculate_split_counts(total: int, split_percentages: SplitPercentages) -> dict[str, int]:
    requested = {
        "train": split_percentages.train,
        "val": split_percentages.val,
        "test": split_percentages.test,
    }
    positive_splits = [key for key, value in requested.items() if value > 0]
    if total < len(positive_splits):
        raise ValueError(
            f"Not enough target objects to satisfy requested train/val/test split. "
            f"Need at least {len(positive_splits)} targets per class, got {total}."
        )

    counts = {key: 0 for key in requested}
    for key in positive_splits:
        counts[key] = 1

    remaining = total - len(positive_splits)
    if remaining <= 0:
        return counts

    ideals = {key: (requested[key] / 100.0) * total for key in requested}
    fractions = sorted(
        requested,
        key=lambda key: (ideals[key] - counts[key], requested[key], key),
        reverse=True,
    )

    while remaining > 0:
        for key in fractions:
            if requested[key] == 0:
                continue
            counts[key] += 1
            remaining -= 1
            if remaining == 0:
                break
    return counts


def _stable_sort_key(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _record_key(record: DatasetRecord) -> str:
    return f"{record.taxonomy_id}/{record.target_id}"


def _read_ascii_ply_points(path: Path) -> np.ndarray:
    lines = path.read_text(encoding="utf-8").splitlines()
    if not lines or lines[0].strip() != "ply":
        raise ValueError(f"Unsupported PLY header in file: {path}")

    vertex_count = None
    header_end = None
    for idx, raw in enumerate(lines[1:], start=1):
        line = raw.strip()
        if line.startswith("format ") and line != "format ascii 1.0":
            raise ValueError(f"Only ASCII PLY is supported: {path}")
        if line.startswith("element vertex "):
            vertex_count = int(line.split()[-1])
        if line == "end_header":
            header_end = idx
            break

    if vertex_count is None or header_end is None:
        raise ValueError(f"Invalid PLY header in file: {path}")

    points: list[list[float]] = []
    for raw in lines[header_end + 1 : header_end + 1 + vertex_count]:
        parts = raw.split()
        if len(parts) < 3:
            continue
        points.append([float(parts[0]), float(parts[1]), float(parts[2])])

    if len(points) != vertex_count:
        raise ValueError(f"PLY vertex count mismatch in file: {path}")
    return np.asarray(points, dtype=np.float32)


def _write_h5_points(path: Path, points: np.ndarray) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with h5py.File(path, "w") as handle:
        handle.create_dataset("data", data=np.asarray(points, dtype=np.float32))


def _compute_normalization_from_target(points: np.ndarray) -> tuple[np.ndarray, float]:
    centroid = np.mean(points, axis=0, dtype=np.float32)
    centered = points - centroid
    scale = float(np.max(np.abs(centered))) if centered.size else 1.0
    if scale <= 1e-8:
        scale = 1.0
    return centroid.astype(np.float32), scale


def _apply_normalization(points: np.ndarray, centroid: np.ndarray, scale: float) -> np.ndarray:
    return ((points - centroid) / scale).astype(np.float32)
