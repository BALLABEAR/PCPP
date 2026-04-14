import configparser
import re
from pathlib import Path
from typing import Callable

try:
    import tomllib
except ModuleNotFoundError:
    tomllib = None

OPENCV_SYSTEM_PACKAGES = [
    "libglib2.0-0",
    "libgl1",
    "libsm6",
    "libxext6",
    "libxrender1",
]


def read_text_safe(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return ""


def parse_requirements_file(path: Path, visited: set[Path] | None = None) -> tuple[list[str], list[str]]:
    packages: list[str] = []
    requirement_files: list[str] = []
    visited = visited or set()
    real_path = path.resolve()
    if real_path in visited:
        return packages, requirement_files
    visited.add(real_path)
    requirement_files.append(str(path))
    for raw in read_text_safe(path).splitlines():
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
                nested_packages, nested_files = parse_requirements_file(ref_path, visited=visited)
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


def collect_project_dependencies(repo: Path) -> tuple[list[str], list[str]]:
    discovered_packages: list[str] = []
    discovered_reqs: list[str] = []
    req_names = {"requirements.txt", "requirements-dev.txt", "requirements.in"}
    for req in repo.rglob("*"):
        if not req.is_file():
            continue
        if req.name in req_names or (req.name.startswith("requirements") and req.suffix == ".txt"):
            req_packages, req_files = parse_requirements_file(req)
            discovered_packages.extend(req_packages)
            discovered_reqs.extend(req_files)

    pyproject = repo / "pyproject.toml"
    if pyproject.exists() and tomllib is not None:
        try:
            payload = tomllib.loads(read_text_safe(pyproject))
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
            parser.read_string(read_text_safe(setup_cfg))
            if parser.has_option("options", "install_requires"):
                raw = parser.get("options", "install_requires")
                discovered_packages.extend([line.strip() for line in raw.splitlines() if line.strip()])
        except Exception:
            pass

    setup_py = repo / "setup.py"
    if setup_py.exists():
        text = read_text_safe(setup_py)
        match = re.search(r"install_requires\s*=\s*\[(.*?)\]", text, flags=re.DOTALL)
        if match:
            for dep in re.findall(r"['\"]([^'\"]+)['\"]", match.group(1)):
                discovered_packages.append(dep.strip())
    return discovered_packages, discovered_reqs


def collect_build_step_hints(repo: Path) -> list[str]:
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
            continue
        text = read_text_safe(setup_path).lower()
        looks_like_native_ext = any(key in text for key in ("cudaextension", "cppextension", "buildextension"))
        path_has_ext_hint = any(part in keyword_dirs for part in rel_parts)
        if looks_like_native_ext or path_has_ext_hint:
            ext_setup_candidates.append(setup_path)
    for setup_path in ext_setup_candidates:
        rel = setup_path.relative_to(repo).as_posix()
        hints.append(f"cd /app/external_models/{repo.name}/{Path(rel).parent.as_posix()} && python setup.py install")
    makefiles = [p for p in repo.rglob("Makefile") if "build" in read_text_safe(p).lower()]
    for makefile in makefiles[:3]:
        rel = makefile.relative_to(repo).as_posix()
        hints.append(f"cd /app/external_models/{repo.name}/{Path(rel).parent.as_posix()} && make")
    has_pointnet2_import = False
    for py in repo.rglob("*.py"):
        if "pointnet2_ops" in read_text_safe(py):
            has_pointnet2_import = True
            break
    has_local_pointnet2_setup = any("pointnet2" in p.as_posix().lower() for p in ext_setup_candidates)
    if has_pointnet2_import and not has_local_pointnet2_setup:
        hints.append(
            "python -m pip install --no-cache-dir --no-build-isolation "
            "git+https://github.com/erikwijmans/Pointnet2_PyTorch.git#subdirectory=pointnet2_ops_lib"
        )
    seen: set[str] = set()
    unique: list[str] = []
    for item in hints:
        if item not in seen:
            seen.add(item)
            unique.append(item)
    return unique


def normalize_dependency_inputs(
    *,
    repo_path: str,
    extra_pip_packages: list[str],
    pip_requirements_files: list[str],
    system_packages: list[str],
    resolve_user_path: Callable[[str], Path],
) -> tuple[list[str], list[str], list[str]]:
    repo = resolve_user_path(repo_path)
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
            req_packages, req_files = parse_requirements_file(req_path)
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

    auto_packages, _auto_req_files = collect_project_dependencies(repo)
    for pkg in auto_packages:
        _push(pkg)

    has_torch = any(_pkg_name(pkg) in {"torch", "torchvision"} for pkg in merged_packages)
    if not has_torch:
        torch_markers = 0
        for py_file in list(repo.rglob("*.py"))[:200]:
            content = read_text_safe(py_file)
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
        for pkg in OPENCV_SYSTEM_PACKAGES:
            if pkg not in merged_system:
                merged_system.append(pkg)

    return merged_packages, merged_requirements, merged_system
