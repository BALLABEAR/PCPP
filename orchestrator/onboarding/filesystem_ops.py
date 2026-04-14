import shutil
import tempfile
from datetime import datetime
from fnmatch import fnmatch
from pathlib import Path
from typing import Callable

import yaml


def copy_tree(src: Path, dst: Path) -> None:
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


def read_model_repo_path(root: Path, task_type: str, model_id: str) -> str | None:
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


def prepare_build_context(
    *,
    root: Path,
    task_type: str,
    model_id: str,
    resolve_user_path: Callable[[str], Path],
) -> tuple[Path, Path]:
    stage_dir = Path(tempfile.mkdtemp(prefix=f"pcpp_build_{task_type}_{model_id}_"))
    workers_dst = stage_dir / "workers"
    workers_dst.mkdir(parents=True, exist_ok=True)
    (stage_dir / "external_models").mkdir(parents=True, exist_ok=True)

    copy_tree(root / "workers" / "__init__.py", workers_dst / "__init__.py")
    copy_tree(root / "workers" / "base", workers_dst / "base")
    copy_tree(root / "workers" / task_type / "__init__.py", workers_dst / task_type / "__init__.py")
    copy_tree(root / "workers" / task_type / model_id, workers_dst / task_type / model_id)

    repo_path_raw = read_model_repo_path(root, task_type, model_id)
    if repo_path_raw:
        repo_path = resolve_user_path(repo_path_raw)
        external_root = (root / "external_models").resolve()
        if repo_path.exists() and repo_path.is_dir():
            if external_root in repo_path.parents or repo_path == external_root:
                rel = repo_path.relative_to(external_root)
                copy_tree(repo_path, stage_dir / "external_models" / rel)
            else:
                copy_tree(repo_path, stage_dir / "external_models" / repo_path.name)

    dockerfile = stage_dir / "workers" / task_type / model_id / "Dockerfile"
    return stage_dir, dockerfile


def collect_backup_dirs(root: Path, *, task_type: str | None, model_id: str | None) -> list[Path]:
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


def backup_if_exists(target: Path) -> None:
    if not target.exists():
        return
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup = target.with_name(f"{target.name}.bak_{stamp}")
    shutil.move(str(target), str(backup))
