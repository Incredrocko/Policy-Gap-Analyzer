"""Thin wrapper around the local Ollama HTTP API. No cloud calls -- everything
goes to http://localhost:11434, which must be running (`ollama serve`, or
it's already running as a background service after install)."""
import requests

import config


class OllamaConnectionError(RuntimeError):
    """Raised when Ollama isn't reachable, with a message the CLI can print
    directly rather than a raw traceback."""


def chat(prompt: str, system: str | None = None, json_mode: bool = False,
         model: str = config.CHAT_MODEL, temperature: float = 0.2) -> str:
    """Single-turn chat completion. Returns the raw text response."""
    messages = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": prompt})

    payload = {
        "model": model,
        "messages": messages,
        "stream": False,
        "options": {"temperature": temperature},
    }
    if json_mode:
        payload["format"] = "json"

    try:
        resp = requests.post(
            f"{config.OLLAMA_HOST}/api/chat", json=payload,
            timeout=config.OLLAMA_TIMEOUT_SECONDS,
        )
    except requests.exceptions.ConnectionError as e:
        raise OllamaConnectionError(
            f"Couldn't reach Ollama at {config.OLLAMA_HOST}. Is it running? "
            f"Try `ollama serve` in another terminal, or check `ollama list` "
            f"shows '{model}' pulled."
        ) from e
    except requests.exceptions.Timeout as e:
        raise OllamaConnectionError(
            f"Ollama didn't respond within {config.OLLAMA_TIMEOUT_SECONDS}s. This usually just "
            f"means '{model}' is slow to generate a long response (e.g. a full policy rewrite) "
            f"on your hardware, not that anything is broken. Options: raise "
            f"config.OLLAMA_TIMEOUT_SECONDS further, switch to a smaller model "
            f"(e.g. `ollama pull qwen2.5:1.5b`), or check Activity Monitor/htop to confirm "
            f"`ollama` is still actively using CPU (still working) rather than stuck."
        ) from e

    if resp.status_code == 404:
        raise OllamaConnectionError(
            f"Ollama returned 404 for model '{model}'. Pull it first: `ollama pull {model}`."
        )
    resp.raise_for_status()
    data = resp.json()
    return data["message"]["content"]
