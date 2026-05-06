import json
from pathlib import Path
from typing import TypeAlias

from workers.base.point_cloud_io import load_points, save_points


SupportedCloudFile: TypeAlias = Path
NORMALIZATION_META_FILENAME = "point_cloud_normalization.json"


class FormatConverter:

    def supported_formats(self) -> set[str]:
        return {".ply", ".xyz", ".txt", ".pts", ".npy", ".pcd", ".las", ".laz"}

    def can_convert_format(self, source_suffix: str, target_suffix: str) -> bool:
        source = source_suffix.lower().strip()
        target = target_suffix.lower().strip()
        if not source.startswith("."):
            source = f".{source}"
        if not target.startswith("."):
            target = f".{target}"
        if source not in self.supported_formats() or target not in self.supported_formats():
            return False
        return True

    def convert(
        self,
        input_path: Path,
        target_suffix: str,
        work_dir: Path,
        *,
        geometry_normalization: bool = False,
    ) -> SupportedCloudFile:
        target = target_suffix.lower().strip()
        if not target.startswith("."):
            target = f".{target}"
        if target not in self.supported_formats():
            raise ValueError(f"Unsupported target format: {target}")
        normalized = self.normalize(
            input_path,
            work_dir,
            geometry_normalization=geometry_normalization,
        )
        if normalized.suffix.lower() == target:
            return normalized
        points = load_points(normalized)
        converted = work_dir / f"{input_path.stem}_converted{target}"
        save_points(converted, points)
        return converted

    def convert_model_output_to_point_cloud(
        self,
        output_path: Path,
        work_dir: Path,
        target_suffix: str = ".ply",
        source_context_dir: Path | None = None,
    ) -> SupportedCloudFile:
        target = target_suffix.lower().strip()
        if not target.startswith("."):
            target = f".{target}"
        if target not in self.supported_formats():
            raise ValueError(f"Unsupported target format: {target}")
        source = output_path.suffix.lower().strip()
        if source == target:
            return output_path
        if source != ".npy":
            return output_path
        work_dir.mkdir(parents=True, exist_ok=True)
        try:
            points = load_points(output_path)
        except ValueError as exc:
            raise ValueError(
                "Model produced .npy output with invalid point shape; expected Nx3 or Nx>=3 values."
            ) from exc
        if not points:
            raise ValueError("Model produced .npy output without any valid XYZ points.")
        metadata = self.load_normalization_metadata(source_context_dir) if source_context_dir else None
        if metadata:
            points = self.restore_points(points, metadata["centroid"], metadata["scale"])
        converted = work_dir / f"{output_path.stem}{target}"
        save_points(converted, points)
        return converted

    def normalize(
        self,
        input_path: Path,
        work_dir: Path,
        *,
        geometry_normalization: bool = False,
    ) -> SupportedCloudFile:
        suffix = input_path.suffix.lower()
        work_dir.mkdir(parents=True, exist_ok=True)

        if suffix in {".ply", ".xyz", ".txt", ".pts", ".npy"}:
            points = load_points(input_path)
            if not points:
                raise ValueError(f"Input file contains no valid XYZ points: {input_path}")
            return self._save_normalized_points(
                input_path=input_path,
                work_dir=work_dir,
                points=points,
                output_suffix=suffix,
                geometry_normalization=geometry_normalization,
            )

        if suffix in {".pcd"}:
            points = self._load_pcd_points(input_path)
            return self._save_normalized_points(
                input_path=input_path,
                work_dir=work_dir,
                points=points,
                output_suffix=".ply",
                geometry_normalization=geometry_normalization,
            )

        if suffix in {".las", ".laz"}:
            points = self._load_via_laspy(input_path)
            return self._save_normalized_points(
                input_path=input_path,
                work_dir=work_dir,
                points=points,
                output_suffix=".ply",
                geometry_normalization=geometry_normalization,
            )

        raise ValueError(
            f"Unsupported input format: {suffix}. Supported: .ply, .xyz, .txt, .pts, .npy, .pcd, .las, .laz"
        )

    def _load_pcd_points(self, input_path: Path) -> list[tuple[float, float, float]]:
        # Fast path for common ASCII PCD files to avoid heavy optional deps.
        points = self._load_ascii_pcd(input_path)
        if points:
            return points
        return self._load_via_open3d(input_path)

    def _load_ascii_pcd(self, input_path: Path) -> list[tuple[float, float, float]]:
        try:
            lines = input_path.read_text(encoding="utf-8", errors="ignore").splitlines()
        except OSError:
            return []
        data_idx = -1
        for idx, line in enumerate(lines):
            if line.strip().lower().startswith("data "):
                data_idx = idx
                if "ascii" not in line.lower():
                    return []
                break
        if data_idx < 0:
            return []
        points: list[tuple[float, float, float]] = []
        for line in lines[data_idx + 1 :]:
            parts = line.strip().split()
            if len(parts) < 3:
                continue
            try:
                points.append((float(parts[0]), float(parts[1]), float(parts[2])))
            except ValueError:
                continue
        return points

    def _load_via_open3d(self, input_path: Path) -> list[tuple[float, float, float]]:
        try:
            import open3d as o3d
        except Exception as exc:
            raise RuntimeError(
                "PCD conversion requires open3d. Install with: pip install open3d"
            ) from exc
        cloud = o3d.io.read_point_cloud(str(input_path))
        points = [(float(p[0]), float(p[1]), float(p[2])) for p in cloud.points]
        if not points:
            raise ValueError(f"Failed to read points from PCD: {input_path}")
        return points

    def _load_via_laspy(self, input_path: Path) -> list[tuple[float, float, float]]:
        try:
            import laspy
        except Exception as exc:
            raise RuntimeError(
                "LAS/LAZ conversion requires laspy. Install with: pip install laspy"
            ) from exc
        las = laspy.read(str(input_path))
        points = [(float(x), float(y), float(z)) for x, y, z in zip(las.x, las.y, las.z)]
        if not points:
            raise ValueError(f"Failed to read points from LAS/LAZ: {input_path}")
        return points

    def _save_normalized_points(
        self,
        *,
        input_path: Path,
        work_dir: Path,
        points: list[tuple[float, float, float]],
        output_suffix: str,
        geometry_normalization: bool,
    ) -> SupportedCloudFile:
        points_to_save = points
        metadata: dict[str, object] | None = None
        if geometry_normalization:
            points_to_save, centroid, scale = self._normalize_points_geometrically(points)
            metadata = {
                "centroid": [float(centroid[0]), float(centroid[1]), float(centroid[2])],
                "scale": float(scale),
            }
        normalized = work_dir / f"{input_path.stem}_normalized{output_suffix}"
        save_points(normalized, points_to_save)
        if metadata:
            self._write_normalization_metadata(work_dir, metadata)
        return normalized

    def load_normalization_metadata(self, search_dir: Path | None) -> dict[str, object] | None:
        if not search_dir or not search_dir.exists():
            return None
        meta_path = search_dir / NORMALIZATION_META_FILENAME
        if not meta_path.exists():
            return None
        try:
            payload = json.loads(meta_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None
        centroid = payload.get("centroid")
        scale = payload.get("scale")
        if (
            not isinstance(centroid, list)
            or len(centroid) != 3
            or not all(isinstance(item, (int, float)) for item in centroid)
            or not isinstance(scale, (int, float))
        ):
            return None
        return {
            "centroid": [float(centroid[0]), float(centroid[1]), float(centroid[2])],
            "scale": float(scale),
        }

    def restore_points(
        self,
        points: list[tuple[float, float, float]],
        centroid: list[float],
        scale: float,
    ) -> list[tuple[float, float, float]]:
        restored: list[tuple[float, float, float]] = []
        safe_scale = float(scale) if abs(float(scale)) > 1e-8 else 1.0
        for x, y, z in points:
            restored.append(
                (
                    float(x) * safe_scale + float(centroid[0]),
                    float(y) * safe_scale + float(centroid[1]),
                    float(z) * safe_scale + float(centroid[2]),
                )
            )
        return restored

    def _normalize_points_geometrically(
        self,
        points: list[tuple[float, float, float]],
    ) -> tuple[list[tuple[float, float, float]], list[float], float]:
        centroid = [
            sum(item[axis] for item in points) / len(points)
            for axis in range(3)
        ]
        centered = [
            (
                float(item[0]) - centroid[0],
                float(item[1]) - centroid[1],
                float(item[2]) - centroid[2],
            )
            for item in points
        ]
        scale = max(
            max(abs(x), abs(y), abs(z))
            for x, y, z in centered
        )
        if scale <= 1e-8:
            scale = 1.0
        normalized = [
            (x / scale, y / scale, z / scale)
            for x, y, z in centered
        ]
        return normalized, [float(centroid[0]), float(centroid[1]), float(centroid[2])], float(scale)

    def _write_normalization_metadata(self, work_dir: Path, payload: dict[str, object]) -> None:
        meta_path = work_dir / NORMALIZATION_META_FILENAME
        meta_path.write_text(json.dumps(payload, ensure_ascii=True, indent=2), encoding="utf-8")
