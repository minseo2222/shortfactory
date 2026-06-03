"""Offline unit tests for the optional real LLM provider adapters.

No real SDKs, API keys, or network access are used. The adapters expose a
``CompletionClient`` seam that these tests fill with a fake returning canned
JSON, so prompt construction, JSON parsing, the opt-in resolver, and error
handling are all verified deterministically.
"""

from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path

import pytest

from shorts_pipeline.b_service import generate_b_scene_plan
from shorts_pipeline.llm import real_providers as rp
from shorts_pipeline.models import BScenePlan, SourceArtifact
from shorts_pipeline.project_service import create_project_from_candidate

FIXTURES = Path(__file__).parent / "fixtures"


def fixed_clock() -> datetime:
    return datetime(2026, 5, 29, 10, 30, 0)


def valid_b_json() -> str:
    return (FIXTURES / "sample_b_scene_plan.json").read_text(encoding="utf-8")


def sample_source() -> SourceArtifact:
    return SourceArtifact(
        project_id="PRJ_20260529_0001",
        source_url="https://example.com/community/post/123",
        source_community="manual",
        source_title="A safe fictional source title",
        user_or_llm_summary="A neutral fictional summary for prompt grounding.",
        hook="A neutral hook.",
        why_shortable="A neutral rationale.",
        created_at="2026-05-29T10:30:00+09:00",
    )


class FakeClient:
    """Captures the last prompt and returns a configured response string."""

    def __init__(self, response: str) -> None:
        self.response = response
        self.last_system: str | None = None
        self.last_user: str | None = None
        self.calls = 0

    def complete_json(self, *, system: str, user: str) -> str:
        self.calls += 1
        self.last_system = system
        self.last_user = user
        return self.response


# --- Parsing and prompt construction ---------------------------------------


def test_real_b_provider_returns_parsed_payload() -> None:
    client = FakeClient(valid_b_json())
    provider = rp.build_b_provider("openai", client=client)
    payload = provider.generate(
        source=sample_source(), prompt_version="v", previous_errors=[]
    )
    assert isinstance(payload, dict)
    # The payload must remain a drop-in for the existing Pydantic contract.
    BScenePlan.model_validate(payload)
    assert provider.provider_name == "openai"
    assert provider.model_name == rp.DEFAULT_MODELS["openai"]


def test_real_e_provider_parses_fenced_json() -> None:
    fenced = "```json\n" + json.dumps({"schema_version": "e_script.v2.1"}) + "\n```"
    client = FakeClient(fenced)
    provider = rp.build_e_provider("anthropic", client=client)
    payload = provider.generate(context={"project_id": "x"}, prompt_version="v", previous_errors=[])
    assert payload == {"schema_version": "e_script.v2.1"}


def test_non_object_json_is_rejected() -> None:
    provider = rp.build_b_provider("gemini", client=FakeClient("[1, 2, 3]"))
    with pytest.raises(rp.LlmResponseError):
        provider.generate(source=sample_source(), prompt_version="v", previous_errors=[])


def test_invalid_json_is_rejected() -> None:
    provider = rp.build_b_provider("openai", client=FakeClient("not json at all"))
    with pytest.raises(rp.LlmResponseError):
        provider.generate(source=sample_source(), prompt_version="v", previous_errors=[])


def test_previous_errors_are_passed_into_user_prompt() -> None:
    client = FakeClient(valid_b_json())
    provider = rp.build_b_provider("openai", client=client)
    provider.generate(
        source=sample_source(),
        prompt_version="v",
        previous_errors=["scene_id values must be consecutive from s01"],
    )
    assert "scene_id values must be consecutive from s01" in (client.last_user or "")
    # System prompt must carry the hard safety rules.
    assert "Never assert crimes" in (client.last_system or "")


# --- Opt-in resolver --------------------------------------------------------


def test_resolver_returns_none_when_disabled(monkeypatch) -> None:
    monkeypatch.delenv(rp.ENABLE_REAL_LLM_ENV, raising=False)
    monkeypatch.setenv(rp.LLM_BACKEND_ENV, "openai")
    assert rp.resolve_b_provider() is None
    assert rp.resolve_e_provider() is None


def test_resolver_returns_none_when_enabled_without_backend(monkeypatch) -> None:
    monkeypatch.setenv(rp.ENABLE_REAL_LLM_ENV, "1")
    monkeypatch.delenv(rp.LLM_BACKEND_ENV, raising=False)
    assert rp.resolve_b_provider() is None


def test_resolver_builds_real_provider_when_opted_in(monkeypatch) -> None:
    monkeypatch.setenv(rp.ENABLE_REAL_LLM_ENV, "true")
    monkeypatch.setenv(rp.LLM_BACKEND_ENV, "openai")
    provider = rp.resolve_b_provider(client=FakeClient(valid_b_json()))
    assert isinstance(provider, rp.RealBScenePlanProvider)
    assert provider.provider_name == "openai"


def test_build_provider_rejects_unknown_backend() -> None:
    with pytest.raises(ValueError):
        rp.build_b_provider("grok", client=FakeClient("{}"))


# --- SDK / key error paths (no real SDK installed) --------------------------


def test_missing_sdk_raises_missing_sdk_error(monkeypatch) -> None:
    def fail_import(name: str):
        raise ImportError(f"no module named {name}")

    monkeypatch.setattr(rp.importlib, "import_module", fail_import)
    provider = rp.build_b_provider("openai")  # no injected client -> lazy load
    with pytest.raises(rp.MissingSdkError):
        provider.generate(source=sample_source(), prompt_version="v", previous_errors=[])


def test_missing_api_key_raises(monkeypatch) -> None:
    class FakeSdk:
        class OpenAI:
            def __init__(self, *, api_key: str) -> None:
                self.api_key = api_key

    monkeypatch.setattr(rp.importlib, "import_module", lambda name: FakeSdk)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    provider = rp.build_e_provider("openai")
    with pytest.raises(rp.MissingApiKeyError):
        provider.generate(context={}, prompt_version="v", previous_errors=[])


# --- Guard-discipline and secret-hygiene self-checks ------------------------


def test_module_has_no_literal_sdk_imports() -> None:
    """The CI network/provider import guard must not match this module."""
    source = Path(rp.__file__).read_text(encoding="utf-8")
    pattern = re.compile(
        r"^\s*(import|from)\s+"
        r"(openai|anthropic|google_genai|google\.genai|requests|httpx|"
        r"urllib\.request|urllib3|selenium|playwright)\b",
        re.MULTILINE,
    )
    assert pattern.search(source) is None


def test_provider_does_not_store_api_key() -> None:
    provider = rp.build_b_provider("openai", client=FakeClient("{}"))
    serialized = json.dumps(
        {k: str(v) for k, v in vars(provider).items()}, ensure_ascii=False
    )
    assert "api_key" not in serialized.lower()
    assert not hasattr(provider, "api_key")


# --- Service drop-in integration -------------------------------------------


def test_real_b_provider_drives_full_service_generation(tmp_path) -> None:
    db_path = tmp_path / "shorts.sqlite3"
    projects_root = tmp_path / "projects"
    candidate = json.loads((FIXTURES / "sample_source.json").read_text(encoding="utf-8"))
    project = create_project_from_candidate(
        candidate, db_path=db_path, projects_root=projects_root, clock=fixed_clock
    )
    provider = rp.build_b_provider("openai", client=FakeClient(valid_b_json()))

    plan = generate_b_scene_plan(
        project.project_id,
        db_path=db_path,
        projects_root=projects_root,
        provider=provider,
        clock=fixed_clock,
    )

    assert isinstance(plan, BScenePlan)
    assert (projects_root / project.project_id / "b_scene_plan.json").is_file()


# --- Adapter robustness: parsing, extraction, transient retry (V5) ----------

from types import SimpleNamespace  # noqa: E402


def test_parse_json_object_handles_prose_wrapped() -> None:
    assert rp._parse_json_object('Here is the JSON:\n```json\n{"a": 1}\n```') == {"a": 1}
    assert rp._parse_json_object('prefix {"x": 2} suffix text') == {"x": 2}


def test_openai_backend_extracts_content_and_tolerates_none() -> None:
    def make(content):
        completions = SimpleNamespace(
            create=lambda **kw: SimpleNamespace(
                choices=[SimpleNamespace(message=SimpleNamespace(content=content))]
            )
        )
        return SimpleNamespace(chat=SimpleNamespace(completions=completions))

    backend = rp._OpenAIBackend(model="m", client=make('{"ok": true}'))
    assert backend.complete_json(system="s", user="u") == '{"ok": true}'
    none_backend = rp._OpenAIBackend(model="m", client=make(None))
    assert none_backend.complete_json(system="s", user="u") == ""


def test_anthropic_backend_joins_only_text_blocks() -> None:
    blocks = [
        SimpleNamespace(type="image", text="IGNORED"),
        SimpleNamespace(type="text", text='{"a": '),
        SimpleNamespace(type="text", text="1}"),
    ]
    client = SimpleNamespace(
        messages=SimpleNamespace(create=lambda **kw: SimpleNamespace(content=blocks))
    )
    backend = rp._AnthropicBackend(model="m", client=client)
    assert backend.complete_json(system="s", user="u") == '{"a": 1}'


def test_gemini_backend_tolerates_none_text() -> None:
    client = SimpleNamespace(
        models=SimpleNamespace(generate_content=lambda **kw: SimpleNamespace(text=None))
    )
    backend = rp._GeminiBackend(model="m", client=client)
    assert backend.complete_json(system="s", user="u") == ""


class _RateLimitError(Exception):
    status_code = 429


def test_transient_errors_retry_then_raise_normalized(monkeypatch) -> None:
    monkeypatch.setattr(rp.time, "sleep", lambda *_a, **_k: None)
    calls = {"n": 0}

    def always_fail():
        calls["n"] += 1
        raise _RateLimitError("rate limited")

    with pytest.raises(rp.LlmTransientError):
        rp._run_sdk_call(always_fail, attempts=2)
    assert calls["n"] == 3  # 1 initial + 2 retries


def test_transient_then_success(monkeypatch) -> None:
    monkeypatch.setattr(rp.time, "sleep", lambda *_a, **_k: None)
    calls = {"n": 0}

    def flaky():
        calls["n"] += 1
        if calls["n"] == 1:
            raise _RateLimitError("rate limited")
        return "ok"

    assert rp._run_sdk_call(flaky, attempts=2) == "ok"


def test_non_transient_error_propagates_unchanged() -> None:
    def fail():
        raise ValueError("bad request")

    with pytest.raises(ValueError):
        rp._run_sdk_call(fail, attempts=2)
