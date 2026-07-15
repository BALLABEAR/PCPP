from __future__ import annotations

import sys
from pathlib import Path


def process(input_path: str, output_dir: str) -> str:
    # Заглушка worker: будет заменено реальной логикой модели.
    source = Path(input_path)
    target = Path(output_dir) / source.name
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(source.read_bytes())
    return str(target)


# Запускает stub-worker через CLI-контракт input_path -> output_dir.
def main() -> int:
    if len(sys.argv) != 3:
        print("Usage: python worker.py <input_path> <output_dir>")
        return 2
    output_path = process(sys.argv[1], sys.argv[2])
    print(output_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
