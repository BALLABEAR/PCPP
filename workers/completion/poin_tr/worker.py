import argparse
import shutil
from pathlib import Path

from workers.base.base_worker import BaseWorker


class PoinTrWorker(BaseWorker):
    """Auto-generated adapter template. Replace process() with real inference."""

    def __init__(self) -> None:
        super().__init__(model_id="poin_tr")

    def process(self, input_path: Path, output_dir: Path) -> Path:
        output_path = output_dir / f"{input_path.stem}_poin_tr{input_path.suffix or '.bin'}"
        shutil.copy2(input_path, output_path)
        return output_path


def main() -> None:
    parser = argparse.ArgumentParser(description="PCPP generated worker template")
    parser.add_argument("--input", required=True, help="Input file path")
    parser.add_argument("--output-dir", required=True, help="Output directory")
    args = parser.parse_args()

    worker = PoinTrWorker()
    result = worker.run(input_path=args.input, output_dir=args.output_dir)
    print(result)


if __name__ == "__main__":
    main()
