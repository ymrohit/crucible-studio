"""Cerebras Chat Completions client with strict structured output (the agent foundation).

Every agent calls :meth:`CerebrasClient.structured` with a system prompt, user content, and
a pydantic model. The model's JSON schema is converted to a Cerebras-strict json_schema
(``additionalProperties:false`` + every key required, recursively), sent as ``response_format``
with ``strict: true``, and the returned content is validated back into the model. On a
validation failure we retry once with the error appended (§9), then surface.

Notes proven empirically against the live API (gemma-4-31b):
  * Strict mode rejects free-form objects ("require at least one of 'properties' or 'anyOf'"),
    so the one free-form field in the seam — ``Spec.illustrative_examples: list[dict]`` — is
    represented to the API as ``{"input": str, "output": str}`` items, which still validate
    against ``list[dict]``.
  * ``usage`` carries prompt/completion/total + reasoning token counts; ``time_info`` carries
    queue/prompt/completion/total times. tok/s = completion_tokens / completion_time; we treat
    queue+prompt time as time-to-first-token.
  * ``reasoning_effort`` is supported and emits a separate ``message.reasoning`` field, which
    consumes completion tokens — reasoning calls get a larger token budget.
"""

from __future__ import annotations

import copy
import json
import os
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Optional, Type, TypeVar

import httpx
from dotenv import load_dotenv
from pydantic import BaseModel, ValidationError

load_dotenv()  # pull .env into os.environ (CEREBRAS_API_KEY / cerebras_key)

T = TypeVar("T", bound=BaseModel)

DEFAULT_BASE_URL = "https://api.cerebras.ai/v1"
DEFAULT_MODEL = os.getenv("CRUCIBLE_MODEL", "gemma-4-31b")


class CerebrasError(RuntimeError):
    """Raised when the API returns a non-200 or repeatedly unparseable response."""


def _resolve_api_key() -> str:
    for name in ("CEREBRAS_API_KEY", "cerebras_key", "CEREBRAS_KEY"):
        val = os.getenv(name)
        if val:
            return val.strip()
    raise CerebrasError(
        "No Cerebras API key found. Set CEREBRAS_API_KEY (or cerebras_key) in .env or the environment."
    )


def _strictify(node: Any) -> Any:
    """Make a JSON schema Cerebras-strict-compatible, in place.

    For every object: force ``additionalProperties:false`` and mark every declared property
    required (strict mode requires this — nullability is expressed via anyOf/null in the type,
    which pydantic already emits for Optional fields). A free-form object (object with no
    declared properties) is given ``{"input": str, "output": str}`` — the shape of the only
    such field in the seam, ``Spec.illustrative_examples`` — because strict mode forbids
    bare objects.
    """
    if isinstance(node, dict):
        if node.get("type") == "object" or "properties" in node:
            props = node.get("properties")
            if props is None:
                node["properties"] = {
                    "input": {"type": "string"},
                    "output": {"type": "string"},
                }
                node["required"] = ["input", "output"]
                node["additionalProperties"] = False
            else:
                node["additionalProperties"] = False
                node["required"] = list(props.keys())
                for v in props.values():
                    _strictify(v)
        for key in ("items", "additionalItems", "contains"):
            if key in node and isinstance(node[key], dict):
                _strictify(node[key])
        for key in ("anyOf", "allOf", "oneOf", "prefixItems"):
            if key in node and isinstance(node[key], list):
                for v in node[key]:
                    _strictify(v)
        if "$defs" in node:
            for v in node["$defs"].values():
                _strictify(v)
    return node


def build_strict_schema(model: Type[BaseModel]) -> dict[str, Any]:
    return _strictify(copy.deepcopy(model.model_json_schema()))


@dataclass
class CallResult:
    """Everything one structured call produced — the validated object plus accounting."""

    parsed: BaseModel
    usage: dict[str, Any]
    time_info: dict[str, Any]
    raw_content: str
    tokens_per_sec: float
    ttft: float
    reasoning: str = ""

    @property
    def total_tokens(self) -> int:
        return int(self.usage.get("total_tokens", 0))


def _metrics(usage: dict[str, Any], time_info: dict[str, Any]) -> tuple[float, float]:
    completion_tokens = float(usage.get("completion_tokens", 0) or 0)
    completion_time = float(time_info.get("completion_time", 0) or 0)
    tps = completion_tokens / completion_time if completion_time > 0 else 0.0
    ttft = float(time_info.get("queue_time", 0) or 0) + float(time_info.get("prompt_time", 0) or 0)
    return tps, ttft


class CerebrasClient:
    def __init__(
        self,
        api_key: Optional[str] = None,
        model: Optional[str] = None,
        base_url: str = DEFAULT_BASE_URL,
        timeout: float = 120.0,
    ) -> None:
        self.api_key = api_key or _resolve_api_key()
        self.model = model or DEFAULT_MODEL
        self.base_url = base_url.rstrip("/")
        self._client = httpx.Client(
            base_url=self.base_url,
            headers={"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"},
            timeout=timeout,
        )

    # -- low-level POST --------------------------------------------------------
    _TRANSIENT = {429, 500, 502, 503, 504}

    def _post(self, body: dict[str, Any], *, attempts: int = 4) -> dict[str, Any]:
        """POST with backoff on transient API failures (rate limits / 5xx / transport)."""
        delay = 0.6
        last: Optional[str] = None
        for i in range(attempts):
            try:
                resp = self._client.post("/chat/completions", json=body)
            except httpx.HTTPError as e:
                last = f"transport error: {e}"
            else:
                if resp.status_code == 200:
                    return resp.json()
                last = f"HTTP {resp.status_code}: {resp.text[:300]}"
                if resp.status_code not in self._TRANSIENT:
                    raise CerebrasError(f"Cerebras {last}")
            if i < attempts - 1:
                time.sleep(delay)
                delay *= 2
        raise CerebrasError(f"Cerebras request failed after {attempts} attempts: {last}")

    # -- structured (the agent workhorse) -------------------------------------
    def structured(
        self,
        system_prompt: str,
        user_content: str,
        schema: Type[T],
        *,
        reasoning_effort: Optional[str] = None,
        temperature: float = 0.6,
        max_completion_tokens: int = 4096,
        retries: int = 1,
        extra_user_blocks: Optional[list[dict[str, Any]]] = None,
    ) -> CallResult:
        """Call the model and validate the response into ``schema``.

        ``extra_user_blocks`` lets the Architect optionally accept multimodal content
        (e.g. a base64 image block) appended after the text — unused in v1.
        """
        strict_schema = build_strict_schema(schema)
        json_schema = {
            "type": "json_schema",
            "json_schema": {"name": schema.__name__, "strict": True, "schema": strict_schema},
        }

        if extra_user_blocks:
            user_message: Any = [{"type": "text", "text": user_content}, *extra_user_blocks]
        else:
            user_message = user_content

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_message},
        ]

        last_err: Optional[str] = None
        mct = max_completion_tokens
        agg = {"total_tokens": 0, "completion_tokens": 0, "prompt_tokens": 0}
        for attempt in range(retries + 1):
            if last_err is not None:
                # Cheap repair turn: tell the model exactly how it violated the schema.
                messages = messages[:2] + [
                    {
                        "role": "user",
                        "content": (
                            "Your previous response failed schema validation with this error:\n"
                            f"{last_err}\n\nReturn ONLY corrected JSON matching the schema exactly."
                        ),
                    }
                ]

            body: dict[str, Any] = {
                "model": self.model,
                "messages": messages,
                "response_format": json_schema,
                "temperature": temperature,
                "max_completion_tokens": mct,
            }
            if reasoning_effort:
                body["reasoning_effort"] = reasoning_effort

            data = self._post(body)
            choice = data["choices"][0]
            finish = choice.get("finish_reason")
            content = choice["message"].get("content") or ""
            reasoning = choice["message"].get("reasoning") or ""
            usage = data.get("usage", {})
            time_info = data.get("time_info", {})
            tps, ttft = _metrics(usage, time_info)
            # Accumulate tokens across attempts so the budget is charged for failed tries too
            # (a truncated/invalid first attempt still burned real tokens).
            for k in agg:
                agg[k] += int(usage.get(k, 0) or 0)

            try:
                parsed = schema.model_validate_json(content)
                charged = {**usage, **agg}  # report cumulative token counts to the governor
                return CallResult(
                    parsed=parsed,
                    usage=charged,
                    time_info=time_info,
                    raw_content=content,
                    tokens_per_sec=tps,
                    ttft=ttft,
                    reasoning=reasoning,
                )
            except ValidationError as exc:
                last_err = str(exc)[:1500]
                if finish == "length":
                    # Output was truncated → invalid JSON. Retrying at the same cap repeats
                    # the truncation, so grow the budget before the next attempt.
                    last_err = f"response was truncated (finish_reason=length); {last_err}"
                    mct = min(mct * 2, 32000)
                if attempt >= retries:
                    raise CerebrasError(
                        f"{schema.__name__} validation failed after {retries + 1} attempts "
                        f"(finish_reason={finish}): {last_err}\nraw: {content[:500]}"
                    ) from exc
        raise CerebrasError("unreachable")  # pragma: no cover

    # -- plain text (vanilla baseline) ----------------------------------------
    def text(
        self,
        system_prompt: str,
        user_content: str,
        *,
        temperature: float = 0.7,
        max_completion_tokens: int = 2048,
        reasoning_effort: Optional[str] = None,
    ) -> tuple[str, dict[str, Any], dict[str, Any], float, float]:
        body: dict[str, Any] = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_content},
            ],
            "temperature": temperature,
            "max_completion_tokens": max_completion_tokens,
        }
        if reasoning_effort:
            body["reasoning_effort"] = reasoning_effort
        data = self._post(body)
        content = data["choices"][0]["message"].get("content") or ""
        usage = data.get("usage", {})
        time_info = data.get("time_info", {})
        tps, ttft = _metrics(usage, time_info)
        return content, usage, time_info, tps, ttft

    # -- streaming text (left-pane "fast vanilla" feel) -----------------------
    def stream_text(
        self,
        system_prompt: str,
        user_content: str,
        on_token: Callable[[str], None],
        *,
        temperature: float = 0.7,
        max_completion_tokens: int = 2048,
    ) -> tuple[str, dict[str, Any], dict[str, Any]]:
        body = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_content},
            ],
            "temperature": temperature,
            "max_completion_tokens": max_completion_tokens,
            "stream": True,
        }
        chunks: list[str] = []
        usage: dict[str, Any] = {}
        time_info: dict[str, Any] = {}
        with self._client.stream("POST", "/chat/completions", json=body) as resp:
            if resp.status_code != 200:
                raise CerebrasError(f"Cerebras HTTP {resp.status_code}: {resp.read()[:500]!r}")
            for line in resp.iter_lines():
                if not line or not line.startswith("data:"):
                    continue
                payload = line[len("data:"):].strip()
                if payload == "[DONE]":
                    break
                try:
                    obj = json.loads(payload)
                except json.JSONDecodeError:
                    continue
                if obj.get("usage"):
                    usage = obj["usage"]
                if obj.get("time_info"):
                    time_info = obj["time_info"]
                for ch in obj.get("choices", []):
                    delta = ch.get("delta", {})
                    tok = delta.get("content")
                    if tok:
                        chunks.append(tok)
                        on_token(tok)
        return "".join(chunks), usage, time_info

    def close(self) -> None:
        self._client.close()


# A lazily-created process-wide client so every agent shares one connection pool.
_default_client: Optional[CerebrasClient] = None


def get_client() -> CerebrasClient:
    global _default_client
    if _default_client is None:
        _default_client = CerebrasClient()
    return _default_client
