import argparse
import json
import subprocess
import time
from pathlib import Path


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
    parser.add_argument("--input-size", required=True, help="e.g. 100k, 500k, 1m")
    parser.add_argument("--run-command", required=True, help="Command that runs worker inference once")
    parser.add_argument("--output", default="benchmark/results.json")
    args = parser.parse_args()

    elapsed = run_inference(args.run_command)
    peak_gpu_mb = get_gpu_memory_mb()

    result = {
        "model_id": args.model_id,
        "input_size": args.input_size,
        "elapsed_seconds": round(elapsed, 3),
        "peak_gpu_memory_mb": peak_gpu_mb,
    }

    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    existing: list[dict] = []
    if output_path.exists():
        existing = json.loads(output_path.read_text(encoding="utf-8"))
    existing.append(result)
    output_path.write_text(json.dumps(existing, ensure_ascii=False, indent=2), encoding="utf-8")

    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()

