from pathlib import Path
from typing import TypeAlias

from workers.base.point_cloud_io import load_points, save_points


SupportedCloudFile: TypeAlias = Path


class FormatConverter:
    """
    Converts various point-cloud inputs to supported worker-friendly files.
    Phase 1 supported input formats:
      .ply, .xyz, .txt, .pts, .npy, .pcd, .las, .laz
    """

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
        # All supported point-cloud formats can be loaded then re-saved to a target format.
        return True

    def convert(self, input_path: Path, target_suffix: str, work_dir: Path) -> SupportedCloudFile:
        target = target_suffix.lower().strip()
        if not target.startswith("."):
            target = f".{target}"
        if target not in self.supported_formats():
            raise ValueError(f"Unsupported target format: {target}")
        normalized = self.normalize(input_path, work_dir)
        if normalized.suffix.lower() == target:
            return normalized
        points = load_points(normalized)
        converted = work_dir / f"{input_path.stem}_converted{target}"
        save_points(converted, points)
        return converted

    def convert_model_output_to_point_cloud(self, output_path: Path, work_dir: Path, target_suffix: str = ".ply") -> SupportedCloudFile:
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
        converted = work_dir / f"{output_path.stem}{target}"
        save_points(converted, points)
        return converted

    def normalize(self, input_path: Path, work_dir: Path) -> SupportedCloudFile:
        suffix = input_path.suffix.lower()
        work_dir.mkdir(parents=True, exist_ok=True)

        if suffix in {".ply", ".xyz", ".txt", ".pts", ".npy"}:
            # Already supported by internal parser.
            points = load_points(input_path)
            if not points:
                raise ValueError(f"Input file contains no valid XYZ points: {input_path}")
            normalized = work_dir / f"{input_path.stem}_normalized{suffix}"
            save_points(normalized, points)
            return normalized

        if suffix in {".pcd"}:
            points = self._load_pcd_points(input_path)
            normalized = work_dir / f"{input_path.stem}_normalized.ply"
            save_points(normalized, points)
            return normalized

        if suffix in {".las", ".laz"}:
            points = self._load_via_laspy(input_path)
            normalized = work_dir / f"{input_path.stem}_normalized.ply"
            save_points(normalized, points)
            return normalized

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
