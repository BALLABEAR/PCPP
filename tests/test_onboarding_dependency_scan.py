from pathlib import Path

from orchestrator.api.onboarding import _collect_build_step_hints, _normalize_dependency_inputs


def test_normalize_dependency_inputs_keeps_requirement_files(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir(parents=True, exist_ok=True)
    (repo / "requirements.txt").write_text("-r requirements-dev.txt\nnumpy==1.26.4\n", encoding="utf-8")
    (repo / "requirements-dev.txt").write_text("scipy==1.11.4\n", encoding="utf-8")
    packages, req_files, system = _normalize_dependency_inputs(
        repo_path=str(repo),
        extra_pip_packages=[],
        pip_requirements_files=["requirements.txt"],
        system_packages=[],
    )
    assert "numpy==1.26.4" in packages
    assert "scipy==1.11.4" in packages
    assert any(item.endswith("external_models/repo/requirements.txt") for item in req_files)
    assert any(item.endswith("external_models/repo/requirements-dev.txt") for item in req_files)
    assert isinstance(system, list)


def test_collect_build_step_hints_detects_extension_setup(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    ext_dir = repo / "extensions" / "chamfer_dist"
    ext_dir.mkdir(parents=True, exist_ok=True)
    (ext_dir / "setup.py").write_text("from setuptools import setup\nsetup()\n", encoding="utf-8")
    hints = _collect_build_step_hints(repo)
    assert any("python setup.py install" in item for item in hints)
