import json
import importlib.util
import re
from pathlib import Path
from typing import Any

from fastapi import HTTPException
from sqlalchemy.orm import Session
import yaml

from flows.flow_definitions import get_pipeline_templates
from orchestrator.models.model_card import ModelCard
from orchestrator.models.model_runtime_status import ModelRuntimeStatus
from orchestrator.models.pipeline import Pipeline
from orchestrator.pipelines.schema import PipelineTemplateResponse
from orchestrator.pipelines.validators import build_step_from_model, validate_step_chain

USER_FLOW_ID = "pipeline_flow"


def validate_pipeline_draft(db: Session, name: str, steps: list[dict[str, Any]]) -> dict[str, Any]:
    errors: list[str] = []
    if not name.strip():
        errors.append("Pipeline name is required.")
    if not steps:
        errors.append("At least one step is required.")
        return {"valid": False, "errors": errors, "normalized_steps": []}

    normalized_steps: list[dict[str, Any]] = []
    for idx, step in enumerate(steps, start=1):
        model_id = str(step.get("model_id", "")).strip()
        if not model_id:
            errors.append(f"Step {idx}: model_id is required.")
            continue
        card = db.get(ModelCard, model_id)
        if not card:
            errors.append(f"Step {idx}: model '{model_id}' not found in registry.")
            continue
        readiness_error = _validate_model_readiness(db, card, idx)
        if readiness_error:
            errors.append(readiness_error)
            continue
        normalized = build_step_from_model(card)
        runtime_errors = _validate_step_runtime_assets(normalized, card, idx)
        if runtime_errors:
            errors.extend(runtime_errors)
            continue
        normalized["name"] = f"{idx:02d}_{model_id}"
        arg_schema = _load_arg_schema(card)
        cli_args, cli_errors = _normalize_cli_args(step.get("params") or {}, idx, arg_schema)
        if cli_errors:
            errors.extend(cli_errors)
            continue
        normalized["cli_args"] = cli_args
        normalized_steps.append(normalized)

    if errors:
        return {"valid": False, "errors": errors, "normalized_steps": []}

    errors.extend(validate_step_chain(normalized_steps))
    return {"valid": len(errors) == 0, "errors": errors, "normalized_steps": normalized_steps}


def create_pipeline_draft(db: Session, name: str, steps: list[dict[str, Any]]) -> Pipeline:
    validation = validate_pipeline_draft(db, name=name, steps=steps)
    if not validation["valid"]:
        raise HTTPException(status_code=422, detail={"errors": validation["errors"]})
    existing = db.query(Pipeline).filter(Pipeline.name == name).first()
    if existing:
        raise HTTPException(status_code=409, detail="Pipeline with this name already exists")

    template_payload = {
        "id": name.lower().replace(" ", "_"),
        "name": name,
        "flow_id": USER_FLOW_ID,
        "description": f"User pipeline: {name}",
        "flow_params": {"pipeline_steps": validation["normalized_steps"]},
        "source": "user",
    }
    pipeline = Pipeline(name=name, config_yaml=json.dumps(template_payload, ensure_ascii=False))
    db.add(pipeline)
    db.commit()
    db.refresh(pipeline)
    return pipeline


def list_templates_with_user(db: Session) -> list[dict[str, Any]]:
    system_templates = [{**item, "source": "system"} for item in get_pipeline_templates()]
    user_templates: list[dict[str, Any]] = []
    pipelines = db.query(Pipeline).order_by(Pipeline.created_at.desc()).all()
    for pipeline in pipelines:
        if not pipeline.config_yaml:
            continue
        try:
            payload = json.loads(pipeline.config_yaml)
        except Exception:
            continue
        if not isinstance(payload, dict):
            continue
        payload.setdefault("source", "user")
        payload.setdefault("pipeline_id", pipeline.id)
        payload["flow_id"] = USER_FLOW_ID
        if payload.get("flow_id"):
            user_templates.append(PipelineTemplateResponse(**payload).model_dump())
    return system_templates + user_templates


def _load_arg_schema(card: ModelCard) -> dict[str, dict[str, Any]]:
    path = Path(card.source_path)
    if not path.exists():
        return {}
    try:
        payload = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except Exception:
        return {}
    params = payload.get("params")
    if not isinstance(params, dict):
        return {}
    schema: dict[str, dict[str, Any]] = {}
    for key, value in params.items():
        canonical = str(key).strip()
        if not canonical:
            continue
        if not isinstance(value, dict):
            value = {}
        aliases_raw = value.get("aliases") or []
        aliases: list[str] = []
        if isinstance(aliases_raw, list):
            aliases = [str(item).strip() for item in aliases_raw if str(item).strip()]
        schema[canonical] = {
            "type": str(value.get("type") or "str"),
            "required": bool(value.get("required", False)),
            "aliases": aliases,
        }
    return schema


def _normalize_cli_args(
    params: dict[str, Any],
    step_idx: int,
    arg_schema: dict[str, dict[str, Any]],
) -> tuple[dict[str, Any], list[str]]:
    normalized: dict[str, Any] = {}
    errors: list[str] = []
    alias_to_key: dict[str, str] = {}
    for canonical, spec in arg_schema.items():
        alias_to_key[canonical] = canonical
        alias_to_key[canonical.replace("-", "_")] = canonical
        alias_to_key[canonical.replace("_", "-")] = canonical
        for alias in spec.get("aliases", []):
            alias_to_key[alias] = canonical
            alias_to_key[alias.replace("-", "_")] = canonical
            alias_to_key[alias.replace("_", "-")] = canonical

    for key, value in params.items():
        raw_key = str(key).strip()
        if not raw_key:
            errors.append(f"Step {step_idx}: empty param key is not allowed.")
            continue
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_\-]*", raw_key):
            errors.append(f"Step {step_idx}: param key '{raw_key}' contains unsupported characters.")
            continue
        if arg_schema:
            canonical = alias_to_key.get(raw_key)
            if not canonical:
                allowed = ", ".join(sorted(arg_schema.keys()))
                errors.append(
                    f"Step {step_idx}: param '{raw_key}' is not supported by this model. "
                    f"Allowed params: {allowed}."
                )
                continue
            try:
                parsed = _coerce_value(value, expected_type=arg_schema.get(canonical, {}).get("type"))
            except Exception as exc:
                errors.append(f"Step {step_idx}: failed to parse '{raw_key}': {exc}.")
                continue
            normalized[canonical] = parsed
        else:
            try:
                parsed = _coerce_value(value, expected_type=None)
            except Exception as exc:
                errors.append(f"Step {step_idx}: failed to parse '{raw_key}': {exc}.")
                continue
            normalized[raw_key] = parsed
    if arg_schema:
        for canonical, spec in arg_schema.items():
            if bool(spec.get("required")) and canonical not in normalized:
                errors.append(f"Step {step_idx}: required param '{canonical}' is missing.")
    return normalized, errors


def _coerce_value(value: Any, expected_type: str | None) -> Any:
    if expected_type:
        normalized_type = expected_type.strip().lower()
        if normalized_type in {"bool", "boolean"}:
            return _coerce_bool(value)
        if normalized_type in {"int", "integer"}:
            return _coerce_int(value)
        if normalized_type in {"float", "number"}:
            return _coerce_float(value)
        if normalized_type in {"list", "array"}:
            return _coerce_list(value)
        if normalized_type in {"json", "object", "dict"}:
            return _coerce_json(value)
        if normalized_type in {"path", "str", "string"}:
            return str(value).strip()
    if isinstance(value, (bool, int, float, list, dict)) or value is None:
        return value
    if not isinstance(value, str):
        return value
    text = value.strip()
    low = text.lower()
    if low in {"true", "false"}:
        return low == "true"
    if low in {"null", "none"}:
        return None
    if re.fullmatch(r"-?\d+", text):
        try:
            return int(text)
        except ValueError:
            return text
    if re.fullmatch(r"-?\d+\.\d+", text):
        try:
            return float(text)
        except ValueError:
            return text
    if text.startswith("[") or text.startswith("{"):
        try:
            parsed = json.loads(text)
            if isinstance(parsed, (list, dict, bool, int, float)) or parsed is None:
                return parsed
        except Exception:
            return text
    return text


def _coerce_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    text = str(value).strip().lower()
    return text in {"1", "true", "yes", "on"}


def _coerce_int(value: Any) -> int:
    if isinstance(value, int):
        return value
    return int(str(value).strip())


def _coerce_float(value: Any) -> float:
    if isinstance(value, float):
        return value
    return float(str(value).strip())


def _coerce_list(value: Any) -> list[Any]:
    if isinstance(value, list):
        return value
    if isinstance(value, str):
        text = value.strip()
        if text.startswith("["):
            try:
                parsed = json.loads(text)
                if isinstance(parsed, list):
                    return parsed
            except Exception:
                return [item.strip() for item in text.split(",") if item.strip()]
        return [item.strip() for item in text.split(",") if item.strip()]
    return [value]


def _coerce_json(value: Any) -> Any:
    if isinstance(value, (dict, list, bool, int, float)) or value is None:
        return value
    text = str(value).strip()
    return json.loads(text)


def _validate_step_runtime_assets(step: dict[str, Any], card: ModelCard, idx: int) -> list[str]:
    errors: list[str] = []
    source_path = Path(card.source_path)
    model_dir = source_path.parent
    worker_file = model_dir / "worker.py"
    dockerfile = Path(str(step.get("dockerfile_path") or ""))
    if not source_path.exists():
        errors.append(f"Step {idx}: model_card.yaml is missing for model '{card.id}'.")
    if not worker_file.exists():
        errors.append(f"Step {idx}: worker.py is missing for model '{card.id}'.")
    if not dockerfile.exists():
        errors.append(f"Step {idx}: Dockerfile is missing for model '{card.id}'.")
    worker_module = str(step.get("worker_module") or "")
    if worker_module:
        try:
            module_spec = importlib.util.find_spec(worker_module)
        except Exception:
            module_spec = None
        if module_spec is None:
            errors.append(f"Step {idx}: worker module '{worker_module}' is not importable.")
    return errors


def _validate_model_readiness(db: Session, card: ModelCard, idx: int) -> str | None:
    status = db.get(ModelRuntimeStatus, card.id)
    if not status:
        if "generated adapter scaffold" not in str(card.description or "").lower():
            return None
        return (
            f"Step {idx}: model '{card.id}' is not runtime-ready. "
            "Run onboarding build and smoke-run before using it in pipelines."
        )
    if not status.build_ok:
        return (
            f"Step {idx}: model '{card.id}' has no successful build. "
            "Re-run onboarding build and check dependencies."
        )
    if not status.smoke_ok:
        return (
            f"Step {idx}: model '{card.id}' has no successful smoke-run. "
            "Re-run onboarding smoke-run before adding to a pipeline."
        )
    return None
