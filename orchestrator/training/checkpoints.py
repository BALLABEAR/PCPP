from pathlib import Path


def find_best_checkpoint(search_roots: Path | list[Path] | tuple[Path, ...], patterns: list[str]) -> Path | None:
    roots = [search_roots] if isinstance(search_roots, Path) else [Path(item) for item in search_roots]
    for pattern in patterns:
        matches: list[Path] = []
        for root in roots:
            if not root.exists():
                continue
            matches.extend(candidate for candidate in root.glob(pattern) if candidate.is_file())
        matches.sort(key=lambda item: item.stat().st_mtime, reverse=True)
        if matches:
            return matches[0]
    return None


def resolve_best_checkpoint(
    search_roots: Path | list[Path] | tuple[Path, ...],
    patterns: list[str],
    fallback_checkpoint: Path | None = None,
) -> Path | None:
    selected = find_best_checkpoint(search_roots, patterns)
    if selected is not None:
        return selected
    if fallback_checkpoint is not None and fallback_checkpoint.is_file():
        return fallback_checkpoint
    return None
