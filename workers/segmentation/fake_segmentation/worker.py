import argparse
import logging
import shutil
from pathlib import Path

from workers.base.base_worker import BaseWorker

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s - %(message)s")
logger = logging.getLogger(__name__)


class FakeSegmentationWorker(BaseWorker):
    """
    Lightweight segmentation stub for Stage 4 DAG.
    For XYZ/TXT files it keeps every second valid XYZ row.
    For unknown formats it falls back to byte copy.
    """

    def __init__(self) -> None:
        super().__init__(model_id="fake_segmentation_worker")

    def process(self, input_path: Path, output_dir: Path) -> Path:
        suffix = input_path.suffix.lower()
        output_path = output_dir / f"{input_path.stem}_segmented{suffix or '.txt'}"

        if suffix in {".xyz", ".txt", ".pts"}:
            rows = _read_xyz_rows(input_path)
            if len(rows) >= 2:
                kept_rows = rows[::2]
                output_path.write_text(
                    "".join(f"{x:.6f} {y:.6f} {z:.6f}\n" for x, y, z in kept_rows),
                    encoding="utf-8",
                )
                logger.info(
                    "Fake segmentation reduced points %s -> %s (%s)",
                    len(rows),
                    len(kept_rows),
                    output_path,
                )
                return output_path

        shutil.copy2(input_path, output_path)
        logger.info("Fake segmentation fallback copy produced file: %s", output_path)
        return output_path


def _read_xyz_rows(path: Path) -> list[tuple[float, float, float]]:
    rows: list[tuple[float, float, float]] = []
    for line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
        parts = line.strip().split()
        if len(parts) < 3:
            continue
        try:
            x, y, z = float(parts[0]), float(parts[1]), float(parts[2])
        except ValueError:
            continue
        rows.append((x, y, z))
    return rows


def main() -> None:
    parser = argparse.ArgumentParser(description="PCPP fake segmentation worker")
    parser.add_argument("--input", required=True, help="Input file path")
    parser.add_argument("--output-dir", required=True, help="Output directory")
    args = parser.parse_args()

    worker = FakeSegmentationWorker()
    result = worker.run(input_path=args.input, output_dir=args.output_dir)
    print(result)


if __name__ == "__main__":
    main()
