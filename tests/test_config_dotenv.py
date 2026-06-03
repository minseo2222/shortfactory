"""Tests for the optional .env loading wired into config.load_local_env."""

from __future__ import annotations

from shorts_pipeline.config import load_local_env

PROBE = "SHORTS_PIPELINE_DOTENV_PROBE"


def test_load_local_env_loads_values_from_file(tmp_path, monkeypatch) -> None:
    monkeypatch.delenv(PROBE, raising=False)
    env_file = tmp_path / ".env"
    env_file.write_text(f"{PROBE}=loaded-from-dotenv\n", encoding="utf-8")

    loaded = load_local_env(dotenv_path=env_file)

    assert loaded is True
    import os

    assert os.environ[PROBE] == "loaded-from-dotenv"


def test_load_local_env_does_not_override_existing(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv(PROBE, "already-set")
    env_file = tmp_path / ".env"
    env_file.write_text(f"{PROBE}=from-file\n", encoding="utf-8")

    load_local_env(dotenv_path=env_file)

    import os

    assert os.environ[PROBE] == "already-set"


def test_load_local_env_missing_file_is_noop(tmp_path) -> None:
    loaded = load_local_env(dotenv_path=tmp_path / "does-not-exist.env")
    assert loaded is False
