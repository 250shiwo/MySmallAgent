# MCP Client 接入设计

## 概述

为 MySmallAgent 新增 **MCP（Model Context Protocol）client** 能力：读取 `mcp.json` 配置，连接外部 MCP server，把 server 暴露的 tools 包装成本地 `Tool` 注册进 `ToolRegistry`，供 LLM 在 CLI 和 QQ 两个前端调用。

这是"agent 侧的通用地基"，为后续自研 MCP server（如 MySQL 同步工具）提供接入点。本次迭代只做 client，用现成的公开 stdio server 验证链路。

### 现有基础

- `Tool` 抽象基类（`name` / `description` / `parameters` / `danger_level` / `category` + async `execute`）
- `ToolRegistry`：`register()` / `get()` / `dispatch()` / `get_openai_tools(readonly_only)`
- `create_default_registry(settings, memory_manager, sessions_dir)` 工厂
- 两个前端组装链：CLI（`__main__.py` `main()`，async）与 QQ（`qq_bot.py` `main()`，sync + `client.run()` 内部自建事件循环）
- 危险工具确认链：`danger_level="dangerous"` 触发 `confirm_callback`；CLI 弹确认，QQ 恒 True 自动批准
- Plan 模式：`get_openai_tools(readonly_only=True)` 仅暴露 `category="read_only"` 工具

### 新增能力

1. `mcp.json` 配置解析
2. 启动时连接 MCP server 并发现其 tools
3. 把远程 tool 包装为 `MCPTool` 注册进 `ToolRegistry`
4. 运行时通过"每次调用即时连接"执行远程 tool
5. 全程降级不阻断：MCP 不可用时 agent 正常运行

## 设计决策

| 决策点 | 选择 | 理由 |
|--------|------|------|
| 传输方式 | 仅 stdio | 最简单，可白嫖大量现成 server 验证；HTTP 留到 Docker 阶段 |
| 连接模型 | **每次调用即时连接**（ephemeral per-call） | 自包含连→调→断，CLI/QQ 两个事件循环行为一致，绕开 MCP SDK 跨 task/跨循环的 "cancel scope" 坑；代价是每次调用拉起子进程的延迟，对偶发调用场景可接受 |
| server 清单 | `mcp.json`（对齐 Claude Desktop 格式，`.gitignore`） | 凭据不进 git；可直接粘贴他人配置；加 server 不改代码 |
| 工具安全级别 | 全部 `danger_level="dangerous"` / `category="write"` | agent 无法预判远程 tool 是否危险；CLI 弹确认、Plan 模式自动排除 |
| 工具命名 | `mcp_{server}_{tool}`，非法字符转 `_`，截断 64 | server 前缀防冲突，满足 OpenAI 命名规则 |
| 模块布局 | 单个扁平模块 `mcp_client.py` | 匹配 `memory.py`/`session.py` 风格；避免 `mcp/` 包名与第三方 `mcp` SDK 冲突 |
| 失败处理 | 降级不阻断 | 个人工具，单个 server 失败不应拖垮 agent 启动 |

## 模块结构

### 新增文件

```
my_small_agent/
├── mcp_client.py        # MCPServerConfig + load_mcp_config + MCPTool + register_mcp_tools
mcp.json.example         # 配置样例（项目根）
tests/
├── test_mcp_client.py   # 全 mock，不拉真子进程
```

### 修改文件

```
my_small_agent/
├── __main__.py          # CLI: create_default_registry 后 await register_mcp_tools
├── qq_bot.py            # QQ: client.run() 前 asyncio.run(register_mcp_tools)
pyproject.toml           # 新增依赖 mcp
.gitignore               # 新增 mcp.json
```

### 新增依赖

```
mcp        # 官方 Model Context Protocol Python SDK
```

## 配置文件

### `mcp.json`（项目根，`.gitignore` 掉）

对齐 Claude Desktop 生态格式：

```json
{
  "mcpServers": {
    "everything": {
      "command": "npx",
      "args": ["-y", "@modelcontextprotocol/server-everything"]
    },
    "mysql-sync": {
      "command": "python",
      "args": ["path/to/mcp_server.py"],
      "env": { "MYSQL_PWD": "..." }
    }
  }
}
```

- `command`（必填）、`args`（可选，默认 `[]`）、`env`（可选，默认 `{}`）
- 文件不存在 = 没有 MCP server，agent 正常启动（向后兼容）
- 附带 `mcp.json.example`；`.gitignore` 加入 `mcp.json`

## 数据结构

### `mcp_client.py`

```python
from dataclasses import dataclass, field

@dataclass
class MCPServerConfig:
    name: str                              # server 标识（mcp.json 的 key）
    command: str                           # 启动命令，如 "npx" / "python"
    args: list[str] = field(default_factory=list)
    env: dict[str, str] = field(default_factory=dict)
```

### `load_mcp_config(path) -> dict[str, MCPServerConfig]`

- 读取 `path`（默认 `"mcp.json"`）
- 文件不存在 → 返回 `{}`（不报错）
- JSON 解析失败或结构非法 → 记 warning，返回 `{}`
- 遍历 `mcpServers`，每项缺 `command` → 跳过该项并记 warning
- 返回 `{name: MCPServerConfig}`

## MCPTool

包装单个远程工具。持有所属 server 的启动参数与远程 tool 名，`execute()` 时即时连接。

```python
import json
from my_small_agent.tools.base import Tool

class MCPTool(Tool):
    danger_level = "dangerous"
    category = "write"

    def __init__(self, registered_name, remote_tool_name, description, parameters, server_config):
        self.name = registered_name          # mcp_{server}_{tool}
        self._remote_tool_name = remote_tool_name
        self.description = description
        self.parameters = parameters         # 远程 tool 的 inputSchema
        self._server_config = server_config

    async def execute(self, **kwargs) -> str:
        """即时连接远程 server，调用 tool，返回文本结果。"""
        try:
            return await _call_remote_tool(
                self._server_config, self._remote_tool_name, kwargs
            )
        except Exception as e:
            return json.dumps({"error": f"MCP tool '{self.name}' failed: {e}"})
```

### `_call_remote_tool(server_config, tool_name, arguments) -> str`

自包含的一次性连接（连→调→断在同一 task 内完成）：

```python
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

async def _call_remote_tool(cfg, tool_name, arguments) -> str:
    params = StdioServerParameters(command=cfg.command, args=cfg.args, env=cfg.env or None)
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            result = await session.call_tool(tool_name, arguments)
            return _stringify_result(result)
```

`_stringify_result`：把 MCP `CallToolResult` 的 content 块（TextContent 等）拼接为字符串；无文本内容时返回其 JSON 表示。

## 启动发现与注册

### `async def register_mcp_tools(registry, config_path="mcp.json") -> None`

```python
async def register_mcp_tools(registry, config_path="mcp.json"):
    servers = load_mcp_config(config_path)
    for name, cfg in servers.items():
        try:
            tools = await _discover_tools(cfg)          # 连接 → list_tools → 断开
        except Exception as e:
            logger.warning(f"MCP server '{name}' 连接失败，已跳过：{e}")
            continue
        for t in tools:
            registered = _make_tool_name(name, t.name)   # mcp_{server}_{tool} + 净化
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
```

### `_discover_tools(cfg)`

带超时的一次性连接，返回远程 tool 列表：

```python
async def _discover_tools(cfg, timeout=30.0):
    async def _connect():
        params = StdioServerParameters(command=cfg.command, args=cfg.args, env=cfg.env or None)
        async with stdio_client(params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                return (await session.list_tools()).tools
    return await asyncio.wait_for(_connect(), timeout=timeout)
```

### `_make_tool_name(server, tool)`

- 拼 `mcp_{server}_{tool}`
- 非 `[a-zA-Z0-9_-]` 字符替换为 `_`
- 超 64 字符从末尾截断

## 前端接入

### CLI（`__main__.py` `main()`，async）

在 `create_default_registry(...)` 之后、创建 `Agent` 之前：

```python
registry = create_default_registry(settings, memory_manager=..., sessions_dir=...)
# ... skill 工具注册 ...
await register_mcp_tools(registry, "mcp.json")     # 新增
```

### QQ（`qq_bot.py` `main()`，sync）

在 `client.run()` **之前**（自包含 `asyncio.run`，连→列→断，无跨循环问题）：

```python
registry = create_default_registry(settings, memory_manager=..., sessions_dir=...)
# ... skill 工具注册 ...
asyncio.run(register_mcp_tools(registry, "mcp.json"))   # 新增
# ... 组装 agent ...
client.run(appid=..., secret=...)
```

注册进 registry 的是 `MCPTool` 包装对象（只存启动参数，不持有活连接），因此发现阶段用独立 `asyncio.run`、调用阶段在 botpy 循环里各自即时连接，互不干扰。

## 数据流

```
启动:
  load_mcp_config("mcp.json")
    → 逐 server: 即时连接 → list_tools → 断开
    → 每个远程 tool 包装为 MCPTool（mcp_{server}_{tool}）注册进 ToolRegistry
    → 某 server 失败 → 记 warning、跳过、其余照常

运行:
  LLM 决定调用 mcp_xxx
    → agent 检查 danger_level="dangerous" → 走既有 confirm_callback
       ├─ CLI: 弹确认面板
       └─ QQ: 自动批准
    → MCPTool.execute(**kwargs)
       → 即时连接远程 server → call_tool → 拼接文本结果 → 断开
    → 结果作为 tool message 回传 LLM
```

## 错误处理（降级不阻断）

| 情况 | 处理 |
|------|------|
| `mcp.json` 不存在 | 返回 `{}`，按"无 MCP"启动 |
| `mcp.json` 格式错/结构非法 | 记 warning，返回 `{}` |
| 单条 server 缺 `command` | 跳过该项，记 warning |
| server 连接失败/崩溃/超时（30s） | 记 warning、跳过该 server、其余照常，不阻断启动 |
| 运行时 `call_tool` 抛错 | 捕获后返回 JSON 错误串给 LLM（与 `dispatch` 风格一致） |

## 测试策略

### 新增 `tests/test_mcp_client.py`（全程 mock，不拉真子进程）

| 测试类别 | 场景 |
|---------|------|
| 配置解析 | 正常多 server / 文件缺失返回 `{}` / 坏 JSON 返回 `{}` / 缺 command 跳过 / args·env 默认值 |
| 工具命名 | 前缀拼接 / 非法字符净化 / 超 64 截断 / 冲突跳过 |
| 发现注册 | mock 连接返回假 tool 清单 → 断言注册进 registry、名称与 `danger_level="dangerous"` 正确 |
| execute | monkeypatch `stdio_client`/`ClientSession` 为假会话 → 断言 `call_tool` 被调、结果被拼接为字符串 |
| 结果拼接 | 多 TextContent 拼接 / 空内容回退 JSON |
| 降级 | 某 server `_discover_tools` 抛错 → 被跳过、其余仍注册、`register_mcp_tools` 不抛异常 |
| execute 异常 | `call_tool` 抛错 → 返回含 `error` 的 JSON 串，不抛异常 |

### 测试要点

- monkeypatch `mcp_client.stdio_client` 与 `mcp_client.ClientSession` 为异步上下文管理器假实现，返回预设 tool 清单/调用结果
- 不新增依赖真实 MCP server 或真实子进程的集成测试（Windows 下易 flaky）
- 复用现有 mock 风格（`AsyncMock` / `SimpleNamespace`）

## 未来扩展 / 非目标

**本次非目标（明确不做）：**

- HTTP/SSE 传输
- 持久连接池 / 连接复用
- MCP prompts、resources（只做 tools）
- 可插拔配置的热加载（重启生效即可）
- 自研 MySQL 同步 server（那是下一次迭代）

**演进路标（对应用户三步愿景）：**

- **迭代一（本 spec）**：stdio client，本地实验，用现成公开 server 验证
- **迭代二**：自研 MySQL 同步 MCP server（GUI + stdio MCP 两副面孔，共用同步引擎），本地起服务接入
- **迭代三（Docker）**：全 docker 化时给 client **新增 HTTP/SSE 传输**——每个 server 独立容器暴露端口，agent 通过网络连接。届时 `_call_remote_tool` / `_discover_tools` 按传输类型分派，stdio 逻辑不变，是干净的扩展点。

> ⚠️ 已知取舍：per-call 即时连接对"跨调用有状态"的 server（如浏览器会话）会丢状态。当前场景（MySQL 同步、各类无状态工具）不受影响；若将来需要有状态 server，再引入持久连接池。
