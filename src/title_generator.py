"""Generate wallpaper titles through a vision-model chat API."""
from __future__ import annotations

import base64
import io
import re
import time
from pathlib import Path
from typing import Any, Optional

import requests

try:
    from PIL import Image
    HAS_PILLOW = True
    PILLOW_ERROR: Optional[Exception] = None
except Exception as error:
    HAS_PILLOW = False
    PILLOW_ERROR = error

def sanitize_filename(name: str) -> str:
    sanitized = re.sub(r'[\\/:*?"<>|]', "_", name).strip(" .")
    return sanitized[:200] if len(sanitized) > 200 else sanitized


def encode_image(image_path, ext: str, report=print) -> str:
    path = Path(image_path)
    if ext == ".webp":
        if HAS_PILLOW:
            try:
                with Image.open(path) as img:
                    buffered = io.BytesIO()
                    img.save(buffered, format="PNG")
                    return base64.b64encode(buffered.getvalue()).decode("utf-8")
            except Exception as err:
                report(f"  WebP conversion failed: {err}")
        else:
            report("  WebP detected but Pillow is not installed.")
            report(f"  Import error: {PILLOW_ERROR}")
            report("  Install with: py -m pip install Pillow")
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


def chat_completion(api_url: str, payload: dict[str, Any], headers: dict[str, str],
                    timeout: int = 300) -> tuple[str, str]:
    """POST a non-streaming chat completion. Returns (content, reasoning).

    Raises requests.HTTPError on non-2xx, with the server's error body
    included in the message.
    """
    response = requests.post(api_url, json=payload, headers=headers, timeout=timeout)
    if not response.ok:
        raise requests.HTTPError(
            f"HTTP {response.status_code} {response.reason} — {response.text}",
            response=response,
        )
    message = response.json()["choices"][0]["message"]
    return message.get("content") or "", message.get("reasoning_content") or ""


def get_new_name_from_model(image_path, system_prompt: str, ext: str,
                            existing_filenames, *, api_url: str, model_name: str,
                            max_retries: int = 5, report=print) -> Optional[str]:
    path = Path(image_path)
    base64_data = encode_image(path, ext, report)
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
            "model": model_name,
            "messages": messages,
            "max_tokens": 4096,
            "temperature": 0.7,
            "stream": False,
        }
        content, reasoning = chat_completion(api_url, payload, headers)
        target = content if content.strip() else reasoning

        name = parse_title(target)
        if not name:
            return None

        if f"{sanitize_filename(name)}{ext}".lower() not in existing_filenames:
            return name

        report(f"  [Notice] '{name}' already exists. Requesting alternative...")
        messages.append({"role": "assistant", "content": target})
        messages.append({"role": "user", "content": (
            f"The title '{name}' already exists in the collection. "
            "Please explore a different creative angle and provide another "
            "title using the same markdown format."
        )})
        time.sleep(1)

    report(f"  [Warning] Exceeded maximum retries for {path.name}.")
    return None


