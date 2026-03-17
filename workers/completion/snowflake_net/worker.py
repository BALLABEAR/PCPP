import argparse
import logging
from pathlib import Path

from workers.base.base_worker import BaseWorker

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s - %(message)s")
logger = logging.getLogger(__name__)


class SnowflakeWorker(BaseWorker):
    """
    Каркас completion-воркера для SnowflakeNet.
    Сейчас работает как безопасный stub: копирует вход в выход.
    Реальную логику инференса замените в process().
    """

    def __init__(self) -> None:
        super().__init__(model_id="snowflake_net")

    def process(self, input_path: Path, output_dir: Path) -> Path:
        output_path = output_dir / f"{input_path.stem}_completed{input_path.suffix or '.ply'}"

        # Stage-3 scaffold: здесь позже подключается реальный инференс SnowflakeNet.
        output_path.write_bytes(input_path.read_bytes())
        logger.info("Stub completion done: %s -> %s", input_path, output_path)
        return output_path


def main() -> None:
    parser = argparse.ArgumentParser(description="Snowflake completion worker scaffold")
    parser.add_argument("--input", required=True, help="Path to input point cloud")
    parser.add_argument("--output-dir", required=True, help="Directory for output file")
    args = parser.parse_args()

    worker = SnowflakeWorker()
    output = worker.run(input_path=args.input, output_dir=args.output_dir)
    print(output)


if __name__ == "__main__":
    main()

