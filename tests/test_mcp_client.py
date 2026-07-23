"""MCP client 单元测试：全程 mock，不拉真子进程。"""
import json
from pathlib import Path

import pytest

from my_small_agent.mcp_client import MCPServerConfig, load_mcp_config


def test_load_config_parses_multiple_servers(tmp_path):
    cfg_file = tmp_path / "mcp.json"
    cfg_file.write_text(json.dumps({
        "mcpServers": {
            "everything": {"command": "npx", "args": ["-y", "srv"]},
            "mysql": {"command": "python", "args": ["s.py"], "env": {"PWD": "x"}},
        }
    }), encoding="utf-8")

    servers = load_mcp_config(str(cfg_file))

    assert set(servers) == {"everything", "mysql"}
    assert servers["everything"].command == "npx"
    assert servers["everything"].args == ["-y", "srv"]
    assert servers["everything"].env == {}
    assert servers["mysql"].env == {"PWD": "x"}


def test_load_config_missing_file_returns_empty():
    assert load_mcp_config("does_not_exist_xyz.json") == {}


def test_load_config_bad_json_returns_empty(tmp_path):
    cfg_file = tmp_path / "mcp.json"
    cfg_file.write_text("{ not valid json", encoding="utf-8")
    assert load_mcp_config(str(cfg_file)) == {}


def test_load_config_skips_entry_without_command(tmp_path):
    cfg_file = tmp_path / "mcp.json"
    cfg_file.write_text(json.dumps({
        "mcpServers": {
            "good": {"command": "python"},
            "bad": {"args": ["x"]},
        }
    }), encoding="utf-8")

    servers = load_mcp_config(str(cfg_file))

    assert set(servers) == {"good"}


def test_load_config_missing_mcpservers_key_returns_empty(tmp_path):
    cfg_file = tmp_path / "mcp.json"
    cfg_file.write_text(json.dumps({"other": {}}), encoding="utf-8")
    assert load_mcp_config(str(cfg_file)) == {}


def test_load_config_non_dict_root_returns_empty(tmp_path):
    cfg_file = tmp_path / "mcp.json"
    cfg_file.write_text("[1, 2, 3]", encoding="utf-8")
    assert load_mcp_config(str(cfg_file)) == {}
