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
