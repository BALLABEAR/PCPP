import argparse
import json
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path

DEFAULT_LOCAL_INPUTS = [
    "examples/model_inputs/sofa.pcd",
    "examples/model_inputs/input.ply",
    "examples/model_inputs/airplane.pcd",
]


def run_inference(command: str) -> float:
    start = time.perf_counter()
    subprocess.run(command, shell=True, check=True)
    return time.perf_counter() - start


def run_dag_inference(
    orchestrator_url: str,
    input_file: Path,
    flow_id: str,
    flow_params: dict,
    timeout_seconds: int,
    poll_interval_seconds: float,
) -> dict:
    try:
        import requests
    except ModuleNotFoundError as exc:
        raise RuntimeError("requests is required for DAG benchmark mode. Install with: pip install requests") from exc

    with input_file.open("rb") as handle:
        upload_resp = requests.post(
            f"{orchestrator_url}/files/upload",
            files={"file": (input_file.name, handle, "application/octet-stream")},
            timeout=60,
        )
    upload_resp.raise_for_status()
    uploaded = upload_resp.json()

    create_payload = {
        "input_bucket": uploaded["bucket"],
        "input_key": uploaded["key"],
        "flow_id": flow_id,
        "flow_params": flow_params,
    }
    started = time.perf_counter()
    create_resp = requests.post(f"{orchestrator_url}/tasks", json=create_payload, timeout=60)
    create_resp.raise_for_status()
    task_payload = create_resp.json()
    task_id = task_payload["id"]

    deadline = time.time() + timeout_seconds
    while time.time() < deadline:
        status_resp = requests.get(f"{orchestrator_url}/tasks/{task_id}", timeout=30)
        status_resp.raise_for_status()
        task_payload = status_resp.json()
        if task_payload["status"] in {"completed", "failed"}:
            break
        time.sleep(poll_interval_seconds)

    if task_payload["status"] != "completed":
        raise RuntimeError(f"DAG task failed or timed out: {task_payload}")

    e2e_elapsed = time.perf_counter() - started
    step_metrics = []
    metrics_payload: dict = {}
    metrics_key = f"results/{task_id}/pipeline_metrics.json"

    try:
        download_resp = requests.get(
            f"{orchestrator_url}/files/download",
            params={"bucket": task_payload["result_bucket"], "key": metrics_key, "expires_seconds": 600},
            timeout=30,
        )
        download_resp.raise_for_status()
        presigned = download_resp.json()["url"]
        metrics_resp = requests.get(presigned, timeout=30)
        metrics_resp.raise_for_status()
        metrics_payload = metrics_resp.json()
        step_metrics = metrics_payload.get("steps", [])
    except Exception:
        step_metrics = []
        metrics_payload = {}

    return {
        "task_id": task_id,
        "elapsed_seconds": round(e2e_elapsed, 3),
        "task_payload": task_payload,
        "step_metrics": step_metrics,
        "pipeline_metrics": metrics_payload,
    }


def get_gpu_memory_mb() -> int | None:
    try:
        raw = subprocess.check_output(
            "nvidia-smi --query-gpu=memory.used --format=csv,noheader,nounits",
            shell=True,
            text=True,
        ).strip()
    except Exception:
        return None

    try:
        values = [int(line.strip()) for line in raw.splitlines() if line.strip()]
        return max(values) if values else None
    except ValueError:
        return None


def get_gpu_name() -> str | None:
    try:
        raw = subprocess.check_output(
            "nvidia-smi --query-gpu=name --format=csv,noheader",
            shell=True,
            text=True,
        ).strip()
        return raw.splitlines()[0] if raw else None
    except Exception:
        return None


def get_git_commit() -> str | None:
    try:
        return subprocess.check_output(
            "git rev-parse --short HEAD",
            shell=True,
            text=True,
        ).strip()
    except Exception:
        return None


def build_metadata() -> dict:
    return {
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "git_commit": get_git_commit(),
        "gpu_name": get_gpu_name(),
        "docker_image_tag": str(Path(".docker-image-tag").read_text().strip())
        if Path(".docker-image-tag").exists()
        else None,
    }


def collect_prepared_inputs(prepared_root: Path, input_size: str) -> list[Path]:
    mapping = {"100k": "100k", "500k": "500k", "1m": "1m"}
    if input_size not in mapping:
        raise ValueError("--input-size must be one of: 100k, 500k, 1m for prepared dataset mode")
    target_dir = prepared_root / mapping[input_size]
    if not target_dir.exists():
        raise FileNotFoundError(
            f"Prepared dataset folder not found: {target_dir}. "
            "Run benchmark/prepare_benchmark_data.py first."
        )
    files = sorted(target_dir.glob("*.xyz"))
    if not files:
        raise FileNotFoundError(f"No .xyz files found in {target_dir}")
    return files


def main() -> None:
    parser = argparse.ArgumentParser(description="Stage 3 benchmark scaffold")
    parser.add_argument("--model-id", required=True)
    parser.add_argument("--output", default="benchmark/results.json")
    parser.add_argument("--input-size", help="e.g. 100k, 500k, 1m (future production mode)")
    parser.add_argument("--run-command", help="One command for single benchmark run")
    parser.add_argument(
        "--use-local-samples",
        action="store_true",
        help="Temporary mode: run benchmark on default three files from examples/model_inputs",
    )
    parser.add_argument(
        "--run-command-template",
        help='Template for local files. Use "{input}" placeholder for file path.',
    )
    parser.add_argument("--repeats", type=int, default=1, help="How many times to run each local sample")
    parser.add_argument("--inputs", nargs="*", help="Optional custom local input files")
    parser.add_argument(
        "--benchmark-target",
        default="command",
        choices=["command", "dag"],
        help="command: run shell command template; dag: run orchestrator flow via API",
    )
    parser.add_argument("--orchestrator-url", default="http://localhost:8000")
    parser.add_argument("--flow-id", default="pipeline_flow")
    parser.add_argument(
        "--flow-params-json",
        default="{}",
        help='JSON for flow_params when --benchmark-target dag, e.g. \'{"completion_mode":"model"}\'',
    )
    parser.add_argument("--task-timeout-seconds", type=int, default=7200)
    parser.add_argument("--poll-interval-seconds", type=float, default=2.0)
    parser.add_argument(
        "--dataset",
        default="custom",
        choices=["custom", "prepared"],
        help="custom: existing behavior, prepared: use data/benchmark_inputs/<size>",
    )
    parser.add_argument(
        "--prepared-root",
        default="data/benchmark_inputs",
        help="Root folder for prepared benchmark inputs",
    )
    args = parser.parse_args()

    results: list[dict] = []
    metadata = build_metadata()
    flow_params = json.loads(args.flow_params_json or "{}")
    if args.dataset == "prepared":
        if not args.input_size:
            raise ValueError("--input-size is required with --dataset prepared")
        if args.benchmark_target == "command" and not args.run_command_template:
            raise ValueError("--run-command-template is required with --dataset prepared")
        input_files = collect_prepared_inputs(Path(args.prepared_root), args.input_size.lower())
        for input_file in input_files:
            for run_idx in range(1, args.repeats + 1):
                if args.benchmark_target == "dag":
                    dag_run = run_dag_inference(
                        orchestrator_url=args.orchestrator_url,
                        input_file=input_file,
                        flow_id=args.flow_id,
                        flow_params=flow_params,
                        timeout_seconds=args.task_timeout_seconds,
                        poll_interval_seconds=args.poll_interval_seconds,
                    )
                    elapsed = dag_run["elapsed_seconds"]
                    step_metrics = dag_run["step_metrics"]
                    pipeline_metrics = dag_run.get("pipeline_metrics") or {}
                    step_gpu = [item.get("gpu_memory_mb") for item in step_metrics if item.get("gpu_memory_mb") is not None]
                    peak_gpu_mb = max(step_gpu) if step_gpu else get_gpu_memory_mb()
                    dag_task_id = dag_run["task_id"]
                    task_result_key = dag_run["task_payload"].get("result_key")
                    queue_delay = pipeline_metrics.get("queue_delay_seconds")
                    build_total = pipeline_metrics.get("image_build_total_seconds")
                    throughput = pipeline_metrics.get("throughput_files_per_second")
                    files_total = pipeline_metrics.get("files_total")
                else:
                    command = args.run_command_template.format(input=str(input_file).replace("\\", "/"))
                    elapsed = run_inference(command)
                    peak_gpu_mb = get_gpu_memory_mb()
                    step_metrics = []
                    dag_task_id = None
                    task_result_key = None
                    queue_delay = None
                    build_total = None
                    throughput = None
                    files_total = None

                results.append(
                    {
                        "model_id": args.model_id,
                        "input_size": args.input_size.lower(),
                        "input_file": input_file.name,
                        "elapsed_seconds": round(elapsed, 3),
                        "peak_gpu_memory_mb": peak_gpu_mb,
                        "mode": "prepared_dataset_dag" if args.benchmark_target == "dag" else "prepared_dataset",
                        "run_index": run_idx,
                        "flow_id": args.flow_id if args.benchmark_target == "dag" else None,
                        "task_id": dag_task_id,
                        "task_result_key": task_result_key,
                        "step_metrics": step_metrics,
                        "queue_delay_seconds": queue_delay,
                        "image_build_total_seconds": build_total,
                        "throughput_files_per_second": throughput,
                        "files_total": files_total,
                        "metadata": metadata,
                    }
                )
    elif args.use_local_samples:
        # Temporary benchmark mode for the three user-provided files.
        if not args.run_command_template:
            raise ValueError("--run-command-template is required with --use-local-samples")
        input_files = [Path(p) for p in (args.inputs or DEFAULT_LOCAL_INPUTS)]
        missing = [str(p) for p in input_files if not p.exists()]
        if missing:
            raise FileNotFoundError(f"Missing local sample files: {missing}")
        for input_file in input_files:
            for run_idx in range(1, args.repeats + 1):
                command = args.run_command_template.format(input=str(input_file).replace("\\", "/"))
                elapsed = run_inference(command)
                peak_gpu_mb = get_gpu_memory_mb()
                results.append(
                    {
                        "model_id": args.model_id,
                        "input_size": input_file.name,
                        "elapsed_seconds": round(elapsed, 3),
                        "peak_gpu_memory_mb": peak_gpu_mb,
                        "mode": "temporary_local_samples",
                        "run_index": run_idx,
                        "metadata": metadata,
                    }
                )
    else:
        # Future production benchmark mode (100K/500K/1M).
        if not args.input_size or not args.run_command:
            raise ValueError("--input-size and --run-command are required in production mode")
        elapsed = run_inference(args.run_command)
        peak_gpu_mb = get_gpu_memory_mb()
        results.append(
            {
                "model_id": args.model_id,
                "input_size": args.input_size,
                "elapsed_seconds": round(elapsed, 3),
                "peak_gpu_memory_mb": peak_gpu_mb,
                "mode": "production",
                "run_index": 1,
                "metadata": metadata,
            }
        )

    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    existing: list[dict] = []
    if output_path.exists():
        existing = json.loads(output_path.read_text(encoding="utf-8"))
    existing.extend(results)
    output_path.write_text(json.dumps(existing, ensure_ascii=False, indent=2), encoding="utf-8")

    print(json.dumps(results, ensure_ascii=False))


if __name__ == "__main__":
    main()

