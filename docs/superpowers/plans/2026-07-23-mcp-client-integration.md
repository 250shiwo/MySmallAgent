# MCP Client 接入 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 为 MySmallAgent 新增 MCP client，能读取 `mcp.json`、连接 stdio MCP server、把远程 tools 包装成本地 `Tool` 注册进 `ToolRegistry`，在 CLI 与 QQ 两个前端可用。

**Architecture:** 单个扁平模块 `mcp_client.py`。启动时对每个 server 做一次性连接发现 tools 并注册；运行时每次调用即时连接（连→调→断，自包含），绕开跨事件循环/跨 task 的 SDK 坑。全程降级不阻断。

**Tech Stack:** Python 3.11+，官方 `mcp` SDK（stdio transport），pytest + pytest-asyncio，全程 mock 不拉真子进程。

## Global Constraints

- Python `>=3.11`（已满足）。
- 新增依赖：`mcp>=1.12`（官方 Model Context Protocol Python SDK），用 `uv sync` 安装。
- 所有 MCP 工具：`danger_level="dangerous"`、`category="write"`（agent 无法预判危险性；CLI 弹确认、Plan 模式自动排除、QQ 自动批准）。
- 工具命名：`mcp_{server}_{tool}`；非 `[a-zA-Z0-9_-]` 字符替换为 `_`；超 64 字符保留前 64。
- 传输仅 stdio；连接模型为"每次调用即时连接"（ephemeral per-call），不维持持久连接。
- 模块内 logger 用标准库：`logger = logging.getLogger(__name__)`（框架中立）。
- 降级不阻断：`mcp.json` 缺失/坏 JSON/单 server 连接失败都只记 warning，agent 照常启动。
- 本机测试命令（规避沙箱临时目录权限）：`uv run pytest -p no:cacheprovider --basetemp=.pytest_tmp -q`，测完删除 `.pytest_tmp`。

---

### Task 1: 依赖 + 配置解析层

**Files:**
- Modify: `pyproject.toml`（dependencies 加 `mcp>=1.12`）
- Create: `mcp.json.example`（项目根）
- Modify: `.gitignore`（新增 `mcp.json`）
- Create: `my_small_agent/mcp_client.py`（imports + `MCPServerConfig` + `load_mcp_config`）
- Test: `tests/test_mcp_client.py`

**Interfaces:**
- Produces:
  - `MCPServerConfig(name: str, command: str, args: list[str], env: dict[str, str])`（dataclass）
  - `load_mcp_config(path: str = "mcp.json") -> dict[str, MCPServerConfig]`

- [ ] **Step 1: 加依赖并安装**

编辑 `pyproject.toml`，在 `dependencies` 列表末尾（`"qq-botpy>=1.1.5",` 之后）加一行：

```toml
    "mcp>=1.12",
```

然后运行：

```bash
uv sync
```

Expected: 安装成功，`mcp` 及其依赖出现在环境中。

- [ ] **Step 2: 创建配置样例与 gitignore**

创建 `mcp.json.example`：

```json
{
  "mcpServers": {
    "everything": {
      "command": "npx",
      "args": ["-y", "@modelcontextprotocol/server-everything"]
    }
  }
}
```

在 `.gitignore` 末尾追加：

```
mcp.json
```

- [ ] **Step 3: 写失败测试（配置解析）**

创建 `tests/test_mcp_client.py`：

```python
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
```

- [ ] **Step 4: 运行测试确认失败**

Run: `uv run pytest -p no:cacheprovider --basetemp=.pytest_tmp tests/test_mcp_client.py -q`
Expected: FAIL（`ModuleNotFoundError` 或 `ImportError: cannot import name`，因为 `mcp_client.py` 还没有内容）

- [ ] **Step 5: 实现配置层**

创建 `my_small_agent/mcp_client.py`：

```python
"""
MCP client 模块 - 连接外部 MCP server，把其 tools 包装为本地 Tool。

设计：
  - 仅 stdio 传输
  - 每次调用即时连接（连→调→断，自包含），不维持持久连接
  - 全程降级不阻断：MCP 不可用时 agent 正常运行
"""

import asyncio
import json
import logging
import re
from dataclasses import dataclass, field
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from my_small_agent.tools.base import Tool

logger = logging.getLogger(__name__)


@dataclass
class MCPServerConfig:
    """单个 MCP server 的启动参数（来自 mcp.json 的一项）。"""
    name: str
    command: str
    args: list[str] = field(default_factory=list)
    env: dict[str, str] = field(default_factory=dict)


def load_mcp_config(path: str = "mcp.json") -> dict[str, MCPServerConfig]:
    """
    读取 mcp.json，返回 {name: MCPServerConfig}。

    降级不阻断：文件不存在/坏 JSON/结构非法 → 记 warning 返回 {}；
    单条缺 command → 跳过该项。
    """
    p = Path(path)
    if not p.exists():
        return {}
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as e:
        logger.warning(f"mcp.json 解析失败，忽略 MCP 配置：{e}")
        return {}

    servers_raw = data.get("mcpServers")
    if not isinstance(servers_raw, dict):
        logger.warning("mcp.json 缺少 mcpServers 对象，忽略 MCP 配置")
        return {}

    result: dict[str, MCPServerConfig] = {}
    for name, entry in servers_raw.items():
        if not isinstance(entry, dict) or "command" not in entry:
            logger.warning(f"MCP server '{name}' 缺少 command，已跳过")
            continue
        result[name] = MCPServerConfig(
            name=name,
            command=entry["command"],
            args=list(entry.get("args", [])),
            env=dict(entry.get("env", {})),
        )
    return result
```

- [ ] **Step 6: 运行测试确认通过**

Run: `uv run pytest -p no:cacheprovider --basetemp=.pytest_tmp tests/test_mcp_client.py -q`
Expected: PASS（5 passed）

- [ ] **Step 7: 提交**

```bash
git add pyproject.toml uv.lock mcp.json.example .gitignore my_small_agent/mcp_client.py tests/test_mcp_client.py
git commit -m "feat: MCP config parsing layer + mcp dependency"
```

---

### Task 2: 纯函数 helper（命名 + 结果拼接）

**Files:**
- Modify: `my_small_agent/mcp_client.py`
- Test: `tests/test_mcp_client.py`

**Interfaces:**
- Consumes: 无
- Produces:
  - `_make_tool_name(server: str, tool: str) -> str`
  - `_stringify_result(result) -> str`（result 有 `.content` 列表，每块可能有 `.text`）

- [ ] **Step 1: 写失败测试**

在 `tests/test_mcp_client.py` 顶部 import 追加：

```python
from types import SimpleNamespace

from my_small_agent.mcp_client import _make_tool_name, _stringify_result
```

追加测试函数：

```python
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
```

- [ ] **Step 2: 运行测试确认失败**

Run: `uv run pytest -p no:cacheprovider --basetemp=.pytest_tmp tests/test_mcp_client.py -q`
Expected: FAIL（`ImportError: cannot import name '_make_tool_name'`）

- [ ] **Step 3: 实现 helper**

在 `my_small_agent/mcp_client.py` 的 `load_mcp_config` 之后追加：

```python
def _make_tool_name(server: str, tool: str) -> str:
    """拼 mcp_{server}_{tool}，净化非法字符，保留前 64 字符。"""
    raw = f"mcp_{server}_{tool}"
    cleaned = re.sub(r"[^a-zA-Z0-9_-]", "_", raw)
    return cleaned[:64]


def _stringify_result(result) -> str:
    """把 CallToolResult 的 content 块拼为字符串；无文本时回退 JSON。"""
    parts: list[str] = []
    for block in getattr(result, "content", None) or []:
        text = getattr(block, "text", None)
        if text is not None:
            parts.append(text)
    if parts:
        return "\n".join(parts)
    try:
        return json.dumps(
            getattr(result, "content", []), default=str, ensure_ascii=False
        )
    except (TypeError, ValueError):
        return str(result)
```

- [ ] **Step 4: 运行测试确认通过**

Run: `uv run pytest -p no:cacheprovider --basetemp=.pytest_tmp tests/test_mcp_client.py -q`
Expected: PASS（10 passed）

- [ ] **Step 5: 提交**

```bash
git add my_small_agent/mcp_client.py tests/test_mcp_client.py
git commit -m "feat: MCP tool name + result stringify helpers"
```

---

### Task 3: MCPTool + 即时调用

**Files:**
- Modify: `my_small_agent/mcp_client.py`
- Test: `tests/test_mcp_client.py`

**Interfaces:**
- Consumes: `_stringify_result`、`MCPServerConfig`
- Produces:
  - `class MCPTool(Tool)`：`__init__(registered_name, remote_tool_name, description, parameters, server_config)`；`danger_level="dangerous"`；`category="write"`；`async execute(**kwargs) -> str`
  - `async _call_remote_tool(cfg: MCPServerConfig, tool_name: str, arguments: dict) -> str`
  - 模块级名 `stdio_client`、`ClientSession`（供测试 monkeypatch）

- [ ] **Step 1: 写失败测试**

在 `tests/test_mcp_client.py` 顶部 import 追加：

```python
from my_small_agent.mcp_client import MCPServerConfig, MCPTool
import my_small_agent.mcp_client as mcp_client
```

追加共享的异步假实现 + 测试：

```python
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
```

- [ ] **Step 2: 运行测试确认失败**

Run: `uv run pytest -p no:cacheprovider --basetemp=.pytest_tmp tests/test_mcp_client.py -q`
Expected: FAIL（`ImportError: cannot import name 'MCPTool'`）

- [ ] **Step 3: 实现 MCPTool + _call_remote_tool**

在 `my_small_agent/mcp_client.py` 的 helper 之后追加：

```python
async def _call_remote_tool(cfg: MCPServerConfig, tool_name: str, arguments: dict) -> str:
    """即时连接远程 server，调用 tool，返回文本结果（连→调→断，自包含）。"""
    params = StdioServerParameters(
        command=cfg.command, args=cfg.args, env=cfg.env or None
    )
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            result = await session.call_tool(tool_name, arguments)
            return _stringify_result(result)


class MCPTool(Tool):
    """包装单个远程 MCP tool。execute 时即时连接。"""

    danger_level = "dangerous"
    category = "write"

    def __init__(
        self, registered_name, remote_tool_name, description, parameters, server_config
    ):
        self.name = registered_name
        self._remote_tool_name = remote_tool_name
        self.description = description
        self.parameters = parameters
        self._server_config = server_config

    async def execute(self, **kwargs) -> str:
        try:
            return await _call_remote_tool(
                self._server_config, self._remote_tool_name, kwargs
            )
        except Exception as e:
            return json.dumps(
                {"error": f"MCP tool '{self.name}' failed: {e}"},
                ensure_ascii=False,
            )
```

- [ ] **Step 4: 运行测试确认通过**

Run: `uv run pytest -p no:cacheprovider --basetemp=.pytest_tmp tests/test_mcp_client.py -q`
Expected: PASS（13 passed）

- [ ] **Step 5: 提交**

```bash
git add my_small_agent/mcp_client.py tests/test_mcp_client.py
git commit -m "feat: MCPTool with per-call ephemeral connection"
```

---

### Task 4: 发现与注册

**Files:**
- Modify: `my_small_agent/mcp_client.py`
- Test: `tests/test_mcp_client.py`

**Interfaces:**
- Consumes: `load_mcp_config`、`_make_tool_name`、`MCPTool`、`stdio_client`、`ClientSession`、`ToolRegistry`
- Produces:
  - `async _discover_tools(cfg: MCPServerConfig, timeout: float = 30.0) -> list`（返回远程 tool 列表，每个有 `.name`/`.description`/`.inputSchema`）
  - `async register_mcp_tools(registry, config_path: str = "mcp.json") -> None`

- [ ] **Step 1: 写失败测试**

在 `tests/test_mcp_client.py` 顶部 import 追加：

```python
from my_small_agent.mcp_client import register_mcp_tools
from my_small_agent.tools import ToolRegistry
```

追加测试：

```python
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
```

- [ ] **Step 2: 运行测试确认失败**

Run: `uv run pytest -p no:cacheprovider --basetemp=.pytest_tmp tests/test_mcp_client.py -q`
Expected: FAIL（`ImportError: cannot import name 'register_mcp_tools'`）

- [ ] **Step 3: 实现发现与注册**

在 `my_small_agent/mcp_client.py` 末尾追加：

```python
async def _discover_tools(cfg: MCPServerConfig, timeout: float = 30.0) -> list:
    """一次性连接 server 拉取 tool 列表（带超时），连→列→断。"""
    async def _connect():
        params = StdioServerParameters(
            command=cfg.command, args=cfg.args, env=cfg.env or None
        )
        async with stdio_client(params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                return (await session.list_tools()).tools

    return await asyncio.wait_for(_connect(), timeout=timeout)


async def register_mcp_tools(registry, config_path: str = "mcp.json") -> None:
    """
    启动时发现并注册所有 MCP server 的 tools。

    降级不阻断：单个 server 连接失败 → 记 warning、跳过、其余照常。
    """
    servers = load_mcp_config(config_path)
    for name, cfg in servers.items():
        try:
            tools = await _discover_tools(cfg)
        except Exception as e:
            logger.warning(f"MCP server '{name}' 连接失败，已跳过：{e}")
            continue
        for t in tools:
            registered = _make_tool_name(name, t.name)
            if registry.get(registered) is not None:
                logger.warning(f"工具名冲突，跳过：{registered}")
                continue
            registry.register(MCPTool(
                registered_name=registered,
                remote_tool_name=t.name,
                description=t.description or "",
                parameters=t.inputSchema or {"type": "object", "properties": {}},
                server_config=cfg,
            ))
        logger.info(f"MCP server '{name}' 已注册 {len(tools)} 个工具")
```

- [ ] **Step 4: 运行测试确认通过**

Run: `uv run pytest -p no:cacheprovider --basetemp=.pytest_tmp tests/test_mcp_client.py -q`
Expected: PASS（17 passed）

- [ ] **Step 5: 提交**

```bash
git add my_small_agent/mcp_client.py tests/test_mcp_client.py
git commit -m "feat: MCP tool discovery and registration with graceful degradation"
```

---

### Task 5: 前端接入（CLI + QQ）+ 冒烟验证

**Files:**
- Modify: `my_small_agent/__main__.py`（`main()` 内，注册 skill 工具之后）
- Modify: `my_small_agent/qq_bot.py`（`main()` 内，`client.run()` 之前）
- Test: 全量回归 + 手动冒烟

**Interfaces:**
- Consumes: `register_mcp_tools(registry, config_path)`

- [ ] **Step 1: 接入 CLI**

在 `my_small_agent/__main__.py` 的 `main()` 中，找到：

```python
        # 4.6 注册 skill 工具 + 组合工具到 ToolRegistry
        register_skill_tools(registry, skill_registry)
        registry.register(ResearchTopicTool(registry))
```

在其后新增（含 import）：

```python
        # 4.8 连接 MCP server 并注册其工具（失败降级，不阻断启动）
        from my_small_agent.mcp_client import register_mcp_tools
        await register_mcp_tools(registry, "mcp.json")
```

- [ ] **Step 2: 接入 QQ**

在 `my_small_agent/qq_bot.py` 的 `main()` 中，找到：

```python
        discover_skills()
        register_skill_tools(registry, skill_registry)
        registry.register(ResearchTopicTool(registry))
```

在其后新增：

```python
        # 连接 MCP server 并注册其工具（client.run() 前，自包含 asyncio.run）
        from my_small_agent.mcp_client import register_mcp_tools
        asyncio.run(register_mcp_tools(registry, "mcp.json"))
```

（`qq_bot.py` 顶部已 `import asyncio`，无需重复导入。）

- [ ] **Step 3: 全量回归**

Run: `uv run pytest -p no:cacheprovider --basetemp=.pytest_tmp -q`
Expected: 全部 PASS（原有测试 + 新增 17 个 MCP 测试，无回归）

- [ ] **Step 4: 手动冒烟验证（需要本机有 Node/npx）**

创建 `mcp.json`（从样例复制）：

```bash
copy mcp.json.example mcp.json
```

启动 CLI：

```bash
uv run agent
```

在 CLI 中输入 `/tools`，Expected: 工具列表中出现 `mcp_everything_*` 前缀的若干工具（如 `mcp_everything_add`、`mcp_everything_echo` 等），且标记为 `dangerous`。

在 CLI 中让 agent 调用一个 MCP 工具验证链路，例如输入：

```
用 echo 工具回显 "hello mcp"
```

Expected: agent 调用 `mcp_everything_echo`（CLI 弹危险确认，输入 y），返回包含 `hello mcp` 的结果。

若本机无 npx：跳过 Step 4，删除 `mcp.json`，仅以 Step 3 全量回归为准（`register_mcp_tools` 对缺失/失败 server 已降级）。

- [ ] **Step 5: 清理并提交**

```bash
del .pytest_tmp /s /q
git add my_small_agent/__main__.py my_small_agent/qq_bot.py
git commit -m "feat: wire MCP tool registration into CLI and QQ frontends"
```

（注意：`mcp.json` 已被 `.gitignore` 忽略，不会误提交。）

---

## Self-Review

**1. Spec coverage:**
- 配置解析（`load_mcp_config` + `MCPServerConfig` + `mcp.json.example` + gitignore）→ Task 1 ✅
- 工具命名 `_make_tool_name` + 结果拼接 `_stringify_result` → Task 2 ✅
- `MCPTool` + `_call_remote_tool`（per-call 即时连接、execute 异常返回 JSON）→ Task 3 ✅
- `_discover_tools` + `register_mcp_tools`（发现、注册、命名冲突跳过、降级不阻断、缺配置 noop）→ Task 4 ✅
- CLI + QQ 前端接入 → Task 5 ✅
- 依赖 `mcp` → Task 1 ✅
- 全部工具 `danger_level="dangerous"`/`category="write"` → Task 3 实现 + Task 4 断言 ✅
- 降级不阻断（缺文件/坏 JSON/缺 command/连接失败）→ Task 1 + Task 4 测试 ✅

**2. Placeholder scan:** 无 TBD/TODO；每个 code step 都有完整代码；每个 test step 都有可运行断言。✅

**3. Type consistency:**
- `MCPServerConfig(name, command, args, env)` 全任务一致 ✅
- `MCPTool(registered_name, remote_tool_name, description, parameters, server_config)` Task 3 定义、Task 4 调用一致 ✅
- `register_mcp_tools(registry, config_path)` Task 4 定义、Task 5 调用一致 ✅
- `_discover_tools(cfg, timeout)` Task 4 定义并被 test 4 monkeypatch，签名一致 ✅
- 模块级 `stdio_client`/`ClientSession` 名称在 Task 3 引入、Task 3/4 测试 monkeypatch 一致 ✅

无遗漏，计划完整。
