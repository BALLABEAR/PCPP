import importlib
import io
import json
import os
import hashlib
import tarfile
import tempfile
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import boto3
from botocore.config import Config
from prefect import get_run_logger, task


def s3_client():
    return boto3.client(
        "s3",
        endpoint_url=os.getenv("MINIO_ENDPOINT", "http://minio:9000"),
        aws_access_key_id=os.getenv("MINIO_ROOT_USER", "pcpp_minio"),
        aws_secret_access_key=os.getenv("MINIO_ROOT_PASSWORD", "pcpp_minio_secret"),
        config=Config(signature_version="s3v4"),
        region_name="us-east-1",
    )


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def parse_utc(value: str | None) -> datetime | None:
    if not value:
        return None
    normalized = value.replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(normalized)
    except ValueError:
        return None


def gpu_memory_snapshot_mb() -> int | None:
    try:
        import subprocess

        raw = subprocess.check_output(
            "nvidia-smi --query-gpu=memory.used --format=csv,noheader,nounits",
            shell=True,
            text=True,
        ).strip()
        values = [int(line.strip()) for line in raw.splitlines() if line.strip()]
        return max(values) if values else None
    except Exception:
        return None


def docker_client():
    import docker

    return docker.from_env()


def repo_root_path() -> str:
    return os.getenv("WORKSPACE_ROOT", "/app")


def docker_image_exists(tag: str) -> bool:
    client = docker_client()
    try:
        client.images.get(tag)
        return True
    except Exception:
        return False


def _debug_log(hypothesis_id: str, message: str, data: dict[str, Any] | None = None, run_id: str = "flow-common") -> None:
    # #region agent log
    payload = {
        "sessionId": "e69ff4",
        "runId": run_id,
        "hypothesisId": hypothesis_id,
        "location": "flows/common.py",
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


def _append_task_log(task_id: str, message: str) -> None:
    try:
        from orchestrator.prefect_client import append_task_log

        append_task_log(task_id, message)
    except Exception:
        # Keep flow execution resilient even if log plumbing fails.
        pass


def ensure_shared_runtime_image(client, docker_build_context: str) -> None:
    runtime_tag = "pcpp-runtime-cuda118:latest"
    _debug_log("H8", "ensure_shared_runtime_image enter", {"runtime_tag": runtime_tag, "context": docker_build_context})
    if docker_image_exists(runtime_tag):
        _debug_log("H8", "shared runtime already exists", {"runtime_tag": runtime_tag})
        return
    runtime_dockerfile = str(Path(repo_root_path()) / "workers" / "base" / "runtime" / "Dockerfile.cuda118")
    started = time.perf_counter()
    client.images.build(
        path=docker_build_context,
        dockerfile=runtime_dockerfile,
        tag=runtime_tag,
        rm=True,
        pull=False,
    )
    _debug_log("H8", "shared runtime built", {"runtime_tag": runtime_tag, "seconds": round(time.perf_counter() - started, 3)})


def cli_args_from_mapping(cli_args: dict[str, object] | None) -> list[str]:
    if not cli_args:
        return []
    args: list[str] = []
    for key, value in cli_args.items():
        flag = f"--{key}"
        if isinstance(value, bool):
            if value:
                args.append(flag)
            continue
        if value is None:
            continue
        args.extend([flag, str(value)])
    return args


def _manifest_hash_for_step(step: dict[str, Any]) -> str | None:
    model_id = step.get("model_id")
    task_type = step.get("task_type")
    if not model_id or not task_type:
        return None
    manifest_path = Path(repo_root_path()) / "workers" / str(task_type) / str(model_id) / "runtime.manifest.yaml"
    if not manifest_path.exists():
        return None
    return hashlib.sha256(manifest_path.read_bytes()).hexdigest()


def _freshness_force_rebuild(step: dict[str, Any]) -> bool:
    model_id = step.get("model_id")
    if not model_id:
        return False
    try:
        from orchestrator.models import SessionLocal
        from orchestrator.models.model_runtime_status import ModelRuntimeStatus
    except Exception:
        return False
    current_hash = _manifest_hash_for_step(step)
    db = SessionLocal()
    try:
        status = db.get(ModelRuntimeStatus, str(model_id))
    finally:
        db.close()
    if not status:
        return False
    if status.manifest_hash and current_hash and status.manifest_hash != current_hash:
        _append_task_log(
            str(step.get("task_id", "unknown")),
            f"[docker] manifest hash changed for model {model_id}; forcing image rebuild",
        )
        return True
    return False


def run_worker_in_docker(
    *,
    task_id: str,
    input_path: Path,
    output_dir: Path,
    worker_module: str,
    dockerfile_path: str,
    image_tag: str,
    cli_args: dict[str, object] | None,
    docker_build: bool = True,
    docker_force_rebuild: bool = False,
    docker_build_context: str | None = None,
    use_gpu: bool = True,
) -> tuple[Path, dict[str, Any]]:
    from docker.types import DeviceRequest

    client = docker_client()
    resolved_context = docker_build_context or repo_root_path()
    dockerfile_for_build = dockerfile_path
    dockerfile_path_obj = Path(dockerfile_path)
    context_obj = Path(resolved_context)
    if dockerfile_path_obj.is_absolute() and context_obj in dockerfile_path_obj.parents:
        dockerfile_for_build = dockerfile_path_obj.relative_to(context_obj).as_posix()
    _debug_log("H7", "run_worker_in_docker enter", {"task_id": task_id, "image_tag": image_tag, "docker_build": docker_build}, run_id=task_id)
    _append_task_log(task_id, f"[docker] Preparing image '{image_tag}'")
    ensure_shared_runtime_image(client, resolved_context)
    _debug_log("H7", "shared runtime check done", {"task_id": task_id, "image_tag": image_tag}, run_id=task_id)

    image_cache_hit = docker_image_exists(image_tag)
    image_build_seconds = 0.0
    built_now = False
    if docker_build and (docker_force_rebuild or not image_cache_hit):
        _append_task_log(task_id, f"[docker] Building image '{image_tag}' (cache_hit_before={image_cache_hit})")
        build_started = time.perf_counter()
        client.images.build(
            path=resolved_context,
            dockerfile=dockerfile_for_build,
            tag=image_tag,
            rm=True,
            pull=False,
        )
        image_build_seconds = time.perf_counter() - build_started
        built_now = True
        _append_task_log(task_id, f"[docker] Build finished in {round(image_build_seconds, 2)}s")
    else:
        _append_task_log(
            task_id,
            f"[docker] Reusing image '{image_tag}' (cache_hit={image_cache_hit}, force_rebuild={docker_force_rebuild})",
        )
    _debug_log(
        "H7",
        "docker build decision",
        {
            "task_id": task_id,
            "image_tag": image_tag,
            "docker_build": docker_build,
            "image_cache_hit_before": image_cache_hit,
            "built_now": built_now,
            "image_build_seconds": round(image_build_seconds, 3),
        },
        run_id=task_id,
    )

    container_name = f"pcpp-step-{uuid.uuid4().hex[:12]}"
    in_container_input = f"/tmp/{input_path.name}"
    in_container_output_dir = "/tmp/out"
    worker_command = [
        "python",
        "-m",
        worker_module,
        "--input",
        in_container_input,
        "--output-dir",
        in_container_output_dir,
    ] + cli_args_from_mapping(cli_args)

    device_requests = [DeviceRequest(count=-1, capabilities=[["gpu"]])] if use_gpu else None
    container = client.containers.create(
        image=image_tag,
        command=worker_command,
        name=container_name,
        detach=True,
        device_requests=device_requests,
        labels={"pcpp.task_id": task_id, "pcpp.worker_module": worker_module},
    )
    try:
        _append_task_log(task_id, f"[docker] Starting worker container '{worker_module}'")
        in_tar_stream = io.BytesIO()
        with tarfile.open(fileobj=in_tar_stream, mode="w") as tar:
            data = input_path.read_bytes()
            tarinfo = tarfile.TarInfo(name=input_path.name)
            tarinfo.size = len(data)
            tar.addfile(tarinfo, io.BytesIO(data))
        in_tar_stream.seek(0)
        container.put_archive("/tmp", in_tar_stream.read())

        container.start()
        status = container.wait()
        status_code = int(status.get("StatusCode", 1))
        if status_code != 0:
            logs = container.logs(stdout=True, stderr=True).decode("utf-8", errors="ignore")
            _append_task_log(task_id, f"[docker] Worker failed with exit={status_code}")
            raise RuntimeError(f"Worker container exited with code {status_code}. Logs:\n{logs}")

        stream, _ = container.get_archive(in_container_output_dir)
        out_tar = b"".join(chunk for chunk in stream)
        raw_out = output_dir / "raw_container_out"
        raw_out.mkdir(parents=True, exist_ok=True)
        with tarfile.open(fileobj=io.BytesIO(out_tar), mode="r:*") as tar:
            tar.extractall(path=raw_out)

        produced_files = [p for p in raw_out.rglob("*") if p.is_file()]
        if not produced_files:
            raise RuntimeError("Worker container finished but produced no output files")

        latest = max(produced_files, key=lambda p: p.stat().st_mtime)
        final_output = output_dir / latest.name
        final_output.write_bytes(latest.read_bytes())
        _append_task_log(task_id, f"[docker] Worker output ready: {final_output.name}")
        return final_output, {
            "image_cache_hit": image_cache_hit,
            "image_build_seconds": round(image_build_seconds, 3),
            "image_tag": image_tag,
        }
    finally:
        try:
            container.remove(force=True)
        except Exception:
            pass


@task(name="test_worker_step")
def run_test_worker(task_id: str, input_bucket: str, input_key: str, result_bucket: str) -> str:
    logger = get_run_logger()
    s3 = s3_client()

    suffix = Path(input_key).suffix
    output_key = f"results/{task_id}/processed{suffix or '.bin'}"

    with tempfile.TemporaryDirectory() as tmp_dir:
        local_in = Path(tmp_dir) / f"input{suffix or '.bin'}"
        local_out = Path(tmp_dir) / f"output{suffix or '.bin'}"

        logger.info("Downloading input s3://%s/%s", input_bucket, input_key)
        s3.download_file(input_bucket, input_key, str(local_in))
        time.sleep(5)
        local_out.write_bytes(local_in.read_bytes())
        logger.info("Uploading result s3://%s/%s", result_bucket, output_key)
        s3.upload_file(str(local_out), result_bucket, output_key)

    return output_key


@task(name="stage_worker_step")
def run_worker_step(
    task_id: str,
    input_bucket: str,
    input_key: str,
    result_bucket: str,
    step_name: str,
    worker_module: str,
    worker_class: str,
    worker_kwargs: dict | None = None,
    output_prefix: str = "intermediate",
    execution_mode: str = "local",
    dockerfile_path: str | None = None,
    image_tag: str | None = None,
    cli_args: dict | None = None,
    docker_build: bool = True,
    docker_force_rebuild: bool = False,
    docker_build_context: str | None = None,
    use_gpu: bool = True,
) -> dict:
    logger = get_run_logger()
    s3 = s3_client()
    suffix = Path(input_key).suffix
    worker_kwargs = worker_kwargs or {}

    image_cache_hit: bool | None = None
    image_build_seconds: float | None = None
    build_image_tag: str | None = None
    step_started_utc = utc_now()

    with tempfile.TemporaryDirectory() as tmp_dir:
        local_input = Path(tmp_dir) / f"input{suffix or '.bin'}"
        local_out_dir = Path(tmp_dir) / "worker_out"

        logger.info("Step %s: downloading s3://%s/%s", step_name, input_bucket, input_key)
        _append_task_log(task_id, f"[step:{step_name}] downloading input {input_key}")
        s3.download_file(input_bucket, input_key, str(local_input))

        started = time.perf_counter()
        if execution_mode == "docker":
            if not dockerfile_path or not image_tag:
                raise ValueError("dockerfile_path and image_tag are required for execution_mode=docker")
            output_local, build_info = run_worker_in_docker(
                task_id=task_id,
                input_path=local_input,
                output_dir=local_out_dir,
                worker_module=worker_module,
                dockerfile_path=dockerfile_path,
                image_tag=image_tag,
                cli_args=cli_args,
                docker_build=docker_build,
                docker_force_rebuild=docker_force_rebuild,
                docker_build_context=docker_build_context,
                use_gpu=use_gpu,
            )
            image_cache_hit = bool(build_info["image_cache_hit"])
            image_build_seconds = float(build_info["image_build_seconds"])
            build_image_tag = str(build_info["image_tag"])
        else:
            module = importlib.import_module(worker_module)
            worker_cls = getattr(module, worker_class)
            worker = worker_cls(**worker_kwargs)
            output_local = Path(worker.run(str(local_input), str(local_out_dir)))
        elapsed = time.perf_counter() - started

        output_suffix = output_local.suffix or ".bin"
        step_key = f"{output_prefix}/{step_name}{output_suffix}"
        logger.info("Step %s: uploading s3://%s/%s", step_name, result_bucket, step_key)
        _append_task_log(task_id, f"[step:{step_name}] uploading output {step_key}")
        s3.upload_file(str(output_local), result_bucket, step_key)

    return {
        "step_name": step_name,
        "output_bucket": result_bucket,
        "output_key": step_key,
        "elapsed_seconds": round(elapsed, 3),
        "gpu_memory_mb": gpu_memory_snapshot_mb(),
        "worker_module": worker_module,
        "worker_class": worker_class,
        "execution_mode": execution_mode,
        "image_cache_hit": image_cache_hit,
        "image_build_seconds": image_build_seconds,
        "image_tag": build_image_tag,
        "started_at_utc": step_started_utc,
        "finished_at_utc": utc_now(),
    }


def execute_pipeline(
    *,
    flow_id: str,
    task_id: str,
    input_bucket: str,
    input_key: str,
    result_bucket: str,
    pipeline_steps: list[dict[str, Any]],
    input_keys: list[str] | None = None,
    task_created_at_utc: str | None = None,
) -> str:
    logger = get_run_logger()
    flow_started_at_utc = utc_now()
    flow_started = time.perf_counter()
    s3 = s3_client()
    run_inputs = input_keys if input_keys else [input_key]
    items_metrics: list[dict[str, Any]] = []

    is_batch_mode = len(run_inputs) > 1
    for idx, current_input_key in enumerate(run_inputs, start=1):
        _append_task_log(task_id, f"[pipeline] item {idx}/{len(run_inputs)} started: {current_input_key}")
        item_started = time.perf_counter()
        item_prefix = f"intermediate/{task_id}/items/{idx:03d}" if is_batch_mode else f"intermediate/{task_id}"
        current_bucket = input_bucket
        current_key = current_input_key
        steps_metrics: list[dict[str, Any]] = []

        for step_i, step in enumerate(pipeline_steps, start=1):
            step_name = step.get("name") or f"step_{step_i:02d}"
            step = {**step, "task_id": task_id}
            force_rebuild = bool(step.get("docker_force_rebuild", False)) or _freshness_force_rebuild(step)
            step_result = run_worker_step.with_options(name=f"{flow_id}-{step_name}-{idx:03d}")(
                task_id=task_id,
                input_bucket=current_bucket,
                input_key=current_key,
                result_bucket=result_bucket,
                step_name=step_name,
                worker_module=step["worker_module"],
                worker_class=step["worker_class"],
                worker_kwargs=step.get("worker_kwargs") or {},
                output_prefix=item_prefix,
                execution_mode=step.get("execution_mode", "local"),
                dockerfile_path=step.get("dockerfile_path"),
                image_tag=step.get("image_tag"),
                cli_args=step.get("cli_args") or {},
                docker_build=step.get("docker_build", True),
                docker_force_rebuild=force_rebuild,
                docker_build_context=step.get("docker_build_context") or repo_root_path(),
                use_gpu=step.get("use_gpu", True),
            )
            steps_metrics.append(step_result)
            current_bucket = step_result["output_bucket"]
            current_key = step_result["output_key"]
            _append_task_log(task_id, f"[pipeline] step finished: {step_name} ({step_result['elapsed_seconds']}s)")

        final_suffix = Path(current_key).suffix or ".bin"
        item_result_key = (
            f"results/{task_id}/items/{idx:03d}/pipeline_output{final_suffix}"
            if is_batch_mode
            else f"results/{task_id}/pipeline_output{final_suffix}"
        )
        s3.copy_object(
            Bucket=result_bucket,
            CopySource={"Bucket": current_bucket, "Key": current_key},
            Key=item_result_key,
        )
        item_elapsed = time.perf_counter() - item_started
        items_metrics.append(
            {
                "index": idx,
                "input_key": current_input_key,
                "result_key": item_result_key,
                "elapsed_seconds": round(item_elapsed, 3),
                "steps": steps_metrics,
            }
        )
        logger.info("Item %s/%s completed: %s", idx, len(run_inputs), item_result_key)
        _append_task_log(task_id, f"[pipeline] item {idx}/{len(run_inputs)} completed: {item_result_key}")

    flow_elapsed = time.perf_counter() - flow_started
    files_total = len(run_inputs)
    throughput_files_per_sec = files_total / flow_elapsed if flow_elapsed > 0 else None
    build_seconds = [
        step.get("image_build_seconds", 0.0) or 0.0
        for item in items_metrics
        for step in item.get("steps", [])
        if step.get("image_build_seconds") is not None
    ]
    cache_hits = sum(
        1
        for item in items_metrics
        for step in item.get("steps", [])
        if step.get("image_cache_hit") is True
    )
    docker_steps_total = sum(
        1
        for item in items_metrics
        for step in item.get("steps", [])
        if step.get("execution_mode") == "docker"
    )

    queue_delay_seconds: float | None = None
    created_at = parse_utc(task_created_at_utc)
    started_at = parse_utc(flow_started_at_utc)
    if created_at and started_at:
        queue_delay_seconds = round((started_at - created_at).total_seconds(), 3)

    if len(items_metrics) == 1:
        final_result_key = items_metrics[0]["result_key"]
    else:
        manifest_key = f"results/{task_id}/batch_manifest.json"
        s3.put_object(
            Bucket=result_bucket,
            Key=manifest_key,
            Body=json.dumps(
                {
                    "task_id": task_id,
                    "flow_id": flow_id,
                    "items": [
                        {"index": item["index"], "input_key": item["input_key"], "result_key": item["result_key"]}
                        for item in items_metrics
                    ],
                },
                ensure_ascii=False,
                indent=2,
            ).encode("utf-8"),
            ContentType="application/json",
        )
        final_result_key = manifest_key

    metrics_payload = {
        "task_id": task_id,
        "flow_id": flow_id,
        "task_created_at_utc": task_created_at_utc,
        "flow_started_at_utc": flow_started_at_utc,
        "flow_finished_at_utc": utc_now(),
        "queue_delay_seconds": queue_delay_seconds,
        "elapsed_seconds": round(flow_elapsed, 3),
        "input_bucket": input_bucket,
        "input_key": input_key,
        "input_keys": run_inputs,
        "result_bucket": result_bucket,
        "result_key": final_result_key,
        "files_total": files_total,
        "throughput_files_per_second": round(throughput_files_per_sec, 4) if throughput_files_per_sec else None,
        "image_build_total_seconds": round(sum(build_seconds), 3),
        "image_cache_hits": cache_hits,
        "docker_steps_total": docker_steps_total,
        # Backward compatibility for single-file consumers.
        "steps": items_metrics[0]["steps"] if len(items_metrics) == 1 else [],
        "items": items_metrics,
    }
    metrics_key = f"results/{task_id}/pipeline_metrics.json"
    s3.put_object(
        Bucket=result_bucket,
        Key=metrics_key,
        Body=json.dumps(metrics_payload, ensure_ascii=False, indent=2).encode("utf-8"),
        ContentType="application/json",
    )
    _append_task_log(task_id, f"[pipeline] metrics saved: {metrics_key}")
    return final_result_key
