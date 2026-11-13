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

# Images longer than this on either side are downscaled before being sent to
# the model. Keeps request bodies small enough for local servers.
MAX_IMAGE_DIMENSION = 1024

# How many times to retry a request that fails with a connection error or
# an HTTP 5xx before giving up on that image.
MAX_TRANSIENT_ATTEMPTS = 3


def sanitize_filename(name: str) -> str:
    sanitized = re.sub(r'[\\/:*?"<>|]', "_", name).strip(" .")
    return sanitized[:200] if len(sanitized) > 200 else sanitized


def _resampling_filter():
    """Best available downsampling filter for this Pillow version."""
    try:
        return Image.Resampling.LANCZOS
    except AttributeError:
        return Image.LANCZOS


def _resize_if_needed(image: Image.Image) -> Image.Image:
    """Return a downscaled copy if the image exceeds MAX_IMAGE_DIMENSION."""
    width, height = image.size
    if max(width, height) <= MAX_IMAGE_DIMENSION:
        return image
    scale = MAX_IMAGE_DIMENSION / max(width, height)
    return image.resize(
        (int(width * scale), int(height * scale)), _resampling_filter()
    )


def encode_image(image_path, ext: str, report=print) -> str:
    path = Path(image_path)

    if ext == ".webp":
        if HAS_PILLOW:
            try:
                with Image.open(path) as img:
                    img = _resize_if_needed(img)
                    buffered = io.BytesIO()
                    img.save(buffered, format="PNG")
                    return base64.b64encode(buffered.getvalue()).decode("utf-8")
            except Exception as err:
                report(f"  WebP conversion failed: {err}")
        else:
            report("  WebP detected but Pillow is not installed.")
            report(f"  Import error: {PILLOW_ERROR}")
            report("  Install with: py -m pip install Pillow")

    if HAS_PILLOW:
        try:
            with Image.open(path) as img:
                # Images within the size limit are sent as-is; re-encoding
                # them is unnecessary and can alter the file.
                if max(img.size) <= MAX_IMAGE_DIMENSION:
                    return base64.b64encode(path.read_bytes()).decode("utf-8")
                img = _resize_if_needed(img)
                buffered = io.BytesIO()
                img.save(buffered, format=img.format or "PNG")
                return base64.b64encode(buffered.getvalue()).decode("utf-8")
        except Exception as err:
            report(f"  Image processing failed: {err}; sending raw file bytes.")

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


def _is_transient_error(error: Exception) -> bool:
    """True if the request failed in a way a retry might reasonably fix.

    requests' ConnectionError/Timeout subclass the builtin ConnectionError/
    TimeoutError, so checking the builtins covers both.
    """
    if isinstance(error, (ConnectionError, TimeoutError)):
        return True
    if isinstance(error, requests.exceptions.HTTPError):
        response = getattr(error, "response", None)
        if response is not None:
            return 500 <= response.status_code < 600
    return False


def _transient_error_message(error: Exception) -> str:
    if isinstance(error, requests.exceptions.HTTPError):
        response = getattr(error, "response", None)
        if response is not None:
            return f"HTTP {response.status_code}"
    return str(error)


def get_new_name_from_model(image_path, system_prompt: str, ext: str,
                            existing_filenames, *, api_url: str, model_name: str,
                            max_retries: int = 5, report=print) -> Optional[str]:
    path = Path(image_path)
    base64_data = encode_image(path, ext, report)
    mime = {
        ".png": "image/png", ".gif": "image/gif", ".bmp": "image/bmp",
        ".tiff": "image/tiff", ".webp": "image/png" if HAS_PILLOW else "image/webp",
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
        # Retry transient transport or server errors before counting the
        # attempt toward the title-retry limit.
        content = reasoning = None
        for attempt in range(MAX_TRANSIENT_ATTEMPTS):
            try:
                payload = {
                    "model": model_name,
                    "messages": messages,
                    "max_tokens": 4096,
                    "temperature": 0.7,
                    "stream": False,
                }
                content, reasoning = chat_completion(api_url, payload, headers)
                break
            except Exception as error:
                if not _is_transient_error(error):
                    raise
                if attempt + 1 >= MAX_TRANSIENT_ATTEMPTS:
                    raise
                delay = min(2 ** (attempt + 1), 8)
                report(f"  [Notice] Request failed ({_transient_error_message(error)}); "
                       f"retrying in {delay}s...")
                time.sleep(delay)

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
