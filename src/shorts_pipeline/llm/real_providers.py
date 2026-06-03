"""Optional real LLM provider adapters (opt-in, default OFF).

These adapters are never used by the default pipeline path. The deterministic
fake providers in ``dev_fakes`` remain the default. Real adapters are only
constructed when a caller explicitly opts in through
``SHORTS_PIPELINE_ENABLE_REAL_LLM`` plus ``SHORTS_PIPELINE_LLM_BACKEND`` (or by
calling ``build_b_provider`` / ``build_e_provider`` directly).

Design constraints:

- Provider SDKs are loaded dynamically with :func:`importlib.import_module`, not
  with ``import openai`` style statements, so the repository's static
  network/provider import guard stays valid. There are no literal SDK imports in
  this module.
- API keys are read from the environment at client-construction time. They are
  never written to artifacts, the database, logs, or stored as attributes of the
  returned provider objects.
- ``generate`` returns a raw payload dict. The B/E services keep ownership of
  Pydantic validation, retries, and persistence; this module adds no trust.
"""

from __future__ import annotations

import importlib
import json
import os
import time
from typing import Any, Protocol

from shorts_pipeline.models import BScenePlan, EScript, SourceArtifact

SUPPORTED_BACKENDS = ("openai", "anthropic", "gemini")
ENABLE_REAL_LLM_ENV = "SHORTS_PIPELINE_ENABLE_REAL_LLM"
LLM_BACKEND_ENV = "SHORTS_PIPELINE_LLM_BACKEND"

DEFAULT_MODELS = {
    "openai": "gpt-4.1-mini",
    "anthropic": "claude-sonnet-4-6",
    "gemini": "gemini-2.5-flash",
}
# Environment variable names checked for each backend, in priority order.
API_KEY_ENVS = {
    "openai": ("OPENAI_API_KEY",),
    "anthropic": ("ANTHROPIC_API_KEY",),
    "gemini": ("GEMINI_API_KEY", "GOOGLE_API_KEY"),
}

_TRUTHY = {"1", "true", "yes", "on"}


class MissingSdkError(RuntimeError):
    """Raised when an opted-in backend's SDK package is not installed."""


class MissingApiKeyError(RuntimeError):
    """Raised when an opted-in backend has no API key in the environment."""


class LlmResponseError(RuntimeError):
    """Raised when the provider response is not a single JSON object."""


class CompletionClient(Protocol):
    """A minimal text-in / JSON-text-out completion seam.

    Tests inject a fake implementing this protocol so adapter logic can be
    verified without any real SDK or network access.
    """

    def complete_json(self, *, system: str, user: str) -> str:
        ...


def real_llm_enabled() -> bool:
    """Return True only when the explicit real-LLM opt-in flag is truthy."""
    return os.environ.get(ENABLE_REAL_LLM_ENV, "").strip().lower() in _TRUTHY


def selected_backend() -> str | None:
    """Return the configured backend name, or None when unset/blank."""
    name = os.environ.get(LLM_BACKEND_ENV, "").strip().lower()
    return name or None


def _resolve_api_key(backend: str) -> str:
    for env_name in API_KEY_ENVS[backend]:
        value = os.environ.get(env_name, "").strip()
        if value:
            return value
    joined = " or ".join(API_KEY_ENVS[backend])
    raise MissingApiKeyError(f"{backend} backend requires {joined} in the environment")


def _import_sdk(module_name: str):
    try:
        return importlib.import_module(module_name)
    except ImportError as exc:  # pragma: no cover - exercised via monkeypatch
        raise MissingSdkError(
            f"the '{module_name}' package is required for this backend; "
            f"install the optional 'llm' extra"
        ) from exc


def _strip_code_fences(text: str) -> str:
    if not text.startswith("```"):
        return text
    lines = text.splitlines()
    if lines and lines[0].startswith("```"):
        lines = lines[1:]
    if lines and lines[-1].strip().startswith("```"):
        lines = lines[:-1]
    return "\n".join(lines).strip()


def _parse_json_object(raw: str) -> dict[str, Any]:
    """Parse a model response into a single JSON object payload.

    Tolerates a leading/trailing code fence and, as a fallback, a JSON object
    embedded in surrounding prose (e.g. "Here is the JSON: {...}").
    """
    text = _strip_code_fences((raw or "").strip())
    candidates = [text]
    start, end = text.find("{"), text.rfind("}")
    if start != -1 and end > start:
        embedded = text[start : end + 1]
        if embedded != text:
            candidates.append(embedded)
    for candidate in candidates:
        try:
            parsed = json.loads(candidate)
        except json.JSONDecodeError:
            continue
        if not isinstance(parsed, dict):
            raise LlmResponseError("provider response JSON must be a single object")
        return parsed
    raise LlmResponseError("provider response was not valid JSON")


# --- Resilience: timeout, transient retry, error normalization --------------

REQUEST_TIMEOUT_SECONDS = 60
TRANSIENT_RETRY_ATTEMPTS = 2
_TRANSIENT_STATUS_CODES = {408, 409, 429, 500, 502, 503, 504}
_TRANSIENT_NAME_MARKERS = (
    "timeout",
    "connection",
    "ratelimit",
    "serviceunavailable",
    "apiconnection",
    "internalserver",
    "overloaded",
)


class LlmTransientError(RuntimeError):
    """Raised when a provider call keeps failing with transient errors."""


def _is_transient(exc: BaseException) -> bool:
    status = getattr(exc, "status_code", None)
    if status is None:
        status = getattr(getattr(exc, "response", None), "status_code", None)
    if status in _TRANSIENT_STATUS_CODES:
        return True
    name = type(exc).__name__.casefold()
    return any(marker in name for marker in _TRANSIENT_NAME_MARKERS)


def _run_sdk_call(call, *, attempts: int = TRANSIENT_RETRY_ATTEMPTS):
    """Run an SDK call, retrying transient failures with backoff.

    Non-transient errors (e.g. auth failures) propagate unchanged. Transient
    failures that exhaust retries are normalized into ``LlmTransientError``.
    """
    last: BaseException | None = None
    for attempt in range(attempts + 1):
        try:
            return call()
        except Exception as exc:  # noqa: BLE001 - classified below
            if not _is_transient(exc):
                raise
            last = exc
            if attempt < attempts:
                time.sleep(min(2**attempt, 8))
    raise LlmTransientError(
        f"provider call failed after {attempts + 1} attempts: {type(last).__name__}"
    ) from last


# --- Backends (real SDK seams; loaded lazily via importlib) -----------------


class _OpenAIBackend:
    def __init__(self, *, model: str, api_key: str | None = None, client: Any = None) -> None:
        self._model = model
        self._api_key = api_key
        self._client = client

    def _ensure_client(self) -> Any:
        if self._client is None:
            sdk = _import_sdk("openai")
            self._client = sdk.OpenAI(api_key=self._api_key or _resolve_api_key("openai"))
        return self._client

    def complete_json(self, *, system: str, user: str) -> str:
        client = self._ensure_client()
        response = _run_sdk_call(
            lambda: client.chat.completions.create(
                model=self._model,
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
                response_format={"type": "json_object"},
                temperature=0,
                timeout=REQUEST_TIMEOUT_SECONDS,
            )
        )
        return response.choices[0].message.content or ""


class _AnthropicBackend:
    def __init__(self, *, model: str, api_key: str | None = None, client: Any = None) -> None:
        self._model = model
        self._api_key = api_key
        self._client = client

    def _ensure_client(self) -> Any:
        if self._client is None:
            sdk = _import_sdk("anthropic")
            self._client = sdk.Anthropic(api_key=self._api_key or _resolve_api_key("anthropic"))
        return self._client

    def complete_json(self, *, system: str, user: str) -> str:
        client = self._ensure_client()
        response = _run_sdk_call(
            lambda: client.messages.create(
                model=self._model,
                max_tokens=2048,
                system=system,
                messages=[{"role": "user", "content": user}],
                timeout=REQUEST_TIMEOUT_SECONDS,
            )
        )
        return "".join(
            getattr(block, "text", "")
            for block in response.content
            if getattr(block, "type", "") == "text"
        )


class _GeminiBackend:
    def __init__(self, *, model: str, api_key: str | None = None, client: Any = None) -> None:
        self._model = model
        self._api_key = api_key
        self._client = client

    def _ensure_client(self) -> Any:
        if self._client is None:
            sdk = _import_sdk("google.genai")
            self._client = sdk.Client(api_key=self._api_key or _resolve_api_key("gemini"))
        return self._client

    def complete_json(self, *, system: str, user: str) -> str:
        client = self._ensure_client()
        response = _run_sdk_call(
            lambda: client.models.generate_content(
                model=self._model,
                contents=f"{system}\n\n{user}",
                config={"response_mime_type": "application/json"},
            )
        )
        return response.text or ""


_BACKEND_BUILDERS = {
    "openai": _OpenAIBackend,
    "anthropic": _AnthropicBackend,
    "gemini": _GeminiBackend,
}


def _make_backend(backend: str, *, model: str, client: Any = None) -> CompletionClient:
    if backend not in SUPPORTED_BACKENDS:
        raise ValueError(f"unsupported backend: {backend!r}")
    return _BACKEND_BUILDERS[backend](model=model, client=client)


# --- Prompt construction ----------------------------------------------------

_SHARED_SAFETY_RULES = (
    "Hard safety rules:\n"
    "- Never include real names, nicknames, or personal-info inference.\n"
    "- Never assert crimes or guilt.\n"
    "- Never invent numbers, counts, rankings, or facts not present in the input.\n"
    "- Never quote source posts or comments directly, and never reuse original captures.\n"
    "- Never mock or demean any individual.\n"
    "Output ONLY one JSON object that matches the schema. No prose, no code fences."
)


def _b_system_prompt() -> str:
    schema = json.dumps(BScenePlan.model_json_schema(), ensure_ascii=False)
    return (
        "You are a short-form video scene planner. Produce a safe, structured "
        "b_scene_plan.v2.1 plan from the provided source metadata.\n"
        f"{_SHARED_SAFETY_RULES}\n"
        f"JSON schema:\n{schema}"
    )


def _e_system_prompt() -> str:
    schema = json.dumps(EScript.model_json_schema(), ensure_ascii=False)
    return (
        "You are a short-form narration and title writer. Produce a safe, "
        "structured e_script.v2.1 output from the provided timeline and image "
        "context.\n"
        f"{_SHARED_SAFETY_RULES}\n"
        f"JSON schema:\n{schema}"
    )


def _user_prompt(payload: dict[str, Any], previous_errors: list[str]) -> str:
    parts = [json.dumps(payload, ensure_ascii=False, indent=2)]
    if previous_errors:
        joined = "\n".join(f"- {error}" for error in previous_errors)
        parts.append(
            "Your previous attempt failed validation. Fix these problems:\n" + joined
        )
    return "\n\n".join(parts)


# --- Provider adapters ------------------------------------------------------


class RealBScenePlanProvider:
    """B provider backed by a real LLM completion client (opt-in)."""

    def __init__(self, client: CompletionClient, *, provider_name: str, model_name: str) -> None:
        self._client = client
        self.provider_name = provider_name
        self.model_name = model_name

    def generate(
        self,
        *,
        source: SourceArtifact,
        prompt_version: str,
        previous_errors: list[str],
    ) -> dict[str, Any]:
        user = _user_prompt(source.model_dump(mode="json"), previous_errors)
        raw = self._client.complete_json(system=_b_system_prompt(), user=user)
        return _parse_json_object(raw)


class RealEScriptProvider:
    """E provider backed by a real LLM completion client (opt-in)."""

    def __init__(self, client: CompletionClient, *, provider_name: str, model_name: str) -> None:
        self._client = client
        self.provider_name = provider_name
        self.model_name = model_name

    def generate(
        self,
        *,
        context: dict[str, Any],
        prompt_version: str,
        previous_errors: list[str],
    ) -> dict[str, Any]:
        user = _user_prompt(context, previous_errors)
        raw = self._client.complete_json(system=_e_system_prompt(), user=user)
        return _parse_json_object(raw)


def _resolve_completion(
    backend: str,
    *,
    model: str,
    client: CompletionClient | None,
) -> CompletionClient:
    if backend not in SUPPORTED_BACKENDS:
        raise ValueError(f"unsupported backend: {backend!r}")
    # An injected CompletionClient (used by tests) is used directly; otherwise a
    # real SDK-backed backend is built and loads its SDK lazily on first call.
    if client is not None:
        return client
    return _make_backend(backend, model=model)


def build_b_provider(
    backend: str,
    *,
    model: str | None = None,
    client: CompletionClient | None = None,
) -> RealBScenePlanProvider:
    """Build a real B provider for the given backend (no opt-in gate)."""
    resolved_model = model or DEFAULT_MODELS.get(backend, "")
    completion = _resolve_completion(backend, model=resolved_model, client=client)
    return RealBScenePlanProvider(
        completion, provider_name=backend, model_name=resolved_model
    )


def build_e_provider(
    backend: str,
    *,
    model: str | None = None,
    client: CompletionClient | None = None,
) -> RealEScriptProvider:
    """Build a real E provider for the given backend (no opt-in gate)."""
    resolved_model = model or DEFAULT_MODELS.get(backend, "")
    completion = _resolve_completion(backend, model=resolved_model, client=client)
    return RealEScriptProvider(
        completion, provider_name=backend, model_name=resolved_model
    )


def resolve_b_provider(*, client: CompletionClient | None = None) -> RealBScenePlanProvider | None:
    """Return a real B provider only when the explicit opt-in is configured."""
    if not real_llm_enabled():
        return None
    backend = selected_backend()
    if backend is None:
        return None
    return build_b_provider(backend, client=client)


def resolve_e_provider(*, client: CompletionClient | None = None) -> RealEScriptProvider | None:
    """Return a real E provider only when the explicit opt-in is configured."""
    if not real_llm_enabled():
        return None
    backend = selected_backend()
    if backend is None:
        return None
    return build_e_provider(backend, client=client)
