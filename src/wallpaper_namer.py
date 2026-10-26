# wallpaper_namer.py
# Run from the project directory: python src/wallpaper_namer.py
from __future__ import annotations

import base64
import io
import os
import re
import sys
import time
from pathlib import Path
from typing import Any, Optional

import requests

from lmstudio import ensure_server_ready

try:
    from PIL import Image
    HAS_PILLOW = True
    PILLOW_ERROR: Optional[Exception] = None
except Exception as error:
    HAS_PILLOW = False
    PILLOW_ERROR = error

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


def sanitize_filename(name: str) -> str:
    sanitized = re.sub(r'[\\/:*?"<>|]', "_", name).strip(" .")
    return sanitized[:200] if len(sanitized) > 200 else sanitized


def get_unique_filename(existing, base_name: str, extension: str) -> str:
    new_name = f"{base_name}{extension}"
    counter = 1
    while new_name.lower() in existing:
        new_name = f"{base_name}_{counter}{extension}"
        counter += 1
    return new_name


def encode_image(image_path, ext: str) -> str:
    path = Path(image_path)
    if ext == ".webp":
        if HAS_PILLOW:
            try:
                with Image.open(path) as img:
                    buffered = io.BytesIO()
                    img.save(buffered, format="PNG")
                    return base64.b64encode(buffered.getvalue()).decode("utf-8")
            except Exception as err:
                write_line(f"  WebP conversion failed: {err}", YELLOW)
        else:
            write_line("  WebP detected but Pillow is not installed.", YELLOW)
            write_line(f"  Import error: {PILLOW_ERROR}", YELLOW)
            write_line("  Install with: py -m pip install Pillow", YELLOW)
    return base64.b64encode(path.read_bytes()).decode("utf-8")


def parse_title(content: str) -> Optional[str]:
    """Extract the title from a markdown H1, with XML/bold fallbacks."""
    if m := re.search(r'^[ \t]*#[ \t]+(.+?)[ \t]*$', content, re.MULTILINE):
        return m.group(1).strip().rstrip("#").strip()
    if m := re.search(r'<title>\s*(.*?)\s*</title>', content, re.IGNORECASE | re.DOTALL):
        return m.group(1).strip()
    if m := re.search(r'\*\*"?([^"\*]+)"?\*\*', content):
        return m.group(1).strip().strip(' "')
    return None


def chat_completion(payload: dict[str, Any], headers: dict[str, str],
                    timeout: int = 300) -> tuple[str, str]:
    """POST a non-streaming chat completion. Returns (content, reasoning).

    Raises requests.HTTPError on non-2xx, with the server's error body
    included in the message.
    """
    response = requests.post(API_URL, json=payload, headers=headers, timeout=timeout)
    if not response.ok:
        raise requests.HTTPError(
            f"HTTP {response.status_code} {response.reason} — {response.text}",
            response=response,
        )
    message = response.json()["choices"][0]["message"]
    return message.get("content") or "", message.get("reasoning_content") or ""


def get_new_name_from_model(image_path, system_prompt: str, ext: str,
                            existing_filenames, max_retries: int = 5) -> Optional[str]:
    path = Path(image_path)
    base64_data = encode_image(path, ext)
    mime = {
        ".png": "image/png", ".gif": "image/gif", ".bmp": "image/bmp",
        ".webp": "image/png" if HAS_PILLOW else "image/webp",
    }.get(ext, "image/jpeg")
    data_url = f"data:{mime};base64,{base64_data}"

    messages = [
        {"role": "system", "content": f"[Cache buster: {time.time()}]\n\n{system_prompt}"},
        {"role": "user", "content": [
            {"type": "text", "text": "Name this artwork."},
            {"type": "image_url", "image_url": {"url": data_url}},
        ]},
    ]
    headers = {"Content-Type": "application/json"}

    for _ in range(max_retries):
        payload = {
            "model": MODEL_NAME,
            "messages": messages,
            "max_tokens": 4096,
            "temperature": 0.7,
            "stream": False,
        }
        content, reasoning = chat_completion(payload, headers)
        target = content if content.strip() else reasoning

        name = parse_title(target)
        if not name:
            return None

        if f"{sanitize_filename(name)}{ext}".lower() not in existing_filenames:
            return name

        write_line(f"  [Notice] '{name}' already exists. Requesting alternative...", YELLOW)
        messages.append({"role": "assistant", "content": target})
        messages.append({"role": "user", "content": (
            f"The title '{name}' already exists in the collection. "
            "Please explore a different creative angle and provide another "
            "title using the same markdown format."
        )})
        time.sleep(1)

    write_line(f"  [Warning] Exceeded maximum retries for {path.name}.", YELLOW)
    return None


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
            new_name = get_new_name_from_model(file_path, system_prompt, ext, existing)
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