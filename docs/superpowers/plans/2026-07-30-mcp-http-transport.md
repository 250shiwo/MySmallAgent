# MCP Client Streamable HTTP 传输支持 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让 MCP client 支持通过 Streamable HTTP 连接远程 MCP server（`mcp.json` 中用 `url` 字段声明），stdio 完全向后兼容。

**Architecture:** 在 `MCPServerConfig` 上增加 `url`/`transport` 字段，`load_mcp_config` 按「有 `url` → http，有 `command` → stdio」分流；把两处重复的建连代码抽成统一的 `_connect(cfg)` 异步上下文管理器，内部按 `transport` 选择 `stdio_client` 或 `streamablehttp_client`。保持「每次调用即时连接（连→调→断）、降级不阻断」的现有设计。

**Tech Stack:** Python 3.12+、`mcp` SDK 1.28.1（`mcp.client.streamable_http.streamablehttp_client`）、pytest + pytest-asyncio（全 mock，不起真服务）。

## Global Constraints

- 仅支持 Streamable HTTP，不支持旧版 SSE、不加鉴权 header、不做持久连接
- 现有 stdio 行为与全部现有测试**一行不改**，必须保持全绿
- 降级不阻断：任何 server 连不上只记 warning，agent 照常启动
- 测试命令统一用 `uv run pytest`（Windows PowerShell，分隔符用 `;` 不用 `&&`）
- 注释与日志风格沿用现有中文注释风格

## 现状速览（给零上下文工程师）

- `my_small_agent/mcp_client.py`（178 行）：现在只支持 stdio。关键成员：
  - `MCPServerConfig`：dataclass，字段 `name/command/args/env`
  - `load_mcp_config(path)`：解析 `mcp.json`，缺 `command` 的条目跳过
  - `_call_remote_tool(cfg, tool_name, arguments)`：连→调→断
  - `_discover_tools(cfg, timeout)`：连→列→断，带 30s 超时
  - `MCPTool`：包装远程 tool，`execute` 内部捕获所有异常返回 JSON error
  - `register_mcp_tools(registry, config_path)`：启动时发现并注册
- `tests/test_mcp_client.py`（259 行）：全 mock。`_FakeStdioCtx` 假装 `stdio_client`（返回二元组），`_FakeSession` 假装 `ClientSession`，`_patch_connection` 做 monkeypatch。
- **注意**：`streamablehttp_client` 的 `__aenter__` 返回**三元组** `(read, write, get_session_id)`，与 `stdio_client` 的二元组不同。

---

### Task 1: 配置层——`MCPServerConfig` 增加 HTTP 字段 + `load_mcp_config` 分流

**Files:**
- Modify: `my_small_agent/mcp_client.py`（`MCPServerConfig` 定义处约 L25-31，`load_mcp_config` 循环体约 L59-70）
- Test: `tests/test_mcp_client.py`

**Interfaces:**
- Produces: `MCPServerConfig` 新字段 `url: str = ""`、`transport: str = "stdio"`（取值 `"stdio"` 或 `"http"`），`command` 改为有默认值 `""`。Task 2 依赖 `cfg.transport` 与 `cfg.url`。

- [ ] **Step 1: 写失败测试**

在 `tests/test_mcp_client.py` 的 `test_load_config_skips_entry_without_command` 之后追加：

```python
def test_load_config_parses_http_server(tmp_path):
    cfg_file = tmp_path / "mcp.json"
    cfg_file.write_text(json.dumps({
        "mcpServers": {"remote": {"url": "http://localhost:8000/mcp"}}
    }), encoding="utf-8")

    servers = load_mcp_config(str(cfg_file))

    assert servers["remote"].transport == "http"
    assert servers["remote"].url == "http://localhost:8000/mcp"


def test_load_config_stdio_entry_has_stdio_transport(tmp_path):
    cfg_file = tmp_path / "mcp.json"
    cfg_file.write_text(json.dumps({
        "mcpServers": {"local": {"command": "python", "args": ["s.py"]}}
    }), encoding="utf-8")

    servers = load_mcp_config(str(cfg_file))

    assert servers["local"].transport == "stdio"
    assert servers["local"].url == ""


def test_load_config_url_takes_precedence_over_command(tmp_path):
    cfg_file = tmp_path / "mcp.json"
    cfg_file.write_text(json.dumps({
        "mcpServers": {"both": {
            "url": "http://h:1/mcp", "command": "python"
        }}
    }), encoding="utf-8")

    servers = load_mcp_config(str(cfg_file))

    assert servers["both"].transport == "http"
    assert servers["both"].url == "http://h:1/mcp"
```

- [ ] **Step 2: 运行测试确认失败**

Run: `uv run pytest tests/test_mcp_client.py -k "http_server or stdio_transport or precedence" -v`
Expected: 3 个 FAIL（`TypeError: unexpected keyword argument 'url'` 或 `AttributeError: transport`）

- [ ] **Step 3: 最小实现**

修改 `my_small_agent/mcp_client.py` 中 `MCPServerConfig`：

```python
@dataclass
class MCPServerConfig:
    """单个 MCP server 的连接参数（来自 mcp.json 的一项）。"""
    name: str
    command: str = ""                        # stdio 传输用
    args: list[str] = field(default_factory=list)
    env: dict[str, str] = field(default_factory=dict)
    url: str = ""                            # HTTP 传输用
    transport: str = "stdio"                 # "stdio" | "http"
```

修改 `load_mcp_config` 的循环体（替换原「缺 command 跳过」逻辑）：

```python
    result: dict[str, MCPServerConfig] = {}
    for name, entry in servers_raw.items():
        if not isinstance(entry, dict):
            logger.warning(f"MCP server '{name}' 配置非法，已跳过")
            continue
        if "url" in entry:
            # 有 url → Streamable HTTP（url 优先于 command）
            result[name] = MCPServerConfig(
                name=name, url=entry["url"], transport="http"
            )
        elif "command" in entry:
            # 有 command → stdio（现有行为不变）
            result[name] = MCPServerConfig(
                name=name,
                command=entry["command"],
                args=list(entry.get("args", [])),
                env=dict(entry.get("env", {})),
            )
        else:
            logger.warning(f"MCP server '{name}' 缺少 command 或 url，已跳过")
    return result
```

同时更新 `load_mcp_config` docstring 中「单条缺 command → 跳过该项」为「单条既无 command 也无 url → 跳过该项」。

- [ ] **Step 4: 运行测试确认通过（含全部旧用例）**

Run: `uv run pytest tests/test_mcp_client.py -v`
Expected: 全部 PASS（旧 stdio 配置用例不改一行仍绿）

- [ ] **Step 5: Commit**

```bash
git add my_small_agent/mcp_client.py tests/test_mcp_client.py
git commit -m "feat(mcp): mcp.json 支持 url 字段声明 HTTP 传输"
```

---

### Task 2: 连接层——抽取 `_connect(cfg)` 并接入 `streamablehttp_client`

**Files:**
- Modify: `my_small_agent/mcp_client.py`（imports 区、`_call_remote_tool` 约 L97-106、`_discover_tools` 约 L136-147）
- Test: `tests/test_mcp_client.py`

**Interfaces:**
- Consumes: Task 1 的 `cfg.transport` / `cfg.url`
- Produces: `_connect(cfg: MCPServerConfig)` —— `@asynccontextmanager`，yield 一个已 `initialize()` 的 `ClientSession`。`_call_remote_tool` / `_discover_tools` 签名不变。

- [ ] **Step 1: 写失败测试**

在 `tests/test_mcp_client.py` 的 `_patch_connection` 之后追加 HTTP 版 mock 基建，并在文件末尾追加 3 个用例：

```python
class _FakeHttpCtx:
    """假 streamablehttp_client：async with 返回三元组 (read, write, get_session_id)。"""
    async def __aenter__(self):
        return ("read", "write", lambda: "session-id")

    async def __aexit__(self, *exc):
        return False


def _patch_http_connection(monkeypatch, *, tools=None, call_result=None, call_error=None):
    """monkeypatch streamablehttp_client 与 ClientSession，返回捕获到的 url/session。"""
    captured = {}

    def fake_http_client(url):
        captured["url"] = url
        return _FakeHttpCtx()

    def fake_client_session(read, write):
        session = _FakeSession(
            read, write, tools=tools,
            call_result=call_result, call_error=call_error,
        )
        captured["session"] = session
        return session

    monkeypatch.setattr(mcp_client, "streamablehttp_client", fake_http_client)
    monkeypatch.setattr(mcp_client, "ClientSession", fake_client_session)
    return captured
```

```python
@pytest.mark.asyncio
async def test_http_tool_execute_calls_remote(monkeypatch):
    result = SimpleNamespace(content=[SimpleNamespace(text="ok")])
    captured = _patch_http_connection(monkeypatch, call_result=result)
    cfg = MCPServerConfig(
        name="remote", url="http://localhost:8000/mcp", transport="http"
    )
    tool = MCPTool("mcp_remote_ping", "ping", "d", {}, cfg)

    out = await tool.execute(x=1)

    assert out == "ok"
    assert captured["url"] == "http://localhost:8000/mcp"
    assert captured["session"].calls == [("ping", {"x": 1})]


@pytest.mark.asyncio
async def test_register_discovers_http_tools(monkeypatch, tmp_path):
    cfg_file = tmp_path / "mcp.json"
    cfg_file.write_text(json.dumps({
        "mcpServers": {"remote": {"url": "http://localhost:8000/mcp"}}
    }), encoding="utf-8")
    _patch_http_connection(monkeypatch, tools=[_fake_tool("ping")])
    registry = ToolRegistry()

    await register_mcp_tools(registry, str(cfg_file))

    assert registry.get("mcp_remote_ping") is not None


@pytest.mark.asyncio
async def test_register_degrades_when_http_server_fails(monkeypatch, tmp_path):
    cfg_file = tmp_path / "mcp.json"
    cfg_file.write_text(json.dumps({
        "mcpServers": {"remote": {"url": "http://localhost:8000/mcp"}}
    }), encoding="utf-8")

    def fake_http_client(url):
        raise ConnectionError("unreachable")

    monkeypatch.setattr(mcp_client, "streamablehttp_client", fake_http_client)
    registry = ToolRegistry()

    # 不抛异常
    await register_mcp_tools(registry, str(cfg_file))

    assert registry.list_all() == []
```

- [ ] **Step 2: 运行测试确认失败**

Run: `uv run pytest tests/test_mcp_client.py -k "http" -v`
Expected: 新增 3 个用例 FAIL（`AttributeError: module ... has no attribute 'streamablehttp_client'`）

- [ ] **Step 3: 最小实现**

在 `my_small_agent/mcp_client.py` 的 imports 区追加：

```python
from contextlib import asynccontextmanager

from mcp.client.streamable_http import streamablehttp_client
```

在 `_stringify_result` 之后新增 `_connect`，并用它重写 `_call_remote_tool` 与 `_discover_tools`（删除两处原有的重复建连代码）：

```python
@asynccontextmanager
async def _connect(cfg: MCPServerConfig):
    """按传输类型建连并 initialize，yield 可用的 ClientSession（连→用→断）。"""
    if cfg.transport == "http":
        # Streamable HTTP：注意 client 返回三元组 (read, write, get_session_id)
        async with streamablehttp_client(cfg.url) as (read, write, _):
            async with ClientSession(read, write) as session:
                await session.initialize()
                yield session
    else:
        params = StdioServerParameters(
            command=cfg.command, args=cfg.args, env=cfg.env or None
        )
        async with stdio_client(params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                yield session


async def _call_remote_tool(cfg: MCPServerConfig, tool_name: str, arguments: dict) -> str:
    """即时连接远程 server，调用 tool，返回文本结果（连→调→断，自包含）。"""
    async with _connect(cfg) as session:
        result = await session.call_tool(tool_name, arguments)
        return _stringify_result(result)


async def _discover_tools(cfg: MCPServerConfig, timeout: float = 30.0) -> list:
    """一次性连接 server 拉取 tool 列表（带超时），连→列→断。"""
    async def _list():
        async with _connect(cfg) as session:
            return (await session.list_tools()).tools

    return await asyncio.wait_for(_list(), timeout=timeout)
```

说明：`_connect` 引用的是模块级名字 `stdio_client` / `ClientSession` / `streamablehttp_client`，因此现有测试对 `mcp_client.stdio_client` 的 monkeypatch 依旧生效，旧用例无需改动。

- [ ] **Step 4: 运行测试确认通过（含全部旧用例）**

Run: `uv run pytest tests/test_mcp_client.py -v`
Expected: 全部 PASS

- [ ] **Step 5: Commit**

```bash
git add my_small_agent/mcp_client.py tests/test_mcp_client.py
git commit -m "feat(mcp): 支持 Streamable HTTP 传输，抽取统一连接入口 _connect"
```

---

### Task 3: 配套更新——示例配置、模块 docstring、全量回归

**Files:**
- Modify: `mcp.json.example`
- Modify: `my_small_agent/mcp_client.py`（模块 docstring L1-8）

**Interfaces:**
- Consumes: Task 1/2 的最终行为（无代码接口，纯文档与回归验证）

- [ ] **Step 1: 更新 `mcp.json.example`**

整文件替换为：

```json
{
  "mcpServers": {
    "everything": {
      "command": "npx",
      "args": ["-y", "@modelcontextprotocol/server-everything"]
    },
    "remote-http": {
      "url": "http://localhost:8000/mcp"
    }
  }
}
```

- [ ] **Step 2: 更新模块 docstring**

把 `my_small_agent/mcp_client.py` 开头 docstring 中的：

```python
"""
MCP client 模块 - 连接外部 MCP server，把其 tools 包装为本地 Tool。

设计：
  - 仅 stdio 传输
  - 每次调用即时连接（连→调→断，自包含），不维持持久连接
  - 全程降级不阻断：MCP 不可用时 agent 正常运行
"""
```

改为：

```python
"""
MCP client 模块 - 连接外部 MCP server，把其 tools 包装为本地 Tool。

设计：
  - 支持 stdio 与 Streamable HTTP 两种传输（mcp.json 条目有 url 即 HTTP）
  - 每次调用即时连接（连→调→断，自包含），不维持持久连接
  - 全程降级不阻断：MCP 不可用时 agent 正常运行
"""
```

- [ ] **Step 3: 全量测试回归**

Run: `uv run pytest`
Expected: 全部 PASS，无任何回归

- [ ] **Step 4: Commit**

```bash
git add mcp.json.example my_small_agent/mcp_client.py
git commit -m "docs(mcp): 示例配置与模块说明补充 HTTP 传输"
```

---

## 验收标准（对照设计方案）

1. `uv run pytest tests/test_mcp_client.py` 全绿，新增 6 个用例（3 配置 + 3 连接）
2. `uv run pytest` 全量无回归
3. 用户把 DataBridge 起成 HTTP server 后，`mcp.json` 条目换成 `{"url": "http://<host>:<port>/mcp"}` 即可直接使用
