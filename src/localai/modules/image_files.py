from __future__ import annotations

from pathlib import Path


def iter_image_files(
    input_dir: str | Path,
    extensions: list[str] | tuple[str, ...] = (".png",),
    recursive: bool = False,
) -> list[Path]:
    """Return sorted image files from a directory."""
    root = Path(input_dir).expanduser()
    normalized_extensions = {
        ext.lower() if ext.startswith(".") else f".{ext.lower()}" for ext in extensions
    }
    pattern = "**/*" if recursive else "*"
    files = [
        path
        for path in root.glob(pattern)
        if path.is_file() and path.suffix.lower() in normalized_extensions
    ]
    return sorted(files, key=lambda item: str(item).lower())
