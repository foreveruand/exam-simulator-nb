from __future__ import annotations

from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile


ROOT = Path(__file__).resolve().parent
OUTPUT = ROOT / "dist" / "exam_simulator.ankiaddon"
INCLUDED = [
    "__init__.py",
    "exam_window.py",
    "history_store.py",
    "launcher.py",
    "manifest.json",
    "meta.json",
    "preset_store.py",
    "scorer.py",
]


def build_addon(output: Path = OUTPUT) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    with ZipFile(output, "w", compression=ZIP_DEFLATED) as archive:
        for relative_path in INCLUDED:
            archive.write(ROOT / relative_path, relative_path)


def main() -> None:
    build_addon()
    print(f"Wrote {OUTPUT}")


if __name__ == "__main__":
    main()
