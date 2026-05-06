from pathlib import Path


def append_log(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(text)


def read_log(path: Path) -> str:
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8")
