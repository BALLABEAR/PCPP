from pathlib import Path
from typing import Iterable


PointRows = list[tuple[float, float, float]]


def load_points(path: Path) -> PointRows:
    suffix = path.suffix.lower()
    if suffix in {".xyz", ".txt", ".pts"}:
        return _load_xyz_like(path)
    if suffix == ".npy":
        return _load_npy(path)
    if suffix == ".ply":
        return _load_ply_ascii(path)
    raise ValueError(f"Unsupported point cloud format for loading: {suffix}")


def save_points(path: Path, points: Iterable[tuple[float, float, float]]) -> Path:
    suffix = path.suffix.lower()
    path.parent.mkdir(parents=True, exist_ok=True)
    normalized = _normalize_points(points)
    if suffix in {".xyz", ".txt", ".pts"}:
        path.write_text(
            "".join(f"{x:.6f} {y:.6f} {z:.6f}\n" for x, y, z in normalized),
            encoding="utf-8",
        )
        return path
    if suffix == ".ply":
        _save_ply_ascii(path, normalized)
        return path
    if suffix == ".npy":
        _save_npy(path, normalized)
        return path
    raise ValueError(f"Unsupported point cloud format for saving: {suffix}")


def _load_xyz_like(path: Path) -> PointRows:
    rows: list[tuple[float, float, float]] = []
    for line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
        parts = line.strip().split()
        if len(parts) < 3:
            continue
        try:
            rows.append((float(parts[0]), float(parts[1]), float(parts[2])))
        except ValueError:
            continue
    return rows


def _load_ply_ascii(path: Path) -> PointRows:
    lines = path.read_text(encoding="utf-8", errors="ignore").splitlines()
    if not lines or lines[0].strip().lower() != "ply":
        raise ValueError(f"Invalid PLY header in {path}")
    vertex_count = None
    data_start = None
    for idx, line in enumerate(lines):
        stripped = line.strip().lower()
        if stripped.startswith("element vertex"):
            parts = stripped.split()
            if len(parts) == 3:
                vertex_count = int(parts[2])
        if stripped == "end_header":
            data_start = idx + 1
            break
    if data_start is None or vertex_count is None:
        raise ValueError(f"PLY header is missing required fields in {path}")

    rows: list[tuple[float, float, float]] = []
    for line in lines[data_start : data_start + vertex_count]:
        parts = line.strip().split()
        if len(parts) < 3:
            continue
        try:
            rows.append((float(parts[0]), float(parts[1]), float(parts[2])))
        except ValueError:
            continue
    return rows


def _save_ply_ascii(path: Path, points: PointRows) -> None:
    header = [
        "ply",
        "format ascii 1.0",
        f"element vertex {len(points)}",
        "property float x",
        "property float y",
        "property float z",
        "end_header",
    ]
    body = [f"{x:.6f} {y:.6f} {z:.6f}" for x, y, z in points]
    path.write_text("\n".join(header + body) + "\n", encoding="utf-8")


def _normalize_points(points: Iterable[tuple[float, float, float]]) -> PointRows:
    result: PointRows = []
    for item in points:
        if len(item) < 3:
            continue
        result.append((float(item[0]), float(item[1]), float(item[2])))
    return result


def _load_npy(path: Path) -> PointRows:
    try:
        import numpy as np
    except Exception as exc:
        raise RuntimeError("Reading .npy point clouds requires numpy") from exc
    points = np.load(str(path))
    if points.ndim == 1:
        points = points.reshape(-1, 3)
    if points.shape[1] > 3:
        points = points[:, :3]
    if points.shape[1] != 3:
        raise ValueError(f"Expected XYZ points in npy, got {points.shape}")
    return [(float(row[0]), float(row[1]), float(row[2])) for row in points]


def _save_npy(path: Path, points: PointRows) -> None:
    try:
        import numpy as np
    except Exception as exc:
        raise RuntimeError("Writing .npy point clouds requires numpy") from exc
    np.save(path, np.asarray(points, dtype=np.float32))
