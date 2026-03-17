import logging
from pathlib import Path


logger = logging.getLogger(__name__)


class BaseWorker:
    """
    Универсальный минимальный контракт воркера.
    Любая модель должна реализовать только метод process().
    """

    def __init__(self, model_id: str):
        self.model_id = model_id

    def run(self, input_path: str, output_dir: str) -> str:
        source = Path(input_path)
        if not source.exists():
            raise FileNotFoundError(f"Input file not found: {source}")

        target_dir = Path(output_dir)
        target_dir.mkdir(parents=True, exist_ok=True)

        logger.info("Worker %s started. input=%s", self.model_id, source)
        output_path = self.process(source, target_dir)
        logger.info("Worker %s finished. output=%s", self.model_id, output_path)
        return str(output_path)

    def process(self, input_path: Path, output_dir: Path) -> Path:
        raise NotImplementedError("Worker must implement process()")

