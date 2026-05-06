from datetime import datetime, timezone
from pathlib import Path

import yaml

from orchestrator.models import SessionLocal
from orchestrator.models.model_runtime_status import ModelRuntimeStatus


def patch_runtime_manifest(
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

    def _pkg_name(pkg: str) -> str:
        import re

        token = re.split(r"[<>=!~ ]", pkg.strip(), maxsplit=1)[0]
        return token.lower()

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
            existing_pip = [str(pkg) for pkg in data["python"].get("pip", [])]
            data["python"]["pip"] = [pkg for pkg in existing_pip if _pkg_name(pkg) != "numpy"]
            data["python"]["pip"].append("numpy<2")
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
    build_text = " ".join(str(s) for s in (data.get("build_steps") or [])).lower()
    if "setup.py" in build_text and "TORCH_CUDA_ARCH_LIST" not in data["env"]:
        data["env"]["TORCH_CUDA_ARCH_LIST"] = "8.0"
    manifest_path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")


def patch_dockerfile_base_image(dockerfile_path: Path, base_image: str) -> None:
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


def manifest_hash(root: Path, task_type: str, model_id: str) -> str | None:
    import hashlib

    manifest_path = root / "workers" / task_type / model_id / "runtime.manifest.yaml"
    if not manifest_path.exists():
        return None
    return hashlib.sha256(manifest_path.read_bytes()).hexdigest()


def manifest_hash_for_model_card(source_path: str | Path) -> str | None:
    import hashlib

    card_path = Path(source_path)
    manifest_path = card_path.parent / "runtime.manifest.yaml"
    if not manifest_path.exists():
        return None
    return hashlib.sha256(manifest_path.read_bytes()).hexdigest()


def docker_image_exists(tag: str | None) -> bool:
    image_tag = str(tag or "").strip()
    if not image_tag:
        return False
    try:
        import docker

        client = docker.from_env()
        client.images.get(image_tag)
        return True
    except Exception:
        return False


def evaluate_runtime_readiness(
    status: ModelRuntimeStatus | None,
    *,
    current_manifest_hash: str | None = None,
) -> tuple[bool, str | None]:
    if status is None:
        return False, "model_not_verified"
    if not status.build_ok:
        return False, "build_not_successful"
    if not status.smoke_ok:
        return False, "smoke_not_successful"
    if current_manifest_hash and status.manifest_hash != current_manifest_hash:
        return False, "runtime_manifest_changed"
    if status.last_build_at and status.last_smoke_at and status.last_smoke_at < status.last_build_at:
        return False, "smoke_not_current"
    if not status.last_image_tag:
        return False, "runtime_image_missing"
    if not docker_image_exists(status.last_image_tag):
        return False, "runtime_image_missing"
    return True, None


def update_model_runtime_status(
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
