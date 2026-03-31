import argparse
import logging
import shutil
import subprocess
from pathlib import Path

from workers.base.base_worker import BaseWorker

logger = logging.getLogger(__name__)


class CloudCompareMeshingWorker(BaseWorker):
    def __init__(self, cloudcompare_exe: str = "CloudCompare", strict_cli: bool = False) -> None:
        super().__init__(model_id="cloudcompare_meshing")
        self.cloudcompare_exe = cloudcompare_exe
        self.strict_cli = strict_cli

    def process(self, input_path: Path, output_dir: Path) -> Path:
        output_dir.mkdir(parents=True, exist_ok=True)
        output_path = output_dir / f"{input_path.stem}_cloudcompare.ply"
        executable = shutil.which(self.cloudcompare_exe) or self.cloudcompare_exe
        command = [
            executable,
            "-SILENT",
            "-NO_TIMESTAMP",
            "-AUTO_SAVE",
            "OFF",
            "-O",
            str(input_path),
            "-C_EXPORT_FMT",
            "PLY",
            "-SAVE_CLOUDS",
            "FILE",
            str(output_path),
        ]
        try:
            subprocess.run(command, check=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        except FileNotFoundError:
            if self.strict_cli:
                raise RuntimeError(f"CloudCompare executable not found: {self.cloudcompare_exe}")
            logger.warning("CloudCompare executable not found; using passthrough fallback for %s", input_path)
            output_path.write_bytes(input_path.read_bytes())
        except subprocess.CalledProcessError as exc:
            if self.strict_cli:
                raise RuntimeError(f"CloudCompare failed: {exc.stdout}") from exc
            logger.warning("CloudCompare failed; using passthrough fallback. Error: %s", exc.stdout)
            output_path.write_bytes(input_path.read_bytes())
        return output_path


def main() -> None:
    parser = argparse.ArgumentParser(description="CloudCompare meshing adapter")
    parser.add_argument("--input", required=True)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--cloudcompare-exe", default="CloudCompare")
    parser.add_argument("--strict-cli", action="store_true")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s - %(message)s")
    worker = CloudCompareMeshingWorker(cloudcompare_exe=args.cloudcompare_exe, strict_cli=args.strict_cli)
    result = worker.run(input_path=args.input, output_dir=args.output_dir)
    print(result)


if __name__ == "__main__":
    main()
