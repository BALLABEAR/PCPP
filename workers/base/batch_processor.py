from pathlib import Path

from workers.base.point_cloud_io import load_points, save_points


class BatchProcessor:
    """Point-cloud batching and merge utility for BaseWorker."""

    def count_points(self, input_path: Path) -> int:
        points = load_points(input_path)
        return len(points)

    def split_points(self, input_path: Path, max_points_per_batch: int, output_dir: Path) -> list[Path]:
        if max_points_per_batch <= 0:
            raise ValueError("max_points_per_batch must be > 0")
        points = load_points(input_path)
        if not points:
            raise ValueError("Cannot split empty point cloud")

        output_dir.mkdir(parents=True, exist_ok=True)
        suffix = input_path.suffix or ".xyz"
        batch_files: list[Path] = []
        start = 0
        total = len(points)
        while start < total:
            end = min(start + max_points_per_batch, total)
            batch_path = output_dir / f"{input_path.stem}_batch_{len(batch_files):04d}{suffix}"
            save_points(batch_path, points[start:end])
            batch_files.append(batch_path)
            start = end
        return batch_files

    def merge_outputs(self, batch_outputs: list[Path], merged_output: Path) -> Path:
        if not batch_outputs:
            raise ValueError("No batch outputs to merge")
        merged_points: list[tuple[float, float, float]] = []
        for item in batch_outputs:
            merged_points.extend(load_points(item))
        save_points(merged_output, merged_points)
        return merged_output
