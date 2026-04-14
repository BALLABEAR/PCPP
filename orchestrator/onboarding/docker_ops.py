import shutil
import uuid
from pathlib import Path
from typing import Any, Callable

import docker
from docker.errors import DockerException
from docker.types import DeviceRequest


def docker_image_exists(tag: str) -> bool:
    try:
        client = docker.from_env()
        client.images.get(tag)
        return True
    except Exception:
        return False


def ensure_shared_runtime_for_build(
    *,
    run_id: str,
    root: Path,
    dockerfile: Path,
    runs: dict[str, dict[str, Any]],
    runs_lock,
) -> None:
    runtime_tag = "pcpp-runtime-cuda118:latest"
    fallback_base = "nvidia/cuda:11.8.0-cudnn8-devel-ubuntu22.04"
    content = dockerfile.read_text(encoding="utf-8")
    if "FROM pcpp-runtime-cuda118:latest" not in content:
        return
    if docker_image_exists(runtime_tag):
        with runs_lock:
            runs[run_id]["logs"] += f"[build] shared runtime hit: {runtime_tag}\n"
        return
    with runs_lock:
        runs[run_id]["logs"] += f"[build] shared runtime miss: {runtime_tag}, building it now...\n"
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
                with runs_lock:
                    runs[run_id]["logs"] += line
            if "error" in chunk:
                raise RuntimeError(str(chunk["error"]))
        with runs_lock:
            runs[run_id]["logs"] += f"[build] shared runtime built: {runtime_tag}\n"
    except Exception as exc:
        patched = content.replace("FROM pcpp-runtime-cuda118:latest", f"FROM {fallback_base}", 1)
        dockerfile.write_text(patched, encoding="utf-8")
        with runs_lock:
            runs[run_id]["logs"] += (
                f"[build] shared runtime build failed ({exc}); "
                f"fallback to base image: {fallback_base}\n"
            )


def start_docker_build_run(
    *,
    tag: str,
    dockerfile: Path,
    root: Path,
    model_id: str,
    task_type: str,
    no_cache: bool,
    cleanup_path: Path | None,
    runs: dict[str, dict[str, Any]],
    runs_lock,
    utc_now: Callable[[], str],
    classify_error: Callable[[str], dict[str, str] | None],
    update_model_runtime_status: Callable[..., None],
    manifest_hash: Callable[[str, str], str | None],
) -> str:
    run_id = uuid.uuid4().hex
    record = {
        "run_id": run_id,
        "kind": "build",
        "status": "pending",
        "command": ["docker-sdk", "build", "-t", tag, "-f", str(dockerfile)],
        "cwd": str(root),
        "logs": "",
        "started_at_utc": utc_now(),
        "finished_at_utc": None,
        "exit_code": None,
        "error_hint": None,
    }
    with runs_lock:
        runs[run_id] = record

    def _runner() -> None:
        with runs_lock:
            runs[run_id]["status"] = "running"
            runs[run_id]["logs"] += "[build] Starting docker build. Preparing context may take a while on large repos.\n"
            runs[run_id]["logs"] += f"[build] cache mode: {'disabled' if no_cache else 'enabled'} (cache_from={tag})\n"
        try:
            ensure_shared_runtime_for_build(
                run_id=run_id,
                root=root,
                dockerfile=dockerfile,
                runs=runs,
                runs_lock=runs_lock,
            )
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
                    with runs_lock:
                        runs[run_id]["logs"] += line
                if "error" in chunk:
                    raise RuntimeError(str(chunk["error"]))
            with runs_lock:
                runs[run_id]["exit_code"] = 0
                runs[run_id]["finished_at_utc"] = utc_now()
                runs[run_id]["status"] = "completed"
            update_model_runtime_status(
                model_id=model_id,
                build_ok=True,
                smoke_ok=False,
                image_tag=tag,
                manifest_hash=manifest_hash(task_type, model_id),
                last_error=None,
                mark_verified=False,
            )
        except Exception as exc:
            with runs_lock:
                runs[run_id]["logs"] += f"\n[docker-build-error] {exc}\n"
                runs[run_id]["exit_code"] = 1
                runs[run_id]["finished_at_utc"] = utc_now()
                runs[run_id]["status"] = "failed"
                runs[run_id]["error_hint"] = classify_error(runs[run_id]["logs"])
            update_model_runtime_status(
                model_id=model_id,
                build_ok=False,
                image_tag=tag,
                manifest_hash=manifest_hash(task_type, model_id),
                last_error=str(exc),
                mark_verified=False,
            )
        finally:
            if cleanup_path and cleanup_path.exists():
                shutil.rmtree(cleanup_path, ignore_errors=True)

    import threading

    threading.Thread(target=_runner, daemon=True).start()
    return run_id


def start_docker_smoke_run(
    *,
    image_tag: str,
    module_name: str,
    input_data_kind: str,
    use_gpu: bool,
    model_args: list[str],
    model_id: str,
    runs: dict[str, dict[str, Any]],
    runs_lock,
    utc_now: Callable[[], str],
    classify_error: Callable[[str], dict[str, str] | None],
    update_model_runtime_status: Callable[..., None],
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
        "started_at_utc": utc_now(),
        "finished_at_utc": None,
        "exit_code": None,
        "error_hint": None,
    }
    with runs_lock:
        runs[run_id] = record

    def _runner() -> None:
        with runs_lock:
            runs[run_id]["status"] = "running"
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
                    with runs_lock:
                        runs[run_id]["logs"] += text
                result = container.wait()
                exit_code = int(result.get("StatusCode", 1))
                with runs_lock:
                    runs[run_id]["exit_code"] = exit_code
                    runs[run_id]["finished_at_utc"] = utc_now()
                    runs[run_id]["status"] = "completed" if exit_code == 0 else "failed"
                    if exit_code != 0:
                        runs[run_id]["error_hint"] = classify_error(runs[run_id]["logs"])
                update_model_runtime_status(
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
            with runs_lock:
                runs[run_id]["logs"] += f"\n[docker-smoke-error] {exc}\n"
                runs[run_id]["exit_code"] = 1
                runs[run_id]["finished_at_utc"] = utc_now()
                runs[run_id]["status"] = "failed"
                runs[run_id]["error_hint"] = classify_error(runs[run_id]["logs"])
            update_model_runtime_status(
                model_id=model_id,
                smoke_ok=False,
                image_tag=image_tag,
                last_error=str(exc),
                mark_verified=False,
            )

    import threading

    threading.Thread(target=_runner, daemon=True).start()
    return run_id
