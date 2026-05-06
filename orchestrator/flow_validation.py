from pathlib import Path
from typing import Any

from flows.flow_definitions import get_flow_step_builder
from workers.base.format_converter import FormatConverter


def _as_format_list(raw: Any) -> list[str]:
    if raw is None:
        return []
    if isinstance(raw, str):
        value = raw.strip()
        if not value:
            return []
        if value.startswith("[") and value.endswith("]"):
            parts = [p.strip() for p in value[1:-1].split(",")]
            return [p if p.startswith(".") else f".{p}" for p in parts if p]
        return [value if value.startswith(".") else f".{value}"]
    if isinstance(raw, list):
        result: list[str] = []
        for item in raw:
            if item is None:
                continue
            text = str(item).strip()
            if not text:
                continue
            result.append(text if text.startswith(".") else f".{text}")
        return result
    return []


def _load_yaml_like(path: Path) -> dict[str, Any]:
    text = path.read_text(encoding="utf-8")
    try:
        import yaml  # type: ignore

        return yaml.safe_load(text) or {}
    except Exception:
        payload: dict[str, Any] = {}
        for raw in text.splitlines():
            line = raw.strip()
            if not line or line.startswith("#") or ":" not in line:
                continue
            key, value = line.split(":", 1)
            payload[key.strip()] = value.strip().strip("'\"")
        return payload


def _model_card_for_worker_module(worker_module: str) -> Path:
    workspace_root = Path(__file__).resolve().parents[1]
    module_parts = worker_module.split(".")
    if len(module_parts) < 2 or module_parts[0] != "workers":
        raise ValueError(f"Unsupported worker_module for format validation: {worker_module}")
    return workspace_root.joinpath(*module_parts[:-1], "model_card.yaml")


def _load_model_format_spec(worker_module: str) -> dict[str, Any]:
    card_path = _model_card_for_worker_module(worker_module)
    if not card_path.exists():
        raise ValueError(f"model_card.yaml is missing for worker_module={worker_module}: {card_path}")
    payload = _load_yaml_like(card_path)
    accepted = _as_format_list(payload.get("accepted_input_formats") or payload.get("input_format"))
    produced = _as_format_list(payload.get("produced_output_formats") or payload.get("output_format"))
    preferred = str(payload.get("preferred_output_format") or "").strip()
    if preferred and not preferred.startswith("."):
        preferred = f".{preferred}"
    if not preferred and produced:
        preferred = produced[0]
    return {
        "accepted_input_formats": accepted,
        "produced_output_formats": produced,
        "preferred_output_format": preferred or None,
        "model_card_path": str(card_path),
    }


def _build_steps_for_validation(flow_id: str, flow_params: dict[str, Any]) -> list[dict[str, Any]]:
    custom = flow_params.get("pipeline_steps")
    if isinstance(custom, list) and custom:
        return custom
    builder = get_flow_step_builder(flow_id)
    if builder is None:
        return []
    return builder(flow_params)


def list_flow_worker_modules(
    *,
    flow_id: str,
    flow_params: dict[str, Any] | None,
) -> list[str]:
    params = flow_params or {}
    steps = _build_steps_for_validation(flow_id, params)
    seen: set[str] = set()
    modules: list[str] = []
    for step in steps:
        worker_module = str(step.get("worker_module") or "").strip()
        if worker_module and worker_module not in seen:
            seen.add(worker_module)
            modules.append(worker_module)
    return modules


def validate_flow_formats(
    *,
    flow_id: str,
    flow_params: dict[str, Any] | None,
    input_key: str,
    input_keys: list[str] | None = None,
) -> None:
    params = flow_params or {}
    steps = _build_steps_for_validation(flow_id, params)
    if not steps:
        return

    converter = FormatConverter()
    specs: list[dict[str, Any]] = []
    for step in steps:
        worker_module = step.get("worker_module")
        if not worker_module:
            continue
        spec = _load_model_format_spec(worker_module)
        specs.append({"step_name": step.get("name") or worker_module, "worker_module": worker_module, **spec})

    if not specs:
        return

    def _input_supported(ext: str, accepted: list[str]) -> bool:
        if not accepted:
            return True
        return any(ext == fmt or converter.can_convert_format(ext, fmt) for fmt in accepted)

    candidate_inputs = input_keys if input_keys else [input_key]
    first_accepted = specs[0]["accepted_input_formats"]
    for key in candidate_inputs:
        ext = Path(key).suffix.lower()
        if not _input_supported(ext, first_accepted):
            raise ValueError(
                f"Input format {ext or '<none>'} is incompatible with first step {specs[0]['step_name']} "
                f"(accepted: {first_accepted})."
            )

    for prev, nxt in zip(specs, specs[1:]):
        prev_outputs = prev["produced_output_formats"]
        next_inputs = nxt["accepted_input_formats"]
        if not prev_outputs or not next_inputs:
            continue
        direct_match = any(out_fmt in next_inputs for out_fmt in prev_outputs)
        convert_match = any(converter.can_convert_format(out_fmt, in_fmt) for out_fmt in prev_outputs for in_fmt in next_inputs)
        if not direct_match and not convert_match:
            raise ValueError(
                f"Format mismatch between {prev['step_name']} and {nxt['step_name']}: "
                f"outputs={prev_outputs}, next_inputs={next_inputs}."
            )
