# wallpaper_namer.py
# Run from the project directory: python src/wallpaper_namer.py
from __future__ import annotations

import os
import sys
import time
from pathlib import Path

from lmstudio import ensure_server_ready
from title_generator import get_new_name_from_model, sanitize_filename

IMAGE_DIR = Path(r"E:\Images\Wallpapers")
MODEL_NAME = "qwen3vl-8b-thinking"
API_URL = "http://localhost:1234/v1/chat/completions"
SYSTEM_PROMPT_FILE = Path(__file__).resolve().parent / "prompt.md"

LMS_EXECUTABLE = "lms"
LMS_LOAD_MODEL = ""

IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".gif", ".bmp", ".webp", ".tiff"}

# Enable VT processing on Windows consoles that don't have it on by default.
if sys.platform == "win32":
    os.system("")

RESET  = "\033[0m"
RED    = "\033[31m"
GREEN  = "\033[32m"
YELLOW = "\033[33m"
CYAN   = "\033[36m"
DIM    = "\033[90m"


def write_line(text: str, color: str = "") -> None:
    print(f"{color}{text}{RESET}" if color else text)


def write(text: str, color: str = "") -> None:
    """Write without trailing newline and flush (for in-progress lines)."""
    sys.stdout.write(f"{color}{text}{RESET}" if color else text)
    sys.stdout.flush()


def load_system_prompt() -> str:
    return SYSTEM_PROMPT_FILE.read_text(encoding="utf-8")


def is_image_file(filename) -> bool:
    return Path(filename).suffix.lower() in IMAGE_EXTENSIONS


def should_rename(filename) -> bool:
    stem = Path(filename).stem
    return bool(stem) and not stem[0].isupper()


def get_unique_filename(existing, base_name: str, extension: str) -> str:
    new_name = f"{base_name}{extension}"
    counter = 1
    while new_name.lower() in existing:
        new_name = f"{base_name}_{counter}{extension}"
        counter += 1
    return new_name


def main() -> None:
    try:
        system_prompt = load_system_prompt()
    except Exception as error:
        write_line(f"Error loading system prompt: {error}", RED)
        return

    if not IMAGE_DIR.exists():
        write_line(f"Error: Directory '{IMAGE_DIR}' does not exist.", RED)
        return

    existing = {p.name.lower() for p in IMAGE_DIR.rglob("*") if p.is_file()}
    candidates = [
        p for p in IMAGE_DIR.rglob("*")
        if p.is_file() and is_image_file(p.name) and should_rename(p.name)
    ]
    if not candidates:
        write_line("No images found that need renaming.", DIM)
        return

    if not ensure_server_ready(API_URL, MODEL_NAME, LMS_EXECUTABLE, LMS_LOAD_MODEL):
        write_line("LM Studio is not ready. Exiting.", RED)
        return

    write_line(f"Found {len(candidates)} images to rename in {IMAGE_DIR}.\n", DIM)

    total = len(candidates)
    renamed = skipped = failed = 0

    for index, file_path in enumerate(candidates, 1):
        relative = file_path.relative_to(IMAGE_DIR)
        ext = file_path.suffix.lower()

        write(f"[{index}/{total}] {relative} ", DIM)

        try:
            new_name = get_new_name_from_model(
                file_path, system_prompt, ext, existing,
                api_url=API_URL, model_name=MODEL_NAME,
                report=lambda message: write_line(message, YELLOW),
            )
            api_error = None
        except Exception as error:
            new_name = None
            api_error = str(error)

        if api_error is not None:
            failed += 1
            write_line(f"— FAILED ({api_error})", RED)
            continue

        if not new_name:
            skipped += 1
            write_line("— SKIPPED (no title)", YELLOW)
            continue

        new_filename = get_unique_filename(existing, sanitize_filename(new_name), ext)
        try:
            file_path.rename(file_path.parent / new_filename)
            existing.discard(file_path.name.lower())
            existing.add(new_filename.lower())
            renamed += 1
            write_line(f"-> {new_filename}", GREEN)
        except Exception as error:
            failed += 1
            write_line(f"— FAILED ({error})", RED)

        time.sleep(1)

    print()
    summary = f"Done: {renamed} renamed, {skipped} skipped, {failed} failed."
    write_line(summary, RED if failed else (YELLOW if skipped else GREEN))


if __name__ == "__main__":
    main()