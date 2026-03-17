import argparse
import logging
import time
from pathlib import Path

from workers.base.base_worker import BaseWorker

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s - %(message)s")
logger = logging.getLogger(__name__)


class SleepWorker(BaseWorker):
    """Fake worker for onboarding: sleeps and copies input to output."""

    def __init__(self) -> None:
        super().__init__(model_id="sleep_worker")

    def process(self, input_path: Path, output_dir: Path) -> Path:
        time.sleep(5)
        output_path = output_dir / f"{input_path.stem}_sleep{input_path.suffix or '.txt'}"
        output_path.write_bytes(input_path.read_bytes())
        logger.info("Sleep worker produced file: %s", output_path)
        return output_path


def main() -> None:
    parser = argparse.ArgumentParser(description="Fake sleep worker")
    parser.add_argument("--input", required=True, help="Input file path")
    parser.add_argument("--output-dir", required=True, help="Output directory")
    args = parser.parse_args()

    worker = SleepWorker()
    result = worker.run(args.input, args.output_dir)
    print(result)


if __name__ == "__main__":
    main()

