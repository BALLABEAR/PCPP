import argparse
import json
import subprocess
import time
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
    args = parser.parse_args()

    results: list[dict] = []
    if args.use_local_samples:
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

