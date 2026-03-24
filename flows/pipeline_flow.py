import importlib
import io
import json
import os
import subprocess
import tempfile
import tarfile
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

import boto3
from botocore.config import Config
from prefect import flow, get_run_logger, task

from workers.completion.snowflake_net.worker import SnowflakeWorker
from workers.segmentation.fake_segmentation.worker import FakeSegmentationWorker


def _s3_client():
    return boto3.client(
        "s3",
        endpoint_url=os.getenv("MINIO_ENDPOINT", "http://minio:9000"),
        aws_access_key_id=os.getenv("MINIO_ROOT_USER", "pcpp_minio"),
        aws_secret_access_key=os.getenv("MINIO_ROOT_PASSWORD", "pcpp_minio_secret"),
        config=Config(signature_version="s3v4"),
        region_name="us-east-1",
    )


def _gpu_memory_snapshot_mb() -> int | None:
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


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _docker_client():
    import docker

    return docker.from_env()


def _docker_image_exists(tag: str) -> bool:
    client = _docker_client()
    try:
        client.images.get(tag)
        return True
    except Exception:
        return False


def _cli_args_from_mapping(cli_args: dict[str, object] | None) -> list[str]:
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


def _run_worker_in_docker(
    *,
    input_path: Path,
    output_dir: Path,
    worker_module: str,
    dockerfile_path: str,
    image_tag: str,
    cli_args: dict[str, object] | None,
    docker_build: bool = True,
    docker_build_context: str = "/app",
    use_gpu: bool = True,
) -> Path:
    import docker
    from docker.types import DeviceRequest

    client = _docker_client()
    if docker_build and not _docker_image_exists(image_tag):
        client.images.build(
            path=docker_build_context,
            dockerfile=dockerfile_path,
            tag=image_tag,
            rm=True,
            pull=False,
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
    ] + _cli_args_from_mapping(cli_args)

    device_requests = [DeviceRequest(count=-1, capabilities=[["gpu"]])] if use_gpu else None
    container = client.containers.create(
        image=image_tag,
        command=worker_command,
        name=container_name,
        detach=True,
        device_requests=device_requests,
    )
    try:
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
        return final_output
    finally:
        try:
            container.remove(force=True)
        except Exception:
            pass


@task(name="test_worker_step")
def run_test_worker(task_id: str, input_bucket: str, input_key: str, result_bucket: str) -> str:
    logger = get_run_logger()
    s3 = _s3_client()

    suffix = Path(input_key).suffix
    output_key = f"results/{task_id}/processed{suffix or '.bin'}"

    with tempfile.TemporaryDirectory() as tmp_dir:
        local_in = Path(tmp_dir) / f"input{suffix or '.bin'}"
        local_out = Path(tmp_dir) / f"output{suffix or '.bin'}"

        logger.info("Downloading input s3://%s/%s", input_bucket, input_key)
        s3.download_file(input_bucket, input_key, str(local_in))

        logger.info("Simulating worker processing (5 seconds)")
        time.sleep(5)

        local_out.write_bytes(local_in.read_bytes())

        logger.info("Uploading result s3://%s/%s", result_bucket, output_key)
        s3.upload_file(str(local_out), result_bucket, output_key)

    return output_key


@flow(name="stage2-test-flow", log_prints=True)
def stage2_test_flow(task_id: str, input_bucket: str, input_key: str, result_bucket: str) -> str:
    logger = get_run_logger()
    logger.info("Stage2 flow started for task %s", task_id)
    result_key = run_test_worker(task_id, input_bucket, input_key, result_bucket)
    logger.info("Stage2 flow completed for task %s", task_id)
    return result_key


@task(name="stage4_fake_segmentation_step")
def run_fake_segmentation_step(task_id: str, input_bucket: str, input_key: str, result_bucket: str) -> str:
    logger = get_run_logger()
    s3 = _s3_client()
    suffix = Path(input_key).suffix
    intermediate_key = f"intermediate/{task_id}/segmented{suffix or '.xyz'}"

    with tempfile.TemporaryDirectory() as tmp_dir:
        local_input = Path(tmp_dir) / f"input{suffix or '.xyz'}"
        local_stage_dir = Path(tmp_dir) / "segmentation_out"

        logger.info("Stage4 segmentation: downloading input s3://%s/%s", input_bucket, input_key)
        s3.download_file(input_bucket, input_key, str(local_input))

        segmented_local = Path(FakeSegmentationWorker().run(str(local_input), str(local_stage_dir)))
        logger.info("Stage4 segmentation: uploading intermediate s3://%s/%s", result_bucket, intermediate_key)
        s3.upload_file(str(segmented_local), result_bucket, intermediate_key)

    return intermediate_key


@task(name="stage4_completion_step")
def run_completion_step(
    task_id: str,
    result_bucket: str,
    intermediate_key: str,
    completion_mode: str = "passthrough",
    weights_path: str | None = None,
    config_path: str | None = None,
    device: str | None = None,
) -> str:
    logger = get_run_logger()
    s3 = _s3_client()
    suffix = Path(intermediate_key).suffix
    result_key = f"results/{task_id}/completed{suffix or '.xyz'}"

    with tempfile.TemporaryDirectory() as tmp_dir:
        local_input = Path(tmp_dir) / f"segmented{suffix or '.xyz'}"
        local_out_dir = Path(tmp_dir) / "completion_out"

        logger.info("Stage4 completion: downloading intermediate s3://%s/%s", result_bucket, intermediate_key)
        s3.download_file(result_bucket, intermediate_key, str(local_input))

        completion_worker = SnowflakeWorker(
            mode=completion_mode,
            weights_path=weights_path,
            config_path=config_path,
            device=device,
        )
        completed_local = Path(completion_worker.run(str(local_input), str(local_out_dir)))
        logger.info("Stage4 completion: uploading result s3://%s/%s", result_bucket, result_key)
        s3.upload_file(str(completed_local), result_bucket, result_key)

    return result_key


@flow(name="stage4-segmentation-completion-flow", log_prints=True)
def stage4_segmentation_completion_flow(
    task_id: str,
    input_bucket: str,
    input_key: str,
    result_bucket: str,
    completion_mode: str = "passthrough",
    weights_path: str | None = None,
    config_path: str | None = None,
    device: str | None = None,
) -> str:
    logger = get_run_logger()
    logger.info("Stage4 flow started for task %s", task_id)

    intermediate_key = run_fake_segmentation_step(task_id, input_bucket, input_key, result_bucket)
    result_key = run_completion_step(
        task_id=task_id,
        result_bucket=result_bucket,
        intermediate_key=intermediate_key,
        completion_mode=completion_mode,
        weights_path=weights_path,
        config_path=config_path,
        device=device,
    )

    logger.info("Stage4 flow completed for task %s", task_id)
    return result_key


@task(name="stage4_worker_step")
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
    docker_build_context: str = "/app",
    use_gpu: bool = True,
) -> dict:
    logger = get_run_logger()
    s3 = _s3_client()
    suffix = Path(input_key).suffix
    worker_kwargs = worker_kwargs or {}

    with tempfile.TemporaryDirectory() as tmp_dir:
        local_input = Path(tmp_dir) / f"input{suffix or '.bin'}"
        local_out_dir = Path(tmp_dir) / "worker_out"

        logger.info("Stage4 step %s: downloading s3://%s/%s", step_name, input_bucket, input_key)
        s3.download_file(input_bucket, input_key, str(local_input))

        started = time.perf_counter()
        if execution_mode == "docker":
            if not dockerfile_path or not image_tag:
                raise ValueError("dockerfile_path and image_tag are required for execution_mode=docker")
            output_local = _run_worker_in_docker(
                input_path=local_input,
                output_dir=local_out_dir,
                worker_module=worker_module,
                dockerfile_path=dockerfile_path,
                image_tag=image_tag,
                cli_args=cli_args,
                docker_build=docker_build,
                docker_build_context=docker_build_context,
                use_gpu=use_gpu,
            )
        else:
            module = importlib.import_module(worker_module)
            worker_cls = getattr(module, worker_class)
            worker = worker_cls(**worker_kwargs)
            output_local = Path(worker.run(str(local_input), str(local_out_dir)))
        elapsed = time.perf_counter() - started

        output_suffix = output_local.suffix or ".bin"
        step_key = f"{output_prefix}/{task_id}/{step_name}{output_suffix}"
        logger.info("Stage4 step %s: uploading s3://%s/%s", step_name, result_bucket, step_key)
        s3.upload_file(str(output_local), result_bucket, step_key)

    return {
        "step_name": step_name,
        "output_bucket": result_bucket,
        "output_key": step_key,
        "elapsed_seconds": round(elapsed, 3),
        "gpu_memory_mb": _gpu_memory_snapshot_mb(),
        "worker_module": worker_module,
        "worker_class": worker_class,
        "execution_mode": execution_mode,
    }


@flow(name="stage4-real-two-model-flow", log_prints=True)
def stage4_real_two_model_flow(
    task_id: str,
    input_bucket: str,
    input_key: str,
    result_bucket: str,
    completion_mode: str = "model",
    completion_weights_path: str | None = "external_models/SnowflakeNet/pretrained_completion/ckpt-best-c3d-cd_l2.pth",
    completion_config_path: str | None = "external_models/SnowflakeNet/completion/configs/c3d_cd2.yaml",
    completion_device: str | None = "cuda",
    meshing_repo_path: str = "external_models/ShapeAsPoints",
    meshing_config_path: str = "configs/optim_based/teaser.yaml",
    meshing_total_epochs: int = 200,
    meshing_grid_res: int = 128,
    meshing_no_cuda: bool = False,
    pipeline_steps: list[dict] | None = None,
) -> str:
    logger = get_run_logger()
    flow_started = time.perf_counter()
    logger.info("Stage4 real flow started for task %s", task_id)

    if pipeline_steps is None:
        pipeline_steps = [
            {
                "name": "01_completion",
                "worker_module": "workers.completion.snowflake_net.worker",
                "worker_class": "SnowflakeWorker",
                "execution_mode": "docker",
                "dockerfile_path": "/app/workers/completion/snowflake_net/Dockerfile",
                "image_tag": "pcpp-snowflake:gpu",
                "use_gpu": completion_device == "cuda",
                "cli_args": {
                    "mode": completion_mode,
                    "weights": completion_weights_path,
                    "config": completion_config_path,
                    "device": completion_device,
                },
            },
            {
                "name": "02_meshing",
                "worker_module": "workers.meshing.shape_as_points.worker",
                "worker_class": "ShapeAsPointsOptimWorker",
                "execution_mode": "docker",
                "dockerfile_path": "/app/workers/meshing/shape_as_points/Dockerfile",
                "image_tag": "pcpp-shape-as-points:gpu",
                "use_gpu": not meshing_no_cuda,
                "cli_args": {
                    "repo-path": meshing_repo_path,
                    "config": meshing_config_path,
                    "total-epochs": meshing_total_epochs,
                    "grid-res": meshing_grid_res,
                    "no-cuda": meshing_no_cuda,
                },
            },
        ]

    current_bucket = input_bucket
    current_key = input_key
    steps_metrics: list[dict] = []

    for idx, step in enumerate(pipeline_steps, start=1):
        step_name = step.get("name") or f"step_{idx:02d}"
        step_result = run_worker_step.with_options(name=f"stage4-{step_name}")(
            task_id=task_id,
            input_bucket=current_bucket,
            input_key=current_key,
            result_bucket=result_bucket,
            step_name=step_name,
            worker_module=step["worker_module"],
            worker_class=step["worker_class"],
            worker_kwargs=step.get("worker_kwargs") or {},
            output_prefix=step.get("output_prefix", "intermediate"),
            execution_mode=step.get("execution_mode", "local"),
            dockerfile_path=step.get("dockerfile_path"),
            image_tag=step.get("image_tag"),
            cli_args=step.get("cli_args") or {},
            docker_build=step.get("docker_build", True),
            docker_build_context=step.get("docker_build_context", "/app"),
            use_gpu=step.get("use_gpu", True),
        )
        steps_metrics.append(step_result)
        current_bucket = step_result["output_bucket"]
        current_key = step_result["output_key"]

    s3 = _s3_client()
    final_suffix = Path(current_key).suffix or ".bin"
    final_result_key = f"results/{task_id}/pipeline_output{final_suffix}"
    s3.copy_object(
        Bucket=result_bucket,
        CopySource={"Bucket": current_bucket, "Key": current_key},
        Key=final_result_key,
    )

    flow_elapsed = time.perf_counter() - flow_started
    metrics_payload = {
        "task_id": task_id,
        "flow_id": "stage4_real_two_model_flow",
        "started_at_utc": _utc_now(),
        "elapsed_seconds": round(flow_elapsed, 3),
        "input_bucket": input_bucket,
        "input_key": input_key,
        "result_bucket": result_bucket,
        "result_key": final_result_key,
        "steps": steps_metrics,
    }
    metrics_key = f"results/{task_id}/pipeline_metrics.json"
    s3.put_object(
        Bucket=result_bucket,
        Key=metrics_key,
        Body=json.dumps(metrics_payload, ensure_ascii=False, indent=2).encode("utf-8"),
        ContentType="application/json",
    )

    logger.info("Stage4 real flow completed for task %s", task_id)
    return final_result_key
