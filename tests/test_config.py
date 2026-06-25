"""Tests for config module."""

import os
from unittest.mock import patch

import pytest

from my_small_agent.config import Settings


def test_settings_from_env_vars():
    """Settings should load from environment variables."""
    env = {
        "OPENAI_API_KEY": "sk-test-key",
        "OPENAI_BASE_URL": "https://api.example.com/v1",
        "OPENAI_MODEL": "gpt-4o-mini",
        "MAX_ITERATIONS": "5",
    }
    with patch.dict(os.environ, env, clear=False):
        settings = Settings(_env_file=None)
        assert settings.openai_api_key == "sk-test-key"
        assert settings.openai_base_url == "https://api.example.com/v1"
        assert settings.openai_model == "gpt-4o-mini"
        assert settings.max_iterations == 5


def test_settings_defaults():
    """Settings should have sensible defaults for optional fields."""
    env = {"OPENAI_API_KEY": "sk-test-key"}
    with patch.dict(os.environ, env, clear=False):
        settings = Settings(_env_file=None)
        assert settings.openai_base_url == "https://api.openai.com/v1"
        assert settings.openai_model == "gpt-4o"
        assert settings.max_iterations == 10


def test_settings_new_fields_defaults(monkeypatch):
    """新增配置项应有正确的默认值。"""
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    settings = Settings(_env_file=None)
    assert settings.enable_streaming is True
    assert settings.enable_thinking is True
    assert settings.timezone == "Asia/Shanghai"


def test_settings_new_fields_from_env(monkeypatch):
    """新增配置项应能从环境变量读取。"""
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.setenv("ENABLE_STREAMING", "false")
    monkeypatch.setenv("ENABLE_THINKING", "false")
    monkeypatch.setenv("TIMEZONE", "America/New_York")
    settings = Settings(_env_file=None)
    assert settings.enable_streaming is False
    assert settings.enable_thinking is False
    assert settings.timezone == "America/New_York"
