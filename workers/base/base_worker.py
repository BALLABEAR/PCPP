import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from workers.base.batch_processor import BatchProcessor
from workers.base.format_converter import FormatConverter, SupportedCloudFile


logger = logging.getLogger(__name__)


MAX_POINTS_LIMIT = 2_000_000


@dataclass
class WorkerRuntimeConfig:
    task_type: str = "unknown"
    batching_mode: str = "auto"
    max_points_per_batch: int | None = None
    accepted_input_formats: list[str] | None = None


class BaseWorker:
    """
    Универсальный минимальный контракт воркера.
    Любая модель должна реализовать только метод process().
    На этапе 5 добавлены:
    - валидация входного файла
    - конвертация в поддерживаемый формат
    - батчинг по model_card.yaml
    """

    def __init__(self, model_id: str, model_card_path: str | None = None):
        self.model_id = model_id
        self.model_card_path = Path(model_card_path).resolve() if model_card_path else self._infer_model_card_path()
        self._runtime = self._load_runtime_config()
        self._converter = FormatConverter()
        self._batch_processor = BatchProcessor()

    def run(self, input_path: str, output_dir: str) -> str:
        source = Path(input_path)
        if not source.exists():
            raise FileNotFoundError(f"Input file not found: {source}")

        target_dir = Path(output_dir)
        target_dir.mkdir(parents=True, exist_ok=True)

        logger.info("Worker %s started. input=%s", self.model_id, source)
        if not self._is_point_cloud_task():
            output_path = self.process(source, target_dir)
            logger.info("Worker %s finished. output=%s", self.model_id, output_path)
            return str(output_path)

        accepted = {item.lower() for item in (self._runtime.accepted_input_formats or []) if item}
        if source.suffix.lower() in accepted:
            normalized = source
        else:
            normalized = self._converter.normalize(source, target_dir / "_normalized")
        try:
            self._validate_points_limit(normalized)
            output_path = self._run_with_batching(normalized, target_dir)
        except ValueError as exc:
            if "Unsupported point cloud format for loading" in str(exc):
                logger.warning(
                    "Worker %s: skipping base point-count/batching checks for unsupported format %s",
                    self.model_id,
                    normalized.suffix.lower(),
                )
                output_path = self.process(normalized, target_dir)
            else:
                raise
        output_path = self._normalize_point_cloud_output(Path(output_path), target_dir)
        logger.info("Worker %s finished. output=%s", self.model_id, output_path)
        return str(output_path)

    def process(self, input_path: Path, output_dir: Path) -> Path:
        raise NotImplementedError("Worker must implement process()")

    def _infer_model_card_path(self) -> Path | None:
        module_file = Path(__import__(self.__class__.__module__, fromlist=["__file__"]).__file__).resolve()
        candidate = module_file.parent / "model_card.yaml"
        return candidate if candidate.exists() else None

    def _load_runtime_config(self) -> WorkerRuntimeConfig:
        if not self.model_card_path or not self.model_card_path.exists():
            return WorkerRuntimeConfig()
        try:
            payload: dict[str, Any] = _load_yaml_like(self.model_card_path)
        except Exception as exc:
            logger.warning("Failed to read model card for %s: %s", self.model_id, exc)
            return WorkerRuntimeConfig()

        mode = str(payload.get("batching_mode", "auto")).strip().lower() or "auto"
        task_type = str(payload.get("task_type", "unknown")).strip().lower() or "unknown"
        max_points_raw = payload.get("max_points_per_batch")
        max_points: int | None = None
        if isinstance(max_points_raw, int) and max_points_raw > 0:
            max_points = max_points_raw
        accepted_raw = payload.get("accepted_input_formats") or payload.get("input_format") or []
        accepted_input_formats: list[str] = []
        if isinstance(accepted_raw, str):
            accepted_input_formats = [item.strip() for item in accepted_raw.split(",") if item.strip()]
        elif isinstance(accepted_raw, list):
            accepted_input_formats = [str(item).strip() for item in accepted_raw if str(item).strip()]
        return WorkerRuntimeConfig(
            task_type=task_type,
            batching_mode=mode,
            max_points_per_batch=max_points,
            accepted_input_formats=accepted_input_formats,
        )

    def _is_point_cloud_task(self) -> bool:
        return self._runtime.task_type in {"segmentation", "completion", "meshing", "filtering", "preprocessing"}

    def _validate_points_limit(self, input_path: SupportedCloudFile) -> None:
        points = self._batch_processor.count_points(input_path)
        if points <= 0:
            raise ValueError("Input point cloud is empty or invalid: no XYZ points found.")
        if points > MAX_POINTS_LIMIT:
            raise ValueError(
                f"Input contains {points} points, which exceeds Phase 1 limit ({MAX_POINTS_LIMIT}). "
                "Use smaller input or add preprocessing/chunking from Phase 2."
            )

    def _run_with_batching(self, input_path: SupportedCloudFile, target_dir: Path) -> Path:
        mode = self._runtime.batching_mode
        max_points = self._runtime.max_points_per_batch
        total_points = self._batch_processor.count_points(input_path)

        if mode == "disabled" and max_points and total_points > max_points:
            raise ValueError(
                f"Model {self.model_id} is configured with batching_mode=disabled and max_points_per_batch={max_points}, "
                f"but input has {total_points} points. "
                "Enable batching_mode=auto/manual or reduce input size."
            )

        if mode == "manual" or not max_points or total_points <= max_points:
            return self.process(input_path, target_dir)

        if mode != "auto":
            logger.warning("Unknown batching_mode=%s for %s, fallback to single-pass.", mode, self.model_id)
            return self.process(input_path, target_dir)

        batch_dir = target_dir / "_batches"
        batch_dir.mkdir(parents=True, exist_ok=True)
        batch_inputs = self._batch_processor.split_points(input_path, max_points, batch_dir)
        logger.info(
            "Worker %s auto-batching enabled: %s points -> %s batches (size=%s)",
            self.model_id,
            total_points,
            len(batch_inputs),
            max_points,
        )
        batch_outputs: list[Path] = []
        per_batch_dir = target_dir / "_batch_out"
        per_batch_dir.mkdir(parents=True, exist_ok=True)
        for idx, batch_input in enumerate(batch_inputs, start=1):
            current_out_dir = per_batch_dir / f"batch_{idx:04d}"
            current_out_dir.mkdir(parents=True, exist_ok=True)
            batch_outputs.append(self.process(batch_input, current_out_dir))

        merged_suffix = batch_outputs[0].suffix or input_path.suffix or ".xyz"
        merged_output = target_dir / f"{input_path.stem}_{self.model_id}_merged{merged_suffix}"
        self._batch_processor.merge_outputs(batch_outputs, merged_output)
        return merged_output

    def _normalize_point_cloud_output(self, output_path: Path, target_dir: Path) -> Path:
        if output_path.suffix.lower() != ".npy":
            return output_path
        converted = self._converter.convert_model_output_to_point_cloud(
            output_path=output_path,
            work_dir=target_dir / "_normalized_output",
            target_suffix=".ply",
        )
        # Keep only point-cloud artifact to avoid downstream pick-up of stale .npy files.
        if Path(converted) != output_path and output_path.exists():
            try:
                output_path.unlink()
            except OSError:
                pass
        logger.info(
            "Worker %s converted model output %s -> %s",
            self.model_id,
            output_path.suffix.lower(),
            Path(converted).suffix.lower(),
        )
        return Path(converted)


def _load_yaml_like(path: Path) -> dict[str, Any]:
    text = path.read_text(encoding="utf-8")
    try:
        import yaml  # type: ignore

        return yaml.safe_load(text) or {}
    except Exception:
        # Minimal fallback parser for test/local environments without PyYAML.
        payload: dict[str, Any] = {}
        for raw in text.splitlines():
            line = raw.strip()
            if not line or line.startswith("#") or ":" not in line:
                continue
            key, value = line.split(":", 1)
            key = key.strip()
            value = value.strip()
            if value.lower() in {"true", "false"}:
                payload[key] = value.lower() == "true"
            elif value.isdigit():
                payload[key] = int(value)
            else:
                payload[key] = value.strip("'\"")
        return payload

