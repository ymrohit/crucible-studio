"""Single-shot Gemma on Google AI Studio — the "GPU baseline" (right-pane speed race).

Mirrors :mod:`crucible.bench.vanilla_baseline` but calls Google AI Studio's
``streamGenerateContent`` endpoint instead of Cerebras. The point is a *same-model*
race: Gemma 4 31B running on a conventional GPU backend (AI Studio) vs the same weights
on Cerebras wafer-scale. We reuse vanilla's ``VANILLA_SYSTEM`` prompt and ``extract_code``
and return the SAME dict keys as ``vanilla_stream`` so the UI can swap one for the other.

Two AI-Studio quirks shape this file:
  * Gemma on AI Studio has no ``system`` role, so ``VANILLA_SYSTEM`` is prepended into the
    single user text part.
  * The API does not report a server-side completion time, so tok/s is measured against the
    wall-clock (``time.monotonic()``) around the streaming request.
"""

from __future__ import annotations

import json
import os
import time
from typing import Any, Callable, Optional

import httpx
from dotenv import load_dotenv

from .vanilla_baseline import VANILLA_SYSTEM, extract_code

load_dotenv()  # pull .env into os.environ (aistudio_gemma4_key)

DEFAULT_MODEL = "gemma-4-31b-it"
API_ROOT = "https://generativelanguage.googleapis.com/v1beta/models"


class GeminiError(RuntimeError):
    """Raised when the AI Studio key/model is missing or the API errors out."""


def _resolve_api_key(api_key: Optional[str] = None) -> str:
    """Use the explicit arg, else read the key from the environment / .env."""
    if api_key:
        return api_key.strip()
    for name in ("aistudio_gemma4_key", "AISTUDIO_GEMMA4_KEY", "GOOGLE_API_KEY", "GEMINI_API_KEY"):
        val = os.getenv(name)
        if val:
            return val.strip()
    raise GeminiError(
        "No Google AI Studio API key found. Set aistudio_gemma4_key in .env "
        "(or the environment), or pass api_key=."
    )


def gemini_stream(
    prompt: str,
    on_token: Callable[[str], None],
    *,
    model: str = DEFAULT_MODEL,
    api_key: Optional[str] = None,
) -> dict[str, Any]:
    """Stream Gemma's answer from AI Studio token-by-token (the GPU-pane typewriter).

    Returns the same dict shape as ``vanilla_stream``: ``code``, ``raw``, ``usage``,
    ``time_info``, ``tokens_per_sec``, ``elapsed``.
    """
    key = _resolve_api_key(api_key)
    if not model:
        raise GeminiError("No model specified for the AI Studio baseline.")

    # Gemma on AI Studio has no system role, so fold VANILLA_SYSTEM into the user text.
    user_text = f"{VANILLA_SYSTEM}\n\n{prompt}"
    url = f"{API_ROOT}/{model}:streamGenerateContent"
    body = {
        "contents": [{"role": "user", "parts": [{"text": user_text}]}],
        "generationConfig": {"temperature": 0.7},
    }

    chunks: list[str] = []
    completion_tokens = 0

    start = time.monotonic()
    with httpx.Client(timeout=300.0) as client:
        with client.stream(
            "POST",
            url,
            params={"alt": "sse", "key": key},
            json=body,
            headers={"Content-Type": "application/json"},
        ) as resp:
            if resp.status_code != 200:
                detail = resp.read().decode("utf-8", "replace")[:500]
                raise GeminiError(f"AI Studio HTTP {resp.status_code}: {detail}")
            for line in resp.iter_lines():
                if not line or not line.startswith("data:"):
                    continue
                payload = line[len("data:"):].strip()
                if not payload or payload == "[DONE]":
                    continue
                try:
                    obj = json.loads(payload)
                except json.JSONDecodeError:
                    continue
                for cand in obj.get("candidates", []):
                    for part in cand.get("content", {}).get("parts", []):
                        piece = part.get("text")
                        if piece:
                            chunks.append(piece)
                            on_token(piece)
                meta = obj.get("usageMetadata")
                if meta and meta.get("candidatesTokenCount"):
                    completion_tokens = int(meta["candidatesTokenCount"])
    elapsed = time.monotonic() - start

    content = "".join(chunks)
    if not content:
        raise GeminiError(
            f"AI Studio returned no text for model {model!r} (empty stream). "
            "Check the model name and that the key has access."
        )
    if not completion_tokens:
        completion_tokens = max(len(content) // 4, 1)  # estimate when usage is absent

    tps = completion_tokens / elapsed if elapsed > 0 else 0.0
    usage = {
        "completion_tokens": completion_tokens,
        "total_tokens": completion_tokens,
        "prompt_tokens": 0,
    }
    time_info = {"total_time": elapsed, "completion_time": elapsed}
    return {
        "code": extract_code(content),
        "raw": content,
        "usage": usage,
        "time_info": time_info,
        "tokens_per_sec": tps,
        "elapsed": elapsed,
    }


def gemini(
    prompt: str,
    *,
    model: str = DEFAULT_MODEL,
    api_key: Optional[str] = None,
) -> dict[str, Any]:
    """Non-streaming convenience: same result as ``gemini_stream`` with a no-op token sink."""
    return gemini_stream(prompt, lambda _piece: None, model=model, api_key=api_key)


if __name__ == "__main__":  # quick manual check / smoke test
    import sys

    p = " ".join(sys.argv[1:]) or "merge overlapping booking intervals"
    print(f"[streaming from AI Studio: {DEFAULT_MODEL!r}]\n")
    out = gemini_stream(p, lambda tok: print(tok, end="", flush=True))
    print("\n\n--- extracted code ---")
    print(out["code"])
    print(f"\n[{out['tokens_per_sec']:.0f} tok/s · {out['elapsed']:.2f}s]")
