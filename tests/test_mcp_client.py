"""MCP client 单元测试：全程 mock，不拉真子进程。"""
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from my_small_agent.mcp_client import MCPServerConfig, load_mcp_config
from my_small_agent.mcp_client import _make_tool_name, _stringify_result
from my_small_agent.mcp_client import MCPTool
from my_small_agent.mcp_client import register_mcp_tools
from my_small_agent.tools import ToolRegistry
import my_small_agent.mcp_client as mcp_client


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


def test_make_tool_name_prefixes_server_and_tool():
    assert _make_tool_name("mysql", "sync") == "mcp_mysql_sync"


def test_make_tool_name_sanitizes_illegal_chars():
    assert _make_tool_name("my.sql:x", "a/b") == "mcp_my_sql_x_a_b"


def test_make_tool_name_truncates_to_64():
    name = _make_tool_name("s" * 40, "t" * 40)
    assert len(name) == 64


def test_stringify_result_joins_text_blocks():
    result = SimpleNamespace(content=[
        SimpleNamespace(text="hello"),
        SimpleNamespace(text="world"),
    ])
    assert _stringify_result(result) == "hello\nworld"


def test_stringify_result_empty_content_returns_json():
    result = SimpleNamespace(content=[])
    out = _stringify_result(result)
    assert out == "[]"


class _FakeStdioCtx:
    """假 stdio_client：async with 返回 (read, write) 哨兵。"""
    async def __aenter__(self):
        return ("read", "write")

    async def __aexit__(self, *exc):
        return False


class _FakeSession:
    """假 ClientSession：可预设 list_tools / call_tool 的返回。"""
    def __init__(self, read, write, *, tools=None, call_result=None, call_error=None):
        self._tools = tools or []
        self._call_result = call_result
        self._call_error = call_error
        self.calls = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def initialize(self):
        pass

    async def list_tools(self):
        return SimpleNamespace(tools=self._tools)

    async def call_tool(self, name, arguments):
        self.calls.append((name, arguments))
        if self._call_error is not None:
            raise self._call_error
        return self._call_result


def _patch_connection(monkeypatch, *, tools=None, call_result=None, call_error=None):
    """monkeypatch stdio_client 与 ClientSession，返回捕获到的 session。"""
    captured = {}

    def fake_stdio_client(params):
        captured["params"] = params
        return _FakeStdioCtx()

    def fake_client_session(read, write):
        session = _FakeSession(
            read, write, tools=tools,
            call_result=call_result, call_error=call_error,
        )
        captured["session"] = session
        return session

    monkeypatch.setattr(mcp_client, "stdio_client", fake_stdio_client)
    monkeypatch.setattr(mcp_client, "ClientSession", fake_client_session)
    return captured


@pytest.mark.asyncio
async def test_mcp_tool_execute_calls_remote_and_stringifies(monkeypatch):
    result = SimpleNamespace(content=[SimpleNamespace(text="42")])
    captured = _patch_connection(monkeypatch, call_result=result)
    cfg = MCPServerConfig(name="calc", command="python", args=["s.py"])
    tool = MCPTool(
        registered_name="mcp_calc_add",
        remote_tool_name="add",
        description="add numbers",
        parameters={"type": "object", "properties": {}},
        server_config=cfg,
    )

    out = await tool.execute(a=5, b=3)

    assert out == "42"
    assert captured["session"].calls == [("add", {"a": 5, "b": 3})]


def test_mcp_tool_danger_level_and_category():
    cfg = MCPServerConfig(name="s", command="python")
    tool = MCPTool("mcp_s_t", "t", "d", {}, cfg)
    assert tool.danger_level == "dangerous"
    assert tool.category == "write"


@pytest.mark.asyncio
async def test_mcp_tool_execute_error_returns_json(monkeypatch):
    _patch_connection(monkeypatch, call_error=RuntimeError("boom"))
    cfg = MCPServerConfig(name="s", command="python")
    tool = MCPTool("mcp_s_t", "t", "d", {}, cfg)

    out = await tool.execute()

    assert "error" in json.loads(out)


def _fake_tool(name, description="d", schema=None):
    return SimpleNamespace(
        name=name, description=description,
        inputSchema=schema or {"type": "object", "properties": {}},
    )


@pytest.mark.asyncio
async def test_register_discovers_and_registers_tools(monkeypatch, tmp_path):
    cfg_file = tmp_path / "mcp.json"
    cfg_file.write_text(json.dumps({
        "mcpServers": {"calc": {"command": "python", "args": ["s.py"]}}
    }), encoding="utf-8")
    _patch_connection(monkeypatch, tools=[_fake_tool("add"), _fake_tool("sub")])
    registry = ToolRegistry()

    await register_mcp_tools(registry, str(cfg_file))

    add = registry.get("mcp_calc_add")
    assert add is not None
    assert add.danger_level == "dangerous"
    assert registry.get("mcp_calc_sub") is not None


@pytest.mark.asyncio
async def test_register_skips_name_conflict(monkeypatch, tmp_path):
    cfg_file = tmp_path / "mcp.json"
    cfg_file.write_text(json.dumps({
        "mcpServers": {"calc": {"command": "python"}}
    }), encoding="utf-8")
    _patch_connection(monkeypatch, tools=[_fake_tool("add"), _fake_tool("add")])
    registry = ToolRegistry()

    await register_mcp_tools(registry, str(cfg_file))

    # 两个同名 → 注册名相同，第二个被跳过；registry 里仍只有一个
    assert registry.get("mcp_calc_add") is not None


@pytest.mark.asyncio
async def test_register_degrades_when_server_fails(monkeypatch, tmp_path):
    cfg_file = tmp_path / "mcp.json"
    cfg_file.write_text(json.dumps({
        "mcpServers": {
            "bad": {"command": "python"},
            "good": {"command": "python"},
        }
    }), encoding="utf-8")

    async def fake_discover(cfg, timeout=30.0):
        if cfg.name == "bad":
            raise RuntimeError("connect failed")
        return [_fake_tool("ok")]

    monkeypatch.setattr(mcp_client, "_discover_tools", fake_discover)
    registry = ToolRegistry()

    # 不抛异常
    await register_mcp_tools(registry, str(cfg_file))

    assert registry.get("mcp_good_ok") is not None


@pytest.mark.asyncio
async def test_register_no_config_is_noop(tmp_path):
    registry = ToolRegistry()
    await register_mcp_tools(registry, str(tmp_path / "absent.json"))
    assert registry.list_all() == []
