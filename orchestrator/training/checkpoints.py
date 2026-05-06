from pathlib import Path


def find_best_checkpoint(run_dir: Path, patterns: list[str]) -> Path | None:
    for pattern in patterns:
        matches = sorted(
            [candidate for candidate in run_dir.glob(pattern) if candidate.is_file()],
            key=lambda item: item.stat().st_mtime,
            reverse=True,
        )
        if matches:
            return matches[0]
    return None
