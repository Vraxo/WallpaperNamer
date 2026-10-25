# lmstudio.py
# Utilities for starting and verifying a local LM Studio server.
#
# Public API:
#   ensure_server_ready(api_url, model_name, lms_executable, lms_load_model) -> bool
#
# The function starts the server via the 'lms' CLI if it isn't already
# reachable, optionally preloads a model, and verifies that the configured
# model name is present in /v1/models. Returns True if the server is ready
# to accept requests, False otherwise.
from __future__ import annotations

import os
import subprocess
import sys
import time
from typing import Optional

import requests

# Enable VT processing on Windows consoles.
if sys.platform == "win32":
    os.system("")


class Color:
    RESET     = "\033[0m"
    RED       = "\033[31m"
    GREEN     = "\033[32m"
    YELLOW    = "\033[33m"
    CYAN      = "\033[36m"
    DARK_GRAY = "\033[90m"


def _print(text: str, color: str = "") -> None:
    print(f"{color}{text}{Color.RESET}" if color else text)


def _api_base(api_url: str) -> str:
    """Strip the /v1/... suffix from a chat-completions URL."""
    return api_url.rsplit("/v1/", 1)[0]


def is_server_reachable(api_url: str, timeout: int = 5) -> bool:
    try:
        return requests.get(f"{_api_base(api_url)}/v1/models", timeout=timeout).ok
    except Exception:
        return False


def _verify_configured_model(api_url: str, model_name: str) -> bool:
    try:
        response = requests.get(f"{_api_base(api_url)}/v1/models", timeout=5)
        if not response.ok:
            _print(
                f"[Model check] /v1/models returned {response.status_code}; skipping check.",
                Color.YELLOW,
            )
            return True

        ids = [m.get("id") for m in response.json().get("data", []) if m.get("id")]

        if any(i.lower() == model_name.lower() for i in ids):
            _print(f"[Model check] '{model_name}' is available.", Color.CYAN)
            return True

        print()
        _print(f"[Model check] Configured model '{model_name}' was NOT found.", Color.RED)
        print()
        _print(f"  Server lists {len(ids)} model(s):", Color.DARK_GRAY)
        for model_id in ids:
            _print(f"    - {model_id}", Color.DARK_GRAY)
        print()
        _print(
            "  Update MODEL_NAME to match one of the IDs above (exact, case-sensitive).",
            Color.DARK_GRAY,
        )
        print()
        return False

    except Exception as error:
        _print(f"[Model check] Failed to query /v1/models: {error}", Color.YELLOW)
        return True


def _spawn_lms(lms_executable: str, args: list[str]) -> Optional[subprocess.Popen]:
    creationflags = (
        subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0  # type: ignore[attr-defined]
    )
    try:
        return subprocess.Popen(
            [lms_executable] + args,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=creationflags,
        )
    except FileNotFoundError:
        _print(f"Could not find '{lms_executable}'.", Color.RED)
        _print("If 'lms' is not on your PATH, pass its full path.", Color.DARK_GRAY)
        return None


def _ensure_model_loaded(api_url: str, lms_executable: str, lms_load_model: str) -> bool:
    """If a model name is configured, preload it (no-op if empty)."""
    if not lms_load_model.strip():
        return True

    # Skip preload if the model is already listed.
    try:
        response = requests.get(f"{_api_base(api_url)}/v1/models", timeout=5)
        if response.ok:
            for entry in response.json().get("data", []):
                if lms_load_model.lower() in entry.get("id", "").lower():
                    _print(f"Model '{lms_load_model}' is already loaded.", Color.DARK_GRAY)
                    return True
    except Exception:
        pass

    _print(f"Preloading model '{lms_load_model}' via 'lms load'...", Color.DARK_GRAY)
    proc = _spawn_lms(lms_executable, ["load", lms_load_model, "--yes"])
    if proc is None:
        return False

    # Up to ~3 minutes for the model to load.
    for _ in range(90):
        time.sleep(2)
        if proc.poll() is not None:
            return proc.returncode == 0

    _print("Timed out waiting for 'lms load' to complete.", Color.RED)
    return False


def ensure_server_ready(
    api_url: str,
    model_name: str,
    lms_executable: str = "lms",
    lms_load_model: str = "",
) -> bool:
    """Ensure LM Studio is running, reachable, and the configured model is present.

    Returns True if the server is ready to accept requests, False otherwise.
    Prints status messages as it goes.
    """
    if not is_server_reachable(api_url):
        _print(
            "LM Studio server not detected. Attempting to start via 'lms' CLI...",
            Color.DARK_GRAY,
        )
        if _spawn_lms(lms_executable, ["server", "start"]) is None:
            return False

        _print("Waiting for LM Studio server to become ready...", Color.DARK_GRAY)
        for _ in range(30):
            time.sleep(2)
            if is_server_reachable(api_url):
                _print("LM Studio server is now running.", Color.DARK_GRAY)
                break
        else:
            _print("Timed out waiting for the LM Studio server to start.", Color.RED)
            return False

    if not _ensure_model_loaded(api_url, lms_executable, lms_load_model):
        return False

    return _verify_configured_model(api_url, model_name)