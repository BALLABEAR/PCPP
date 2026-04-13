import os
import json
import hashlib
import re
import shutil
import subprocess
import tempfile
import threading
import uuid
import configparser
from fnmatch import fnmatch
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict, Field
import yaml

from orchestrator.onboarding.error_classifier import classify_error
import docker
from docker.errors import DockerException
from docker.types import DeviceRequest
from orchestrator.models import SessionLocal
from orchestrator.models.model_card import ModelCard
from orchestrator.models.model_runtime_status import ModelRuntimeStatus
from orchestrator.registry.scanner import scan_model_cards

try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover
    tomllib = None  # type: ignore[assignment]

router = APIRouter(prefix="/onboarding/models", tags=["onboarding"])

DATA_KIND_FORMATS: dict[str, list[str]] = {
    "point_cloud": [".xyz", ".ply", ".pcd", ".pts", ".txt", ".npy", ".las", ".laz"],
    "mesh": [".obj", ".stl", ".off", ".ply"],
}


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _workspace_root() -> Path:
    return Path(os.getenv("WORKSPACE_ROOT", "/app")).resolve()


def _resolve_user_path(raw: str) -> Path:
    normalized = (raw or "").strip().replace("\\", "/")
    path = Path(normalized)
    if not path.is_absolute():
        path = _workspace_root() / path
    return path.resolve()


def _is_lower_snake(value: str) -> bool:
    return re.fullmatch(r"[a-z][a-z0-9_]*", value) is not None


class ValidateModelRequest(BaseModel):
    model_config = ConfigDict(protected_namespaces=())
    model_id: str
    task_type: str
    repo_path: str
    weights_path: str
    config_path: str
    input_data_kind: Literal["point_cloud", "mesh"] = "point_cloud"
    output_data_kind: Literal["point_cloud", "mesh"] = "point_cloud"


class ValidateModelResponse(BaseModel):
    valid: bool
    errors: list[str]
    warnings: list[str]
    normalized: dict[str, Any]


class ScaffoldModelRequest(ValidateModelRequest):
    model_config = ConfigDict(protected_namespaces=())
    description: str = "Generated adapter scaffold. Replace template logic with real inference."
    overwrite: bool = False
    entry_command: str = ""
    extra_pip_packages: list[str] = Field(default_factory=list)
    pip_requirements_files: list[str] = Field(default_factory=list)
    pip_extra_args: list[str] = Field(default_factory=list)
    system_packages: list[str] = Field(default_factory=list)
    base_image: str = ""
    extra_build_steps: list[str] = Field(default_factory=list)
    env_overrides: dict[str, str] = Field(default_factory=dict)


class ActionRunRequest(BaseModel):
    command: list[str]
    cwd: str | None = None


class BuildRequest(BaseModel):
    model_config = ConfigDict(protected_namespaces=())
    task_type: str
    model_id: str
    image_tag: str | None = None
    no_cache: bool = False


class CleanupRequest(BaseModel):
    model_config = ConfigDict(protected_namespaces=())
    task_type: str
    model_id: str


class SmokeRunRequest(BaseModel):
    model_config = ConfigDict(protected_namespaces=())
    task_type: str
    model_id: str
    input_path: str | None = None
    input_data_kind: Literal["point_cloud", "mesh"] = "point_cloud"
    output_dir: str = "./examples/model_outputs"
    image_tag: str | None = None
    use_gpu: bool = True
    model_args: list[str] = Field(default_factory=list)
    smoke_args: str = ""


class RegistryCheckRequest(BaseModel):
    model_config = ConfigDict(protected_namespaces=())
    model_id: str


class PreflightScanRequest(ValidateModelRequest):
    pass


class CleanupBackupsRequest(BaseModel):
    model_config = ConfigDict(protected_namespaces=())
    task_type: str | None = None
    model_id: str | None = None
    apply: bool = False
    older_than_hours: int = 0


class RunStatusResponse(BaseModel):
    run_id: str
    kind: Literal["build", "smoke", "command"]
    status: Literal["pending", "running", "completed", "failed"]
    command: list[str]
    cwd: str
    logs: str
    started_at_utc: str
    finished_at_utc: str | None
    exit_code: int | None
    error_hint: dict[str, str] | None


_RUNS_LOCK = threading.Lock()
_RUNS: dict[str, dict[str, Any]] = {}

_ENTRY_PATTERNS = (
    "run.py",
    "inference.py",
    "infer.py",
    "test.py",
    "demo.py",
    "evaluate.py",
    "main.py",
)


_OPENCV_SYSTEM_PACKAGES = [
    "libglib2.0-0",
    "libgl1",
    "libsm6",
    "libxext6",
    "libxrender1",
]


def _debug_log(hypothesis_id: str, message: str, data: dict[str, Any] | None = None, run_id: str = "onboarding") -> None:
    # #region agent log
    payload = {
        "sessionId": "e69ff4",
        "runId": run_id,
        "hypothesisId": hypothesis_id,
        "location": "orchestrator/api/onboarding.py",
        "message": message,
        "data": data or {},
        "timestamp": int(datetime.now(timezone.utc).timestamp() * 1000),
    }
    try:
        with Path("debug-e69ff4.log").open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(payload, ensure_ascii=True) + "\n")
    except Exception:
        pass
    # #endregion


def _parse_requirements_file(path: Path, visited: set[Path] | None = None) -> tuple[list[str], list[str]]:
    packages: list[str] = []
    requirement_files: list[str] = []
    visited = visited or set()
    real_path = path.resolve()
    if real_path in visited:
        return packages, requirement_files
    visited.add(real_path)
    requirement_files.append(str(path))
    for raw in _read_text_safe(path).splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if "#" in line:
            line = line.split("#", 1)[0].strip()
        if not line:
            continue
        req_match = re.match(r"^(?:-r|--requirement)\s+(.+)$", line)
        con_match = re.match(r"^(?:-c|--constraint)\s+(.+)$", line)
        if req_match or con_match:
            ref = (req_match or con_match).group(1).strip()
            ref_path = (path.parent / ref).resolve()
            if ref_path.exists() and ref_path.is_file():
                nested_packages, nested_files = _parse_requirements_file(ref_path, visited=visited)
                packages.extend(nested_packages)
                requirement_files.extend(nested_files)
            continue
        if line.startswith(("git+", "http://", "https://")):
            packages.append(line)
            continue
        if line.startswith("--"):
            continue
        if line.lower() in {"argparse"}:
            continue
        packages.append(line)
    return packages, requirement_files


def _collect_project_dependencies(repo: Path) -> tuple[list[str], list[str]]:
    discovered_packages: list[str] = []
    discovered_reqs: list[str] = []
    req_names = {"requirements.txt", "requirements-dev.txt", "requirements.in"}
    for req in repo.rglob("*"):
        if not req.is_file():
            continue
        if req.name in req_names or (req.name.startswith("requirements") and req.suffix == ".txt"):
            req_packages, req_files = _parse_requirements_file(req)
            discovered_packages.extend(req_packages)
            discovered_reqs.extend(req_files)

    pyproject = repo / "pyproject.toml"
    if pyproject.exists() and tomllib is not None:
        try:
            payload = tomllib.loads(_read_text_safe(pyproject))
            project_dep = payload.get("project", {}).get("dependencies", []) or []
            optional_dep = payload.get("project", {}).get("optional-dependencies", {}) or {}
            for item in project_dep:
                if isinstance(item, str):
                    discovered_packages.append(item)
            if isinstance(optional_dep, dict):
                for items in optional_dep.values():
                    if isinstance(items, list):
                        for item in items:
                            if isinstance(item, str):
                                discovered_packages.append(item)
            poetry_dep = payload.get("tool", {}).get("poetry", {}).get("dependencies", {}) or {}
            if isinstance(poetry_dep, dict):
                for key, value in poetry_dep.items():
                    if key == "python":
                        continue
                    if isinstance(value, str):
                        discovered_packages.append(f"{key}{value if value.startswith(('=', '>', '<', '~', '!')) else '==' + value}")
                    elif isinstance(value, dict) and isinstance(value.get("version"), str):
                        discovered_packages.append(f"{key}{value['version']}")
        except Exception:
            pass

    setup_cfg = repo / "setup.cfg"
    if setup_cfg.exists():
        parser = configparser.ConfigParser()
        try:
            parser.read_string(_read_text_safe(setup_cfg))
            if parser.has_option("options", "install_requires"):
                raw = parser.get("options", "install_requires")
                discovered_packages.extend([line.strip() for line in raw.splitlines() if line.strip()])
        except Exception:
            pass

    setup_py = repo / "setup.py"
    if setup_py.exists():
        text = _read_text_safe(setup_py)
        match = re.search(r"install_requires\s*=\s*\[(.*?)\]", text, flags=re.DOTALL)
        if match:
            for dep in re.findall(r"['\"]([^'\"]+)['\"]", match.group(1)):
                discovered_packages.append(dep.strip())
    return discovered_packages, discovered_reqs


def _collect_build_step_hints(repo: Path) -> list[str]:
    hints: list[str] = []
    skip_dirs = {
        ".git", ".hg", ".svn", "__pycache__", "node_modules",
        ".venv", "venv", "env", "build", "dist",
    }
    keyword_dirs = {
        "extensions", "extension", "ext", "ops", "op", "cuda",
        "chamfer", "emd", "pointnet2_ops", "pointnet2_ops_lib",
    }
    ext_setup_candidates: list[Path] = []
    for setup_path in repo.rglob("setup.py"):
        rel_parts = [part.lower() for part in setup_path.relative_to(repo).parts]
        if any(part in skip_dirs for part in rel_parts):
            continue
        if setup_path.parent == repo:
            # Repository-level setup.py is usually package install, not extension build.
            continue
        text = _read_text_safe(setup_path).lower()
        looks_like_native_ext = any(key in text for key in ("cudaextension", "cppextension", "buildextension"))
        path_has_ext_hint = any(part in keyword_dirs for part in rel_parts)
        if looks_like_native_ext or path_has_ext_hint:
            ext_setup_candidates.append(setup_path)
    for setup_path in ext_setup_candidates:
        rel = setup_path.relative_to(repo).as_posix()
        hints.append(f"cd /app/external_models/{repo.name}/{Path(rel).parent.as_posix()} && python setup.py install")
    makefiles = [p for p in repo.rglob("Makefile") if "build" in _read_text_safe(p).lower()]
    for makefile in makefiles[:3]:
        rel = makefile.relative_to(repo).as_posix()
        hints.append(f"cd /app/external_models/{repo.name}/{Path(rel).parent.as_posix()} && make")
    # Fallback for repos importing pointnet2_ops without vendored setup.py.
    # This keeps onboarding universal for common PointNet2-based models.
    has_pointnet2_import = False
    for py in repo.rglob("*.py"):
        if "pointnet2_ops" in _read_text_safe(py):
            has_pointnet2_import = True
            break
    has_local_pointnet2_setup = any("pointnet2" in p.as_posix().lower() for p in ext_setup_candidates)
    if has_pointnet2_import and not has_local_pointnet2_setup:
        hints.append(
            "python -m pip install --no-cache-dir --no-build-isolation "
            "git+https://github.com/erikwijmans/Pointnet2_PyTorch.git#subdirectory=pointnet2_ops_lib"
        )
    # preserve order while removing duplicates
    seen: set[str] = set()
    unique: list[str] = []
    for item in hints:
        if item not in seen:
            seen.add(item)
            unique.append(item)
    return unique


def _normalize_dependency_inputs(
    *,
    repo_path: str,
    extra_pip_packages: list[str],
    pip_requirements_files: list[str],
    system_packages: list[str],
) -> tuple[list[str], list[str], list[str]]:
    repo = _resolve_user_path(repo_path)
    repo_mount = f"external_models/{repo.name}"
    merged_packages: list[str] = []
    merged_requirements: list[str] = []
    seen: set[str] = set()
    seen_reqs: set[str] = set()

    optional_heavy = {
        "plotly",
        "dash",
    }

    def _normalize_pkg(pkg: str) -> str:
        value = pkg.strip()
        value = re.sub(r"\s+--[a-zA-Z0-9_-]+(?:=\S+)?", "", value).strip()
        low = value.lower()
        pkg_name = re.split(r"[<>=!~ ]", low, maxsplit=1)[0]
        if pkg_name in optional_heavy:
            return ""
        if low.startswith("open3d==0.9"):
            return "open3d==0.19.0"
        return value

    def _pkg_name(pkg: str) -> str:
        token = re.split(r"[<>=!~ ]", pkg.strip(), maxsplit=1)[0]
        return token.lower()

    def _push(pkg: str) -> None:
        value = _normalize_pkg(pkg)
        if not value:
            return
        key = _pkg_name(value)
        if key and key not in seen:
            seen.add(key)
            merged_packages.append(value)

    for pkg in extra_pip_packages:
        _push(pkg)

    for req in pip_requirements_files:
        rel = req.strip()
        if not rel:
            continue
        req_path = repo / rel
        if req_path.exists() and req_path.is_file():
            req_packages, req_files = _parse_requirements_file(req_path)
            for pkg in req_packages:
                _push(pkg)
            for item in req_files:
                rel_item = Path(item).resolve()
                if rel_item not in seen_reqs:
                    seen_reqs.add(rel_item)
                    try:
                        merged_requirements.append(f"{repo_mount}/{rel_item.relative_to(repo).as_posix()}")
                    except Exception:
                        merged_requirements.append(str(rel_item))

    auto_packages, _auto_req_files = _collect_project_dependencies(repo)
    for pkg in auto_packages:
        _push(pkg)

    has_torch = any(_pkg_name(pkg) in {"torch", "torchvision"} for pkg in merged_packages)
    if not has_torch:
        torch_markers = 0
        for py_file in list(repo.rglob("*.py"))[:200]:
            content = _read_text_safe(py_file)
            if "import torch" in content or "from torch" in content:
                torch_markers += 1
                if torch_markers >= 2:
                    break
        if torch_markers >= 1:
            _push("torch==2.1.2")
            _push("torchvision==0.16.2")

    merged_system = [pkg.strip() for pkg in system_packages if pkg.strip()]
    low_pkgs = " ".join(merged_packages).lower()
    if "opencv-python" in low_pkgs or "opencv-contrib-python" in low_pkgs:
        for pkg in _OPENCV_SYSTEM_PACKAGES:
            if pkg not in merged_system:
                merged_system.append(pkg)

    return merged_packages, merged_requirements, merged_system


def _patch_runtime_manifest(
    manifest_path: Path,
    *,
    extra_pip_packages: list[str],
    pip_requirements_files: list[str],
    pip_extra_args: list[str],
    system_packages: list[str],
    base_image: str,
    extra_build_steps: list[str],
    env_overrides: dict[str, str],
) -> None:
    if not manifest_path.exists():
        return
    data = yaml.safe_load(manifest_path.read_text(encoding="utf-8")) or {}
    data.setdefault("python", {})
    data["python"].setdefault("pip", [])
    data["python"].setdefault("pip_commands", [])
    data["python"].setdefault("pip_requirements_files", [])
    data["python"].setdefault("pip_extra_args", [])
    data.setdefault("system_packages", [])
    if base_image.strip():
        data["base_image"] = base_image.strip()
    def _clean(value: str) -> str:
        text = (value or "").strip()
        return "" if text.lower() == "<empty>" else text

    for item in system_packages:
        pkg = _clean(item)
        if pkg and pkg not in data["system_packages"]:
            data["system_packages"].append(pkg)
    for req in pip_requirements_files:
        value = _clean(req)
        if value and value not in data["python"]["pip_requirements_files"]:
            data["python"]["pip_requirements_files"].append(value)
    for arg in pip_extra_args:
        value = _clean(arg)
        if value and value not in data["python"]["pip_extra_args"]:
            data["python"]["pip_extra_args"].append(value)
    if extra_pip_packages:
        cleaned = [pkg for pkg in (_clean(item) for item in extra_pip_packages) if pkg]
        torch_related = [pkg for pkg in cleaned if pkg.lower().startswith("torch") or pkg.lower().startswith("torchvision")]
        if torch_related:
            data["python"]["pip_commands"].append(
                "python -m pip install --no-cache-dir torch==2.1.2 torchvision==0.16.2 --index-url https://download.pytorch.org/whl/cu118"
            )
        for pkg in cleaned:
            if pkg in torch_related:
                continue
            if pkg not in data["python"]["pip"]:
                data["python"]["pip"].append(pkg)
    data.setdefault("build_steps", [])
    for step in extra_build_steps:
        value = _clean(step)
        if value:
            data["build_steps"].append(value)
    data.setdefault("env", {})
    for key, value in env_overrides.items():
        if key.strip():
            data["env"][key.strip()] = str(value)
    # CUDA extension builds inside Docker often have no visible GPU during `docker build`,
    # which leaves TORCH_CUDA_ARCH_LIST empty and breaks torch.utils.cpp_extension.
    # Provide a conservative default (Ampere + PTX) unless the user overrides.
    build_text = " ".join(str(s) for s in (data.get("build_steps") or [])).lower()
    if "setup.py" in build_text and "TORCH_CUDA_ARCH_LIST" not in data["env"]:
        data["env"]["TORCH_CUDA_ARCH_LIST"] = "8.0"
    manifest_path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")


def _patch_dockerfile_base_image(dockerfile_path: Path, base_image: str) -> None:
    if not dockerfile_path.exists():
        return
    image = (base_image or "").strip()
    if not image:
        return
    lines = dockerfile_path.read_text(encoding="utf-8").splitlines()
    patched: list[str] = []
    replaced = False
    for line in lines:
        if not replaced and line.strip().startswith("FROM "):
            patched.append(f"FROM {image}")
            replaced = True
        else:
            patched.append(line)
    if replaced:
        dockerfile_path.write_text("\n".join(patched) + "\n", encoding="utf-8")


def _docker_image_exists(tag: str) -> bool:
    try:
        client = docker.from_env()
        client.images.get(tag)
        return True
    except Exception:
        return False


def _ensure_shared_runtime_for_build(*, run_id: str, root: Path, dockerfile: Path) -> None:
    runtime_tag = "pcpp-runtime-cuda118:latest"
    fallback_base = "nvidia/cuda:11.8.0-cudnn8-devel-ubuntu22.04"
    content = dockerfile.read_text(encoding="utf-8")
    if "FROM pcpp-runtime-cuda118:latest" not in content:
        return
    if _docker_image_exists(runtime_tag):
        with _RUNS_LOCK:
            _RUNS[run_id]["logs"] += f"[build] shared runtime hit: {runtime_tag}\n"
        return
    with _RUNS_LOCK:
        _RUNS[run_id]["logs"] += f"[build] shared runtime miss: {runtime_tag}, building it now...\n"
    runtime_dockerfile = root / "workers" / "base" / "runtime" / "Dockerfile.cuda118"
    try:
        client = docker.from_env()
        api = client.api
        for chunk in api.build(
            path=str(root),
            dockerfile=str(runtime_dockerfile.relative_to(root)),
            tag=runtime_tag,
            decode=True,
            nocache=False,
            pull=False,
            rm=True,
        ):
            line = chunk.get("stream") or chunk.get("error") or ""
            if line:
                with _RUNS_LOCK:
                    _RUNS[run_id]["logs"] += line
            if "error" in chunk:
                raise RuntimeError(str(chunk["error"]))
        with _RUNS_LOCK:
            _RUNS[run_id]["logs"] += f"[build] shared runtime built: {runtime_tag}\n"
    except Exception as exc:
        # Fallback for environments where shared runtime cannot be prebuilt.
        patched = content.replace("FROM pcpp-runtime-cuda118:latest", f"FROM {fallback_base}", 1)
        dockerfile.write_text(patched, encoding="utf-8")
        with _RUNS_LOCK:
            _RUNS[run_id]["logs"] += (
                f"[build] shared runtime build failed ({exc}); "
                f"fallback to base image: {fallback_base}\n"
            )


def _read_text_safe(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return ""


def _copy_tree(src: Path, dst: Path) -> None:
    if not src.exists():
        return
    if src.is_file():
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)
        return
    for item in src.rglob("*"):
        rel = item.relative_to(src)
        target = dst / rel
        if item.is_dir():
            target.mkdir(parents=True, exist_ok=True)
        else:
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(item, target)


def _read_model_repo_path(root: Path, task_type: str, model_id: str) -> str | None:
    card_path = root / "workers" / task_type / model_id / "model_card.yaml"
    if not card_path.exists():
        return None
    try:
        payload = yaml.safe_load(card_path.read_text(encoding="utf-8")) or {}
    except Exception:
        return None
    value = payload.get("github_url")
    if not isinstance(value, str):
        return None
    return value.strip() or None


def _manifest_hash(root: Path, task_type: str, model_id: str) -> str | None:
    manifest_path = root / "workers" / task_type / model_id / "runtime.manifest.yaml"
    if not manifest_path.exists():
        return None
    return hashlib.sha256(manifest_path.read_bytes()).hexdigest()


def _update_model_runtime_status(
    *,
    model_id: str,
    build_ok: bool | None = None,
    smoke_ok: bool | None = None,
    image_tag: str | None = None,
    manifest_hash: str | None = None,
    last_error: str | None = None,
    mark_verified: bool = False,
) -> None:
    db = SessionLocal()
    try:
        status = db.get(ModelRuntimeStatus, model_id)
        if not status:
            status = ModelRuntimeStatus(model_id=model_id)
            db.add(status)
        now = datetime.now(timezone.utc)
        if build_ok is not None:
            status.build_ok = build_ok
            status.last_build_at = now
        if smoke_ok is not None:
            status.smoke_ok = smoke_ok
            status.last_smoke_at = now
        if image_tag:
            status.last_image_tag = image_tag
        if manifest_hash:
            status.manifest_hash = manifest_hash
        if last_error is not None:
            status.last_error = last_error[:1024]
        if mark_verified:
            status.last_verified_at = now
        db.commit()
    finally:
        db.close()


def _prepare_build_context(root: Path, task_type: str, model_id: str) -> tuple[Path, Path]:
    stage_dir = Path(tempfile.mkdtemp(prefix=f"pcpp_build_{task_type}_{model_id}_"))
    workers_dst = stage_dir / "workers"
    workers_dst.mkdir(parents=True, exist_ok=True)
    (stage_dir / "external_models").mkdir(parents=True, exist_ok=True)

    # Copy only required worker code.
    _copy_tree(root / "workers" / "__init__.py", workers_dst / "__init__.py")
    _copy_tree(root / "workers" / "base", workers_dst / "base")
    _copy_tree(root / "workers" / task_type / "__init__.py", workers_dst / task_type / "__init__.py")
    _copy_tree(root / "workers" / task_type / model_id, workers_dst / task_type / model_id)

    # Copy only required external model repository when detectable.
    repo_path_raw = _read_model_repo_path(root, task_type, model_id)
    if repo_path_raw:
        repo_path = _resolve_user_path(repo_path_raw)
        external_root = (root / "external_models").resolve()
        if repo_path.exists() and repo_path.is_dir():
            if external_root in repo_path.parents or repo_path == external_root:
                rel = repo_path.relative_to(external_root)
                _copy_tree(repo_path, stage_dir / "external_models" / rel)
            else:
                _copy_tree(repo_path, stage_dir / "external_models" / repo_path.name)

    dockerfile = stage_dir / "workers" / task_type / model_id / "Dockerfile"
    file_count = sum(1 for p in stage_dir.rglob("*") if p.is_file())
    _debug_log("H2", "build context prepared", {"task_type": task_type, "model_id": model_id, "file_count": file_count, "stage_dir": str(stage_dir)})
    return stage_dir, dockerfile


def _scan_preflight(payload: PreflightScanRequest) -> dict[str, Any]:
    validation = _validate_request(payload)
    if not validation.valid:
        return {
            "valid": False,
            "errors": validation.errors,
            "warnings": validation.warnings,
            "suggested": {},
            "confidence": "low",
            "notes": [],
        }

    repo = _resolve_user_path(payload.repo_path)
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

    auto_packages, auto_req_files = _collect_project_dependencies(repo)
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
        content = _read_text_safe(env_yml[0])
        for line in content.splitlines():
            text = line.strip().lstrip("-").strip()
            if text and "pip:" not in text and ":" not in text:
                suggested["extra_pip_packages"].append(text)
        notes.append(f"[scan] conda env: {env_yml[0].name}")
        score += 1

    readme = repo / "README.md"
    readme_text = _read_text_safe(readme)
    if "cuda_home" in readme_text.lower():
        suggested["env_overrides"]["CUDA_HOME"] = "/usr/local/cuda"
        score += 1
    if "torch_cuda_arch_list" in readme_text.lower():
        suggested["env_overrides"]["TORCH_CUDA_ARCH_LIST"] = "8.6"
        score += 1

    entry_candidates = [p for p in repo.rglob("*.py") if p.name in _ENTRY_PATTERNS]
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
        auto_build_steps = _collect_build_step_hints(repo)
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
        for pkg in _OPENCV_SYSTEM_PACKAGES:
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

    result = {
        "valid": True,
        "errors": [],
        "warnings": validation.warnings,
        "suggested": suggested,
        "confidence": confidence,
        "notes": notes,
    }
    _debug_log("H3", "preflight suggestions built", {"confidence": confidence, "notes_count": len(notes), "score": score})
    return result


def _collect_backup_dirs(root: Path, *, task_type: str | None, model_id: str | None) -> list[Path]:
    workers_root = root / "workers"
    candidates: list[Path] = []
    if not workers_root.exists():
        return candidates
    pattern = f"{model_id}.bak_*" if model_id else "*.bak_*"
    search_base = workers_root / task_type if task_type else workers_root
    if not search_base.exists():
        return candidates
    for path in search_base.rglob("*"):
        if path.is_dir() and fnmatch(path.name, pattern):
            candidates.append(path)
    return candidates


def _clean_cli_tokens(raw: str) -> list[str]:
    return [token.strip() for token in (raw or "").split("\n") if token.strip() and token.strip().lower() != "<empty>"]


def _validate_request(payload: ValidateModelRequest) -> ValidateModelResponse:
    errors: list[str] = []
    warnings: list[str] = []

    if not _is_lower_snake(payload.model_id):
        errors.append("model_id must be lower_snake_case (e.g. poin_tr).")
    if not _is_lower_snake(payload.task_type):
        errors.append("task_type must be lower_snake_case (e.g. completion).")

    repo = _resolve_user_path(payload.repo_path)
    weights = _resolve_user_path(payload.weights_path)
    config = _resolve_user_path(payload.config_path)

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


def _guess_entry_command(payload: ScaffoldModelRequest) -> str:
    entry = (payload.entry_command or "").strip()
    if entry:
        return entry
    repo = _resolve_user_path(payload.repo_path)
    repo_name = repo.name
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


def _backup_if_exists(target: Path) -> None:
    if not target.exists():
        return
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup = target.with_name(f"{target.name}.bak_{stamp}")
    shutil.move(str(target), str(backup))


def _start_run(kind: Literal["build", "smoke", "command"], command: list[str], cwd: Path) -> str:
    run_id = uuid.uuid4().hex
    record = {
        "run_id": run_id,
        "kind": kind,
        "status": "pending",
        "command": command,
        "cwd": str(cwd),
        "logs": "",
        "started_at_utc": _utc_now(),
        "finished_at_utc": None,
        "exit_code": None,
        "error_hint": None,
    }
    with _RUNS_LOCK:
        _RUNS[run_id] = record

    def _runner() -> None:
        with _RUNS_LOCK:
            _RUNS[run_id]["status"] = "running"
        try:
            process = subprocess.Popen(
                command,
                cwd=str(cwd),
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
            )
            assert process.stdout is not None
            for line in process.stdout:
                with _RUNS_LOCK:
                    _RUNS[run_id]["logs"] += line
            process.wait()
            exit_code = int(process.returncode or 0)
            with _RUNS_LOCK:
                _RUNS[run_id]["exit_code"] = exit_code
                _RUNS[run_id]["finished_at_utc"] = _utc_now()
                _RUNS[run_id]["status"] = "completed" if exit_code == 0 else "failed"
                if exit_code != 0:
                    _RUNS[run_id]["error_hint"] = classify_error(_RUNS[run_id]["logs"])
        except Exception as exc:
            with _RUNS_LOCK:
                _RUNS[run_id]["logs"] += f"\n[runner-error] {exc}\n"
                _RUNS[run_id]["exit_code"] = 1
                _RUNS[run_id]["finished_at_utc"] = _utc_now()
                _RUNS[run_id]["status"] = "failed"
                _RUNS[run_id]["error_hint"] = classify_error(_RUNS[run_id]["logs"])

    threading.Thread(target=_runner, daemon=True).start()
    return run_id


def _start_docker_build_run(
    *,
    tag: str,
    dockerfile: Path,
    root: Path,
    model_id: str,
    task_type: str,
    no_cache: bool = False,
    cleanup_path: Path | None = None,
) -> str:
    run_id = uuid.uuid4().hex
    record = {
        "run_id": run_id,
        "kind": "build",
        "status": "pending",
        "command": ["docker-sdk", "build", "-t", tag, "-f", str(dockerfile)],
        "cwd": str(root),
        "logs": "",
        "started_at_utc": _utc_now(),
        "finished_at_utc": None,
        "exit_code": None,
        "error_hint": None,
    }
    with _RUNS_LOCK:
        _RUNS[run_id] = record

    def _runner() -> None:
        with _RUNS_LOCK:
            _RUNS[run_id]["status"] = "running"
            _RUNS[run_id]["logs"] += "[build] Starting docker build. Preparing context may take a while on large repos.\n"
            _RUNS[run_id]["logs"] += f"[build] cache mode: {'disabled' if no_cache else 'enabled'} (cache_from={tag})\n"
        _debug_log("H4", "docker build start", {"run_id": run_id, "tag": tag, "no_cache": no_cache}, run_id=run_id)
        try:
            _ensure_shared_runtime_for_build(run_id=run_id, root=root, dockerfile=dockerfile)
            client = docker.from_env()
            api = client.api
            for chunk in api.build(
                path=str(root),
                dockerfile=str(dockerfile.relative_to(root)),
                tag=tag,
                decode=True,
                nocache=no_cache,
                pull=False,
                rm=True,
                cache_from=[tag],
            ):
                line = chunk.get("stream") or chunk.get("error") or ""
                if line:
                    with _RUNS_LOCK:
                        _RUNS[run_id]["logs"] += line
                if "error" in chunk:
                    raise RuntimeError(str(chunk["error"]))
            with _RUNS_LOCK:
                _RUNS[run_id]["exit_code"] = 0
                _RUNS[run_id]["finished_at_utc"] = _utc_now()
                _RUNS[run_id]["status"] = "completed"
            _update_model_runtime_status(
                model_id=model_id,
                build_ok=True,
                smoke_ok=False,
                image_tag=tag,
                manifest_hash=_manifest_hash(_workspace_root(), task_type, model_id),
                last_error=None,
                mark_verified=False,
            )
        except Exception as exc:
            with _RUNS_LOCK:
                _RUNS[run_id]["logs"] += f"\n[docker-build-error] {exc}\n"
                _RUNS[run_id]["exit_code"] = 1
                _RUNS[run_id]["finished_at_utc"] = _utc_now()
                _RUNS[run_id]["status"] = "failed"
                _RUNS[run_id]["error_hint"] = classify_error(_RUNS[run_id]["logs"])
            _update_model_runtime_status(
                model_id=model_id,
                build_ok=False,
                image_tag=tag,
                manifest_hash=_manifest_hash(_workspace_root(), task_type, model_id),
                last_error=str(exc),
                mark_verified=False,
            )
        finally:
            if cleanup_path and cleanup_path.exists():
                shutil.rmtree(cleanup_path, ignore_errors=True)

    threading.Thread(target=_runner, daemon=True).start()
    return run_id


def _start_docker_smoke_run(
    *,
    image_tag: str,
    module_name: str,
    input_data_kind: Literal["point_cloud", "mesh"],
    use_gpu: bool,
    model_args: list[str],
    model_id: str,
) -> str:
    if input_data_kind == "mesh":
        sample_create = (
            "p=pathlib.Path('/tmp/pcpp_smoke_input.obj');"
            "p.write_text('v 0 0 0\\n' 'v 1 0 0\\n' 'v 0 1 0\\n' 'f 1 2 3\\n', encoding='utf-8');"
        )
        sample_path = "/tmp/pcpp_smoke_input.obj"
    else:
        sample_create = (
            "p=pathlib.Path('/tmp/pcpp_smoke_input.pcd');"
            "p.write_text("
            "'# .PCD v0.7 - Point Cloud Data file format\\n'"
            "'VERSION 0.7\\n'"
            "'FIELDS x y z\\n'"
            "'SIZE 4 4 4\\n'"
            "'TYPE F F F\\n'"
            "'COUNT 1 1 1\\n'"
            "'WIDTH 4\\n'"
            "'HEIGHT 1\\n'"
            "'VIEWPOINT 0 0 0 1 0 0 0\\n'"
            "'POINTS 4\\n'"
            "'DATA ascii\\n'"
            "'0 0 0\\n1 0 0\\n0 1 0\\n0 0 1\\n', "
            "encoding='utf-8');"
        )
        sample_path = "/tmp/pcpp_smoke_input.pcd"

    smoke_runner = (
        "import pathlib,subprocess,sys;"
        f"{sample_create}"
        "pathlib.Path('/tmp/pcpp_smoke_out').mkdir(parents=True, exist_ok=True);"
        f"cmd=['python','-m','{module_name}','--input','{sample_path}','--output-dir','/tmp/pcpp_smoke_out']+{repr(model_args or [])};"
        "sys.exit(subprocess.call(cmd))"
    )
    run_id = uuid.uuid4().hex
    command = ["python", "-c", smoke_runner]
    record = {
        "run_id": run_id,
        "kind": "smoke",
        "status": "pending",
        "command": ["docker-sdk", "run", image_tag] + command,
        "cwd": "",
        "logs": "",
        "started_at_utc": _utc_now(),
        "finished_at_utc": None,
        "exit_code": None,
        "error_hint": None,
    }
    with _RUNS_LOCK:
        _RUNS[run_id] = record

    def _runner() -> None:
        with _RUNS_LOCK:
            _RUNS[run_id]["status"] = "running"
        try:
            client = docker.from_env()
            env = {}
            device_requests = None
            if use_gpu:
                env["NVIDIA_VISIBLE_DEVICES"] = "all"
                env["NVIDIA_DRIVER_CAPABILITIES"] = "compute,utility"
                device_requests = [DeviceRequest(count=-1, capabilities=[["gpu"]])]
            container = client.containers.run(
                image_tag,
                command=command,
                environment=env,
                device_requests=device_requests,
                detach=True,
                remove=False,
            )
            try:
                for line in container.logs(stream=True, follow=True):
                    text = line.decode("utf-8", errors="replace")
                    with _RUNS_LOCK:
                        _RUNS[run_id]["logs"] += text
                result = container.wait()
                exit_code = int(result.get("StatusCode", 1))
                with _RUNS_LOCK:
                    _RUNS[run_id]["exit_code"] = exit_code
                    _RUNS[run_id]["finished_at_utc"] = _utc_now()
                    _RUNS[run_id]["status"] = "completed" if exit_code == 0 else "failed"
                    if exit_code != 0:
                        _RUNS[run_id]["error_hint"] = classify_error(_RUNS[run_id]["logs"])
                _update_model_runtime_status(
                    model_id=model_id,
                    smoke_ok=exit_code == 0,
                    image_tag=image_tag,
                    last_error=None if exit_code == 0 else f"smoke exited with code {exit_code}",
                    mark_verified=exit_code == 0,
                )
            finally:
                try:
                    container.remove(force=True)
                except DockerException:
                    pass
        except Exception as exc:
            with _RUNS_LOCK:
                _RUNS[run_id]["logs"] += f"\n[docker-smoke-error] {exc}\n"
                _RUNS[run_id]["exit_code"] = 1
                _RUNS[run_id]["finished_at_utc"] = _utc_now()
                _RUNS[run_id]["status"] = "failed"
                _RUNS[run_id]["error_hint"] = classify_error(_RUNS[run_id]["logs"])
            _update_model_runtime_status(
                model_id=model_id,
                smoke_ok=False,
                image_tag=image_tag,
                last_error=str(exc),
                mark_verified=False,
            )

    threading.Thread(target=_runner, daemon=True).start()
    return run_id


def _prepare_smoke_input(payload: SmokeRunRequest) -> Path:
    # Use user-provided input when available; otherwise generate a tiny synthetic sample.
    if payload.input_path:
        candidate = _resolve_user_path(payload.input_path)
        if candidate.exists():
            return candidate

    root = _workspace_root()
    sample_dir = root / ".onboarding_samples"
    sample_dir.mkdir(parents=True, exist_ok=True)
    if payload.input_data_kind == "mesh":
        sample = sample_dir / "sample.obj"
        sample.write_text(
            "v 0 0 0\n"
            "v 1 0 0\n"
            "v 0 1 0\n"
            "f 1 2 3\n",
            encoding="utf-8",
        )
        return sample

    benchmark_sample = root / "data" / "benchmark_inputs" / "airplane.pcd"
    if benchmark_sample.exists():
        return benchmark_sample

    sample = sample_dir / "sample.pcd"
    sample.write_text(
        "# .PCD v0.7 - Point Cloud Data file format\n"
        "VERSION 0.7\n"
        "FIELDS x y z\n"
        "SIZE 4 4 4\n"
        "TYPE F F F\n"
        "COUNT 1 1 1\n"
        "WIDTH 4\n"
        "HEIGHT 1\n"
        "VIEWPOINT 0 0 0 1 0 0 0\n"
        "POINTS 4\n"
        "DATA ascii\n"
        "0.0 0.0 0.0\n"
        "1.0 0.0 0.0\n"
        "0.0 1.0 0.0\n"
        "0.0 0.0 1.0\n",
        encoding="utf-8",
    )
    return sample


@router.post("/validate", response_model=ValidateModelResponse)
def validate_model(payload: ValidateModelRequest) -> ValidateModelResponse:
    return _validate_request(payload)


@router.post("/preflight-scan")
def preflight_scan(payload: PreflightScanRequest) -> dict[str, Any]:
    return _scan_preflight(payload)


@router.post("/scaffold")
def scaffold_model(payload: ScaffoldModelRequest) -> dict[str, Any]:
    validation = _validate_request(payload)
    if not validation.valid:
        raise HTTPException(status_code=422, detail={"errors": validation.errors, "warnings": validation.warnings})

    root = _workspace_root()
    repo = _resolve_user_path(payload.repo_path)
    target_dir = root / "workers" / payload.task_type / payload.model_id
    _debug_log("H1", "scaffold called", {"target_dir": str(target_dir), "exists": target_dir.exists(), "overwrite": payload.overwrite})
    if target_dir.exists() and not payload.overwrite:
        raise HTTPException(
            status_code=409,
            detail=f"Target folder already exists: {target_dir}. Set overwrite=true to replace with backup.",
        )
    if target_dir.exists() and payload.overwrite:
        _backup_if_exists(target_dir)

    cmd = [
        "python",
        "workers/base/create_model_adapter.py",
        "--task-type",
        payload.task_type,
        "--model-id",
        payload.model_id,
        "--repo-path",
        payload.repo_path,
        "--entry-command",
        _guess_entry_command(payload),
        "--weights-path",
        payload.weights_path,
        "--config-path",
        payload.config_path,
        "--input-format",
        ",".join(validation.normalized["input_formats"]),
        "--output-format",
        ",".join(validation.normalized["output_formats"]),
        "--description",
        payload.description,
    ]
    result = subprocess.run(cmd, cwd=str(root), capture_output=True, text=True)
    if result.returncode != 0:
        logs = (result.stdout or "") + "\n" + (result.stderr or "")
        raise HTTPException(status_code=500, detail={"message": "Scaffold generation failed", "logs": logs})

    manifest_path = target_dir / "runtime.manifest.yaml"
    resolved_pips, resolved_reqs, resolved_system = _normalize_dependency_inputs(
        repo_path=payload.repo_path,
        extra_pip_packages=payload.extra_pip_packages,
        pip_requirements_files=payload.pip_requirements_files,
        system_packages=payload.system_packages,
    )
    detected_build_steps = _collect_build_step_hints(repo)
    effective_build_steps = payload.extra_build_steps if payload.extra_build_steps else detected_build_steps
    effective_base_image = payload.base_image.strip()
    if detected_build_steps:
        for pkg in ("ninja-build", "cmake"):
            if pkg not in resolved_system:
                resolved_system.append(pkg)
    _patch_runtime_manifest(
        manifest_path,
        extra_pip_packages=resolved_pips,
        pip_requirements_files=resolved_reqs,
        pip_extra_args=payload.pip_extra_args,
        system_packages=resolved_system,
        base_image=effective_base_image,
        extra_build_steps=effective_build_steps,
        env_overrides=payload.env_overrides,
    )
    _patch_dockerfile_base_image(target_dir / "Dockerfile", effective_base_image)
    # Ensure model card exists in DB before writing runtime status (FK-safe).
    db = SessionLocal()
    try:
        scan_model_cards(db, root)
    finally:
        db.close()
    _update_model_runtime_status(
        model_id=payload.model_id,
        build_ok=False,
        smoke_ok=False,
        manifest_hash=_manifest_hash(root, payload.task_type, payload.model_id),
        last_error=None,
        mark_verified=False,
    )

    return {
        "status": "ok",
        "target_dir": str(target_dir),
        "stdout": result.stdout,
        "warnings": validation.warnings,
        "autodetected_build_steps": effective_build_steps,
        "autodetected_base_image": effective_base_image,
    }


@router.post("/build")
def build_model(payload: BuildRequest) -> dict[str, str]:
    root = _workspace_root()
    source_dockerfile = root / "workers" / payload.task_type / payload.model_id / "Dockerfile"
    if not source_dockerfile.exists():
        raise HTTPException(status_code=404, detail=f"Dockerfile not found: {source_dockerfile}")
    stage_dir, dockerfile = _prepare_build_context(root, payload.task_type, payload.model_id)
    if not dockerfile.exists():
        raise HTTPException(status_code=404, detail=f"Dockerfile not found in stage: {dockerfile}")
    image_tag = payload.image_tag or f"pcpp-{payload.task_type}-{payload.model_id}:gpu"
    run_id = _start_docker_build_run(
        tag=image_tag,
        dockerfile=dockerfile,
        root=stage_dir,
        model_id=payload.model_id,
        task_type=payload.task_type,
        no_cache=payload.no_cache,
        cleanup_path=stage_dir,
    )
    return {"run_id": run_id, "status": "running"}


@router.post("/smoke-run")
def smoke_run(payload: SmokeRunRequest) -> dict[str, str]:
    image_tag = payload.image_tag or f"pcpp-{payload.task_type}-{payload.model_id}:gpu"
    module_name = f"workers.{payload.task_type}.{payload.model_id}.worker"
    db = SessionLocal()
    try:
        card = db.get(ModelCard, payload.model_id)
        if card:
            source = Path(card.source_path)
            parts = list(source.parts)
            if "workers" in parts:
                i = parts.index("workers")
                if len(parts) >= i + 4:
                    module_name = f"workers.{parts[i + 1]}.{parts[i + 2]}.worker"
    finally:
        db.close()
    run_id = _start_docker_smoke_run(
        image_tag=image_tag,
        module_name=module_name,
        input_data_kind=payload.input_data_kind,
        use_gpu=payload.use_gpu,
        model_args=(payload.model_args or []) + _clean_cli_tokens(payload.smoke_args),
        model_id=payload.model_id,
    )
    return {"run_id": run_id, "status": "running"}


@router.get("/runs/{run_id}", response_model=RunStatusResponse)
def get_run_status(run_id: str) -> RunStatusResponse:
    with _RUNS_LOCK:
        run = _RUNS.get(run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")
    return RunStatusResponse(**run)


@router.post("/command")
def run_command(payload: ActionRunRequest) -> dict[str, str]:
    root = _workspace_root()
    cwd = _resolve_user_path(payload.cwd) if payload.cwd else root
    run_id = _start_run("command", payload.command, cwd)
    return {"run_id": run_id, "status": "running"}


@router.post("/cleanup")
def cleanup_scaffold(payload: CleanupRequest) -> dict[str, str]:
    root = _workspace_root()
    target_dir = (root / "workers" / payload.task_type / payload.model_id).resolve()
    workers_root = (root / "workers").resolve()
    if workers_root not in target_dir.parents:
        raise HTTPException(status_code=400, detail="Invalid cleanup target.")
    if target_dir.exists():
        shutil.rmtree(target_dir)
        return {"status": "deleted", "target_dir": str(target_dir)}
    return {"status": "not_found", "target_dir": str(target_dir)}


@router.post("/cleanup-backups")
def cleanup_backups(payload: CleanupBackupsRequest) -> dict[str, Any]:
    root = _workspace_root()
    now = datetime.now(timezone.utc)
    matched = _collect_backup_dirs(root, task_type=payload.task_type, model_id=payload.model_id)
    selected: list[Path] = []
    for item in matched:
        if payload.older_than_hours <= 0:
            selected.append(item)
            continue
        mtime = datetime.fromtimestamp(item.stat().st_mtime, tz=timezone.utc)
        age_hours = (now - mtime).total_seconds() / 3600.0
        if age_hours >= payload.older_than_hours:
            selected.append(item)

    deleted: list[str] = []
    if payload.apply:
        for item in selected:
            shutil.rmtree(item, ignore_errors=True)
            deleted.append(str(item))
    result = {
        "status": "ok",
        "dry_run": not payload.apply,
        "matched_count": len(matched),
        "selected_count": len(selected),
        "paths": [str(p) for p in selected] if not payload.apply else deleted,
    }
    _debug_log("H5", "cleanup backups evaluated", {"apply": payload.apply, "matched": len(matched), "selected": len(selected)})
    return result


@router.post("/registry-check")
def registry_check(payload: RegistryCheckRequest) -> dict[str, Any]:
    db = SessionLocal()
    try:
        card = db.query(ModelCard).filter(ModelCard.id == payload.model_id).first()
        status = db.get(ModelRuntimeStatus, payload.model_id)
    finally:
        db.close()
    ready = bool(status and status.build_ok and status.smoke_ok)
    reason = None
    if card is None:
        reason = "model_not_registered"
    elif status is None:
        reason = "model_not_verified"
    elif not status.build_ok:
        reason = "build_not_successful"
    elif not status.smoke_ok:
        reason = "smoke_not_successful"
    return {
        "registered": card is not None,
        "ready": ready,
        "reason": reason,
        "model_id": payload.model_id,
    }


@router.post("/registry-reconcile")
def registry_reconcile() -> dict[str, Any]:
    root = _workspace_root()
    db = SessionLocal()
    try:
        found = scan_model_cards(db, root)
    finally:
        db.close()
    return {"status": "ok", "found": found}
