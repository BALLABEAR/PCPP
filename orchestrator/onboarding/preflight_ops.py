import re
from pathlib import Path
from typing import Any, Callable

from orchestrator.onboarding import dependency_scan as dep_scan
from orchestrator.onboarding.schemas import (
    DATA_KIND_FORMATS,
    PreflightScanRequest,
    ScaffoldModelRequest,
    ValidateModelRequest,
    ValidateModelResponse,
)


ENTRY_PATTERNS = (
    "run.py",
    "inference.py",
    "infer.py",
    "test.py",
    "demo.py",
    "evaluate.py",
    "main.py",
)


def is_lower_snake(value: str) -> bool:
    return re.fullmatch(r"[a-z][a-z0-9_]*", value) is not None


def clean_cli_tokens(raw: str) -> list[str]:
    return [token.strip() for token in (raw or "").split("\n") if token.strip() and token.strip().lower() != "<empty>"]


def validate_request(
    payload: ValidateModelRequest,
    *,
    resolve_user_path: Callable[[str], Path],
) -> ValidateModelResponse:
    errors: list[str] = []
    warnings: list[str] = []

    if not is_lower_snake(payload.model_id):
        errors.append("model_id must be lower_snake_case (e.g. poin_tr).")
    if not is_lower_snake(payload.task_type):
        errors.append("task_type must be lower_snake_case (e.g. completion).")

    repo = resolve_user_path(payload.repo_path)
    weights = resolve_user_path(payload.weights_path)
    config = resolve_user_path(payload.config_path)

    if not repo.exists() or not repo.is_dir():
        errors.append(f"repo_path not found: {repo}")
    if not weights.exists() or not weights.is_file():
        errors.append(f"weights_path not found: {weights}")
    if not config.exists() or not config.is_file():
        errors.append(f"config_path not found: {config}")

    valid_input = DATA_KIND_FORMATS.get(payload.input_data_kind, [])
    valid_output = DATA_KIND_FORMATS.get(payload.output_data_kind, [])
    if not valid_input:
        errors.append("Unsupported input_data_kind.")
    if not valid_output:
        errors.append("Unsupported output_data_kind.")

    return ValidateModelResponse(
        valid=len(errors) == 0,
        errors=errors,
        warnings=warnings,
        normalized={
            "model_id": payload.model_id,
            "task_type": payload.task_type,
            "repo_path": str(repo),
            "weights_path": str(weights),
            "config_path": str(config),
            "input_data_kind": payload.input_data_kind,
            "output_data_kind": payload.output_data_kind,
            "input_formats": valid_input,
            "output_formats": valid_output,
        },
    )


def guess_entry_command(payload: ScaffoldModelRequest, *, resolve_user_path: Callable[[str], Path]) -> str:
    entry = (payload.entry_command or "").strip()
    if entry:
        return entry
    repo = resolve_user_path(payload.repo_path)
    if (repo / "tools" / "inference.py").exists():
        return (
            "python {repo_path}/tools/inference.py {config_path} {weights_path} "
            "--pc {input} --out_pc_root {output_dir} --device {device}"
        )
    if (repo / "completion" / "test.py").exists():
        return (
            "python {repo_path}/completion/test.py "
            "--config {config_path} --ckpt_path {weights_path} "
            "--infile {input} --outdir {output_dir}"
        )
    return ""


def scan_preflight(
    payload: PreflightScanRequest,
    *,
    resolve_user_path: Callable[[str], Path],
) -> dict[str, Any]:
    validation = validate_request(payload, resolve_user_path=resolve_user_path)
    if not validation.valid:
        return {
            "valid": False,
            "errors": validation.errors,
            "warnings": validation.warnings,
            "suggested": {},
            "confidence": "low",
            "notes": [],
        }

    repo = resolve_user_path(payload.repo_path)
    suggested: dict[str, Any] = {
        "entry_command": "",
        "extra_pip_packages": [],
        "pip_requirements_files": [],
        "pip_extra_args": [],
        "system_packages": [],
        "base_image": "",
        "extra_build_steps": [],
        "env_overrides": {},
        "smoke_args": [],
    }
    notes: list[str] = []
    score = 0

    auto_packages, auto_req_files = dep_scan.collect_project_dependencies(repo)
    for req_path in auto_req_files[:8]:
        req_file = Path(req_path)
        try:
            rel = req_file.relative_to(repo).as_posix()
        except Exception:
            rel = req_file.as_posix()
        if rel not in suggested["pip_requirements_files"]:
            suggested["pip_requirements_files"].append(rel)
    if auto_req_files:
        notes.append(f"[scan] requirements files discovered: {len(auto_req_files)}")
        score += 1
    if auto_packages:
        suggested["extra_pip_packages"].extend(auto_packages)
        notes.append(f"[scan] python dependencies discovered: {len(auto_packages)}")
        score += 1

    env_yml = [p for p in repo.rglob("environment.yml")]
    if env_yml:
        content = dep_scan.read_text_safe(env_yml[0])
        for line in content.splitlines():
            text = line.strip().lstrip("-").strip()
            if text and "pip:" not in text and ":" not in text:
                suggested["extra_pip_packages"].append(text)
        notes.append(f"[scan] conda env: {env_yml[0].name}")
        score += 1

    readme = repo / "README.md"
    readme_text = dep_scan.read_text_safe(readme)
    if "cuda_home" in readme_text.lower():
        suggested["env_overrides"]["CUDA_HOME"] = "/usr/local/cuda"
        score += 1
    if "torch_cuda_arch_list" in readme_text.lower():
        suggested["env_overrides"]["TORCH_CUDA_ARCH_LIST"] = "8.6"
        score += 1

    entry_candidates = [p for p in repo.rglob("*.py") if p.name in ENTRY_PATTERNS]
    if entry_candidates:
        entry_rel = entry_candidates[0].relative_to(repo).as_posix()
        suggested["entry_command"] = f"python /app/external_models/{repo.name}/{entry_rel}"
        notes.append(f"[scan] entry candidate: {entry_rel}")
        score += 1

    ext_setup_candidates = [
        p for p in repo.rglob("setup.py")
        if any(part.lower() in {"extensions", "ops", "chamfer3d", "emd", "pointnet2_ops_lib"} for part in p.parts)
    ]
    if ext_setup_candidates:
        suggested["system_packages"] = ["ninja-build"]
        suggested["base_image"] = "nvidia/cuda:11.8.0-cudnn8-devel-ubuntu22.04"
        auto_build_steps = dep_scan.collect_build_step_hints(repo)
        if auto_build_steps:
            suggested["extra_build_steps"].extend(auto_build_steps)
            notes.append(f"[scan] generated build step hints: {len(auto_build_steps)}")
        notes.append("[scan] detected extension setup.py files")
        score += 1

    pip_unique: list[str] = []
    seen_pip: set[str] = set()
    for pkg in suggested["extra_pip_packages"]:
        key = pkg.lower()
        if key not in seen_pip:
            seen_pip.add(key)
            pip_unique.append(pkg)
    suggested["extra_pip_packages"] = pip_unique
    low_pkgs = " ".join(pip_unique).lower()
    if "opencv-python" in low_pkgs or "opencv-contrib-python" in low_pkgs:
        for pkg in dep_scan.OPENCV_SYSTEM_PACKAGES:
            if pkg not in suggested["system_packages"]:
                suggested["system_packages"].append(pkg)
        notes.append("[scan] detected opencv dependency -> added system libs (glib/x11/gl)")
        score += 1

    if ext_setup_candidates and not any("torch" in p.lower() for p in pip_unique):
        suggested["extra_pip_packages"].extend(["torch==2.1.2", "torchvision==0.16.2"])
        notes.append("[scan] inserted torch/torchvision packages for extension-ready environment")
        score += 1

    confidence = "low"
    if score >= 5:
        confidence = "high"
    elif score >= 2:
        confidence = "medium"

    return {
        "valid": True,
        "errors": [],
        "warnings": validation.warnings,
        "suggested": suggested,
        "confidence": confidence,
        "notes": notes,
    }
