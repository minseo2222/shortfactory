"""Contract tests pinning the real LLM adapters to the installed SDK surface.

These verify that the exact client classes, request method paths, request
parameters, and response shapes that ``real_providers`` depends on actually
exist in the installed provider SDKs. Each test ``importorskip``s its SDK, so CI
(which does not install the optional ``llm`` extra) skips them and stays
offline; locally, with ``pip install -e ".[llm]"``, they catch adapter drift if
a provider SDK changes its API.

No network calls are made: SDK clients are constructed with a dummy key (the
clients are lazy and do not contact the network until a request is issued), and
response shapes are checked by class introspection only.

SDK modules are reached only via importlib / importorskip return values, never
via literal ``import openai`` style statements, so the CI network/provider
import guard stays valid for this file.
"""

from __future__ import annotations

import importlib
import inspect

import pytest

from shorts_pipeline.llm import real_providers as rp


def _params(func) -> set[str]:
    return set(inspect.signature(func).parameters)


def test_openai_adapter_matches_installed_sdk(monkeypatch) -> None:
    openai = pytest.importorskip("openai")
    assert hasattr(openai, "OpenAI")
    assert "api_key" in _params(openai.OpenAI.__init__)
    # Request method path and parameters used by _OpenAIBackend.complete_json.
    create = openai.resources.chat.completions.Completions.create
    assert {"model", "messages", "response_format", "temperature"} <= _params(create)
    # Response shape: response.choices[...].message.content.
    chat_types = importlib.import_module("openai.types.chat")
    assert "choices" in chat_types.ChatCompletion.model_fields
    # The backend constructs the real client (lazy, no network) via importlib.
    monkeypatch.setenv("OPENAI_API_KEY", "dummy-offline-key")
    backend = rp.build_b_provider("openai")._client
    client = backend._ensure_client()
    assert callable(client.chat.completions.create)


def test_anthropic_adapter_matches_installed_sdk(monkeypatch) -> None:
    anthropic = pytest.importorskip("anthropic")
    assert hasattr(anthropic, "Anthropic")
    assert "api_key" in _params(anthropic.Anthropic.__init__)
    create = anthropic.resources.messages.Messages.create
    assert {"model", "max_tokens", "system", "messages"} <= _params(create)
    # Response shape: text blocks expose .type and .text.
    atypes = importlib.import_module("anthropic.types")
    assert {"text", "type"} <= set(atypes.TextBlock.model_fields)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "dummy-offline-key")
    backend = rp.build_b_provider("anthropic")._client
    client = backend._ensure_client()
    assert callable(client.messages.create)


def test_gemini_adapter_matches_installed_sdk(monkeypatch) -> None:
    genai = pytest.importorskip("google.genai")
    gmodels = importlib.import_module("google.genai.models")
    assert hasattr(genai, "Client")
    assert "api_key" in _params(genai.Client.__init__)
    assert {"model", "contents", "config"} <= _params(gmodels.Models.generate_content)
    monkeypatch.setenv("GEMINI_API_KEY", "dummy-offline-key")
    backend = rp.build_b_provider("gemini")._client
    client = backend._ensure_client()
    assert callable(client.models.generate_content)
