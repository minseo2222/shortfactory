"""Tests for the ``doctor`` dev CLI command (local readiness report).

Offline and secret-free: doctor reports only presence booleans and env var
names, never any API key value.
"""

from __future__ import annotations

import json

from shorts_pipeline import dev_cli

_REAL_LLM_ENV = (
    "SHORTS_PIPELINE_ENABLE_REAL_LLM",
    "SHORTS_PIPELINE_LLM_BACKEND",
    "OPENAI_API_KEY",
    "ANTHROPIC_API_KEY",
    "GEMINI_API_KEY",
    "GOOGLE_API_KEY",
)


def _clear(monkeypatch) -> None:
    for name in _REAL_LLM_ENV:
        monkeypatch.delenv(name, raising=False)


def test_doctor_reports_fake_when_unconfigured(monkeypatch, capsys) -> None:
    _clear(monkeypatch)
    code = dev_cli.main(["doctor", "--json"])
    assert code == dev_cli.SUCCESS
    summary = json.loads(capsys.readouterr().out)
    assert summary["provider_mode"] == "fake"
    assert summary["real_ready"] is False
    assert any("SHORTS_PIPELINE_ENABLE_REAL_LLM" in item for item in summary["missing"])
    assert "optional_deps_installed" in summary


def test_doctor_strict_fails_when_not_ready(monkeypatch, capsys) -> None:
    _clear(monkeypatch)
    code = dev_cli.main(["doctor", "--strict"])
    assert code == dev_cli.RUNTIME_ERROR
    assert "not fully configured" in capsys.readouterr().err


def test_doctor_reports_source_readiness(monkeypatch, capsys) -> None:
    _clear(monkeypatch)
    monkeypatch.delenv("NAVER_CLIENT_ID", raising=False)
    monkeypatch.delenv("NAVER_CLIENT_SECRET", raising=False)
    monkeypatch.setenv("YOUTUBE_API_KEY", "yt-key")
    code = dev_cli.main(["doctor", "--json"])
    assert code == dev_cli.SUCCESS
    sources = json.loads(capsys.readouterr().out)["sources_ready"]
    assert sources["rss"] is True and sources["single_link"] is True
    assert sources["youtube"] is True  # key set
    assert sources["naver"] is False  # no credentials


def test_doctor_never_prints_key_value(monkeypatch, capsys) -> None:
    _clear(monkeypatch)
    monkeypatch.setenv("SHORTS_PIPELINE_ENABLE_REAL_LLM", "1")
    monkeypatch.setenv("SHORTS_PIPELINE_LLM_BACKEND", "openai")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-doctor-secret-xyz")
    code = dev_cli.main(["doctor", "--json"])
    assert code == dev_cli.SUCCESS
    out = capsys.readouterr().out
    assert "sk-doctor-secret-xyz" not in out
    summary = json.loads(out)
    assert summary["real_ready"] is True
    assert summary["key_present"] is True
