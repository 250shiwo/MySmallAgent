# 流式输出、思维链模式与联网搜索 — 设计规格

## 概述

在 MySmallAgent v0.1（基础文件操作 + Shell 执行）基础上，新增三大能力：
1. **流式输出（Streaming）** — 实时逐字显示 LLM 回复
2. **思维链模式（Thinking）** — DeepSeek Reasoning 能力集成
3. **联网搜索工具** — DuckDuckGo 搜索 + 当前时间查询

同时配套：CLI 新增命令、配置项扩展、系统提示词升级。

---

## 1. 配置层（config.py）

### 新增字段

| 字段 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `enable_streaming` | `bool` | `True` | 流式输出开关 |
| `enable_thinking` | `bool` | `True` | 思维链模式开关 |
| `timezone` | `str` | `"Asia/Shanghai"` | 时区，用于 current_time 工具 |

### .env.example 追加

```
ENABLE_STREAMING=true
ENABLE_THINKING=true
TIMEZONE=Asia/Shanghai
```

---

## 2. LLM 层（llm.py）

### 接口变更

`LLMClient` 新增 `chat_stream()` 方法，原有 `chat()` 增加 `thinking_enabled` 参数：

```python
async def chat(
    self, messages, tools=None, thinking_enabled=False
) -> ChatCompletion:
    kwargs = {"model": self.model, "messages": messages}
    if tools:
        kwargs["tools"] = tools
    if thinking_enabled:
        kwargs["thinking"] = {"type": "enabled"}
    return await self.client.chat.completions.create(**kwargs)

async def chat_stream(
    self, messages, tools=None, thinking_enabled=False
) -> AsyncStream[ChatCompletionChunk]:
    kwargs = {"model": self.model, "messages": messages, "stream": True}
    if tools:
        kwargs["tools"] = tools
    if thinking_enabled:
        kwargs["thinking"] = {"type": "enabled"}
    return await self.client.chat.completions.create(**kwargs)
```

### 设计决策

- `thinking_enabled` 作为方法参数（而非从 settings 读取），Agent 层可动态控制
- DeepSeek Thinking 通过 `{"thinking": {"type": "enabled"}}` 参数启用
- `chat_stream()` 返回 OpenAI SDK 的 `AsyncStream[ChatCompletionChunk]`

---

## 3. Agent 层（agent.py）

### 运行时状态

Agent 新增两个可动态切换的属性（初始值从 Settings 读取，CLI 命令可切换）：

```python
self.streaming_enabled: bool  # 从 settings.enable_streaming 初始化
self.thinking_enabled: bool   # 从 settings.enable_thinking 初始化
```

### 新增方法：`run_turn_stream()`

流式版本的对话循环，使用 async generator 模式：

```python
async def run_turn_stream(self, user_input, confirm_callback):
    """yield (event_type, content) 元组，event_type 为 'thinking' 或 'content'"""
```

**流程：**
1. 追加用户消息到历史
2. 调用 `llm.chat_stream()` 获取异步流
3. 遍历 chunk，根据 delta 类型 yield 不同事件：
   - `delta.reasoning_content` → yield `("thinking", text)`
   - `delta.content` → yield `("content", text)`
   - `delta.tool_calls` → 累积拼接工具调用数据
4. 流结束后：
   - 若无工具调用 → 保存到历史，return
   - 若有工具调用 → 执行工具（阻塞），追加结果到历史，继续下一轮循环

**关键约束：**
- 流式仅用于最终文本回复，工具调用轮次等完整响应后再执行工具
- 工具执行期间不产生流式输出（CLI 可显示 spinner）

### 新增方法：`strip_thinking_from_history()`

```python
def strip_thinking_from_history(self):
    """从历史中剔除 reasoning_content 字段，节省 token 开销。
    在用户关闭 thinking 模式时调用。"""
    for msg in self.messages:
        if msg.get("role") == "assistant" and "reasoning_content" in msg:
            del msg["reasoning_content"]
```

### 思维链历史管理策略

- **thinking 开启时**：assistant 消息保存为 `{"role": "assistant", "content": "...", "reasoning_content": "..."}`，多轮工具调用时 LLM 能延续推理
- **thinking 关闭时**：调用 `strip_thinking_from_history()` 清除已有推理内容，后续消息不含此字段
- **清理时机**：仅在用户通过 `/think` 命令关闭时执行一次（惰性清理）

### 原有方法调整

`run_turn()` 保留，但返回类型从 `str` 变更为 `AgentResponse` 数据类：

```python
@dataclass
class AgentResponse:
    content: str              # 最终文本回复
    thinking: str = ""        # 思维链内容（thinking 关闭时为空）
```

调用 LLM 时透传 thinking 参数：

```python
response = await self.llm.chat(
    messages=self.messages,
    tools=tools if tools else None,
    thinking_enabled=self.thinking_enabled,
)
# 从 response 中提取 reasoning_content（如有）
thinking_content = getattr(message, 'reasoning_content', '') or ''
return AgentResponse(content=content, thinking=thinking_content)
```

CLI 非流式模式据此决定是否展示 thinking 面板（dim 样式一次性展示）。

---

## 4. 工具层（tools/）

### 新增 `tools/web_search.py`

```python
class WebSearchTool(Tool):
    name = "web_search"
    description = "Search the web using DuckDuckGo and return top results."
    parameters = {
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "The search query."},
            "max_results": {"type": "integer", "description": "Max results (default: 5)."},
        },
        "required": ["query"],
    }
    danger_level = "safe"
```

- 使用 `duckduckgo-search` 库的 `AsyncDDGS.atext()` 方法
- 返回格式：编号 + 标题 + URL + 摘要
- 无需 API Key，免费使用

### 新增 `tools/current_time.py`

```python
class CurrentTimeTool(Tool):
    name = "current_time"
    description = "Get current date and time in the configured timezone."
    parameters = {"type": "object", "properties": {}}
    danger_level = "safe"
```

- 使用 Python 标准库 `zoneinfo.ZoneInfo`，无额外依赖
- 构造时接收 `timezone` 参数（从 Settings 传入）
- 输出格式：`2026-06-25 14:30:00 CST (Wednesday)`

### 工具注册变更

`create_default_registry()` 签名变更为接受 `settings` 参数：

```python
def create_default_registry(settings: Settings) -> ToolRegistry:
    registry = ToolRegistry()
    registry.register(ReadFileTool())
    registry.register(WriteFileTool())
    registry.register(ListDirectoryTool())
    registry.register(ExecuteShellTool())
    registry.register(WebSearchTool())
    registry.register(CurrentTimeTool(timezone=settings.timezone))
    return registry
```

### 新增依赖

`pyproject.toml` 添加：
```
"duckduckgo-search>=7.0",
```

---

## 5. CLI 层（cli.py）

### 新增命令

| 命令 | 功能 | 行为 |
|------|------|------|
| `/stream` | 切换流式输出 | toggle `agent.streaming_enabled` |
| `/think` | 切换思维链 | toggle `agent.thinking_enabled`，关闭时调用 `strip_thinking_from_history()` |
| `/status` | 显示当前状态 | 面板展示：模型名、流式开关、思维链开关 |

### 流式输出渲染

`_run_agent_turn()` 根据 `streaming_enabled` 分支：

**流式模式（`_run_agent_turn_stream()`）：**
- 遍历 `agent.run_turn_stream()` yield 的事件
- `("thinking", text)` → 用 `[dim]` 淡色 + 💭 前缀逐字打印
- `("content", text)` → 正常颜色逐字打印
- 不使用 Markdown 渲染（逐字流式无法整体渲染）

**非流式模式（保持原样）：**
- 显示 `Status("Thinking...")` spinner
- 等待完整响应后用 `Markdown()` 渲染

### 欢迎面板和帮助更新

welcome 和 `/help` 命令列表中添加新命令的说明。

---

## 6. 系统提示词（agent.py SYSTEM_PROMPT）

从当前的英文简短描述升级为：

```
你是一个运行在命令行终端中的通用任务助手（CLI Agent）。

你的能力：
- 文件读写和目录浏览
- 执行 Shell 命令
- 联网搜索获取实时信息
- 查询当前时间

工作原则：
- 高效完成用户任务，避免冗余解释
- 输出简洁清晰，适合终端阅读
- 避免使用复杂 Markdown（如表格、嵌套列表），终端渲染有限
- 代码块和简单列表可以使用
- 优先用中文回复，除非用户使用英文提问
```

**变更要点：**
- 从"文件操作助手"升级为"通用任务助手"
- 明确终端环境限制（避免复杂 Markdown）
- 列举完整能力清单
- 强调效率与简洁

---

## 7. 入口点变更（__main__.py）

`create_default_registry()` 调用需传入 settings：

```python
registry = create_default_registry(settings)
```

---

## 8. 依赖变更汇总

### pyproject.toml

```toml
dependencies = [
    "openai>=1.0",
    "pydantic-settings>=2.0",
    "prompt-toolkit>=3.0",
    "rich>=13.0",
    "duckduckgo-search>=7.0",  # 新增
]
```

---

## 9. 文件变更清单

| 文件 | 操作 | 说明 |
|------|------|------|
| `my_small_agent/config.py` | 修改 | 新增 3 个配置字段 |
| `my_small_agent/llm.py` | 修改 | 新增 `chat_stream()`，`chat()` 增加 thinking 参数 |
| `my_small_agent/agent.py` | 修改 | 新增 `run_turn_stream()`、`strip_thinking_from_history()`、运行时状态 |
| `my_small_agent/tools/web_search.py` | 新增 | DuckDuckGo 搜索工具 |
| `my_small_agent/tools/current_time.py` | 新增 | 当前时间工具 |
| `my_small_agent/tools/__init__.py` | 修改 | 注册新工具，签名变更 |
| `my_small_agent/cli.py` | 修改 | 新增命令、流式渲染逻辑 |
| `my_small_agent/__main__.py` | 修改 | 传 settings 给 registry |
| `.env.example` | 修改 | 新增配置项模板 |
| `pyproject.toml` | 修改 | 新增 duckduckgo-search 依赖 |
