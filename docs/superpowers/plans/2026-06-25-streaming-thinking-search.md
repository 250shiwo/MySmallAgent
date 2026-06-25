# 流式输出、思维链与联网搜索 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在现有 CLI Agent 基础上新增流式输出、DeepSeek 思维链模式和联网搜索能力。

**Architecture:** 在已有分层架构（Config → LLM → Tools → Agent → CLI）上逐层增量扩展。LLM 层新增流式接口，Agent 层新增 async generator 模式的流式对话循环，工具层新增 web_search 和 current_time，CLI 层新增命令和流式渲染。

**Tech Stack:** Python 3.11+, openai SDK (AsyncStream), duckduckgo-search (AsyncDDGS), zoneinfo (stdlib), rich (Live/print), prompt-toolkit

## Global Constraints

- Python >= 3.11
- 所有新增依赖必须在 pyproject.toml 中声明
- 异步优先：所有 IO 操作使用 async/await
- 工具安全级别：web_search 和 current_time 均为 "safe"
- 中文注释风格保持一致（参照现有代码的模块级和方法级注释格式）
- 测试使用 pytest + pytest-asyncio，asyncio_mode = "auto"
- 运行测试命令：`uv run pytest tests/ -v`

---

### Task 1: 配置层扩展 + 依赖更新

**Files:**
- Modify: `my_small_agent/config.py`
- Modify: `.env.example`
- Modify: `pyproject.toml`
- Modify: `tests/test_config.py`

**Interfaces:**
- Consumes: 无（底层模块）
- Produces: `Settings.enable_streaming: bool`, `Settings.enable_thinking: bool`, `Settings.timezone: str`

- [ ] **Step 1: 写失败测试 — 验证新配置字段**

在 `tests/test_config.py` 追加：

```python
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
```

- [ ] **Step 2: 运行测试确认失败**

```bash
uv run pytest tests/test_config.py::test_settings_new_fields_defaults tests/test_config.py::test_settings_new_fields_from_env -v
```

Expected: FAIL — `Settings` 没有 `enable_streaming` 等属性

- [ ] **Step 3: 实现配置字段**

修改 `my_small_agent/config.py`，在 `Settings` 类中新增字段：

```python
class Settings(BaseSettings):
    """
    Agent 的配置项集合。

    配置项说明：
      - openai_api_key:     API 密钥，必填
      - openai_base_url:    API 地址，默认 OpenAI 官方
      - openai_model:       模型名称，默认 gpt-4o
      - max_iterations:     单次对话最大工具调用次数
      - enable_streaming:   流式输出开关
      - enable_thinking:    思维链模式开关
      - timezone:           时区（用于 current_time 工具）
    """

    openai_api_key: str
    openai_base_url: str = "https://api.openai.com/v1"
    openai_model: str = "gpt-4o"
    max_iterations: int = 10
    enable_streaming: bool = True
    enable_thinking: bool = True
    timezone: str = "Asia/Shanghai"

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
    )
```

- [ ] **Step 4: 更新 .env.example**

追加到 `.env.example` 末尾：

```
ENABLE_STREAMING=true
ENABLE_THINKING=true
TIMEZONE=Asia/Shanghai
```

- [ ] **Step 5: 更新 pyproject.toml 依赖**

修改 `pyproject.toml` 的 dependencies：

```toml
dependencies = [
    "openai>=1.0",
    "pydantic-settings>=2.0",
    "prompt-toolkit>=3.0",
    "rich>=13.0",
    "duckduckgo-search>=7.0",
]
```

- [ ] **Step 6: 安装新依赖**

```bash
uv sync
```

- [ ] **Step 7: 运行测试确认通过**

```bash
uv run pytest tests/test_config.py -v
```

Expected: ALL PASS

- [ ] **Step 8: Commit**

```bash
git add my_small_agent/config.py .env.example pyproject.toml tests/test_config.py uv.lock
git commit -m "feat(config): add streaming, thinking, timezone settings"
```

---

### Task 2: LLM 层 — 流式接口 + Thinking 参数

**Files:**
- Modify: `my_small_agent/llm.py`
- Modify: `tests/test_llm.py`

**Interfaces:**
- Consumes: `Settings`（已有）
- Produces: `LLMClient.chat(messages, tools?, thinking_enabled?) -> ChatCompletion`, `LLMClient.chat_stream(messages, tools?, thinking_enabled?) -> AsyncStream`

- [ ] **Step 1: 写失败测试 — chat() 支持 thinking 参数**

在 `tests/test_llm.py` 追加：

```python
from unittest.mock import AsyncMock, patch, MagicMock


@pytest.fixture
def mock_settings(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    from my_small_agent.config import Settings
    return Settings(_env_file=None)


@pytest.mark.asyncio
async def test_chat_with_thinking_enabled(mock_settings):
    """thinking_enabled=True 时应传递 thinking 参数给 API。"""
    from my_small_agent.llm import LLMClient

    client = LLMClient(mock_settings)
    mock_response = MagicMock()
    client.client.chat.completions.create = AsyncMock(return_value=mock_response)

    await client.chat(
        messages=[{"role": "user", "content": "hello"}],
        thinking_enabled=True,
    )

    call_kwargs = client.client.chat.completions.create.call_args[1]
    assert call_kwargs["thinking"] == {"type": "enabled"}


@pytest.mark.asyncio
async def test_chat_without_thinking(mock_settings):
    """thinking_enabled=False 时不应传递 thinking 参数。"""
    from my_small_agent.llm import LLMClient

    client = LLMClient(mock_settings)
    mock_response = MagicMock()
    client.client.chat.completions.create = AsyncMock(return_value=mock_response)

    await client.chat(
        messages=[{"role": "user", "content": "hello"}],
        thinking_enabled=False,
    )

    call_kwargs = client.client.chat.completions.create.call_args[1]
    assert "thinking" not in call_kwargs


@pytest.mark.asyncio
async def test_chat_stream_returns_stream(mock_settings):
    """chat_stream() 应传递 stream=True 给 API。"""
    from my_small_agent.llm import LLMClient

    client = LLMClient(mock_settings)
    mock_stream = AsyncMock()
    client.client.chat.completions.create = AsyncMock(return_value=mock_stream)

    result = await client.chat_stream(
        messages=[{"role": "user", "content": "hello"}],
        thinking_enabled=True,
    )

    call_kwargs = client.client.chat.completions.create.call_args[1]
    assert call_kwargs["stream"] is True
    assert call_kwargs["thinking"] == {"type": "enabled"}
    assert result is mock_stream
```

- [ ] **Step 2: 运行测试确认失败**

```bash
uv run pytest tests/test_llm.py::test_chat_with_thinking_enabled tests/test_llm.py::test_chat_without_thinking tests/test_llm.py::test_chat_stream_returns_stream -v
```

Expected: FAIL — `chat()` 不接受 `thinking_enabled` 参数，`chat_stream` 不存在

- [ ] **Step 3: 实现 LLM 层变更**

重写 `my_small_agent/llm.py`：

```python
"""
LLM 客户端模块 - 封装 OpenAI 异步 API 调用。

工作原理：
  - 基于 openai 库的 AsyncOpenAI 客户端
  - 提供 chat() 方法，发送消息列表，返回模型响应
  - 提供 chat_stream() 方法，返回流式响应的异步迭代器
  - 支持可选 thinking 参数启用 DeepSeek 思维链
  - 兼容所有 OpenAI API 格式的服务（DeepSeek、本地模型等）
"""

from openai import AsyncOpenAI
from openai.types.chat import ChatCompletion

from my_small_agent.config import Settings


class LLMClient:
    """
    OpenAI 异步聊天客户端的封装。

    职责：
      - 管理与 OpenAI API 的连接
      - 提供统一的 chat() 和 chat_stream() 接口给 Agent 使用
      - 支持 thinking 参数透传（DeepSeek Reasoning）
    """

    def __init__(self, settings: Settings) -> None:
        # 创建异步 OpenAI 客户端
        self.client = AsyncOpenAI(
            api_key=settings.openai_api_key,
            base_url=settings.openai_base_url,
        )
        self.model = settings.openai_model

    def _build_kwargs(
        self,
        messages: list[dict],
        tools: list[dict] | None = None,
        thinking_enabled: bool = False,
        stream: bool = False,
    ) -> dict:
        """构造 API 调用参数（内部复用）。"""
        kwargs: dict = {
            "model": self.model,
            "messages": messages,
        }
        if tools:
            kwargs["tools"] = tools
        if thinking_enabled:
            kwargs["thinking"] = {"type": "enabled"}
        if stream:
            kwargs["stream"] = True
        return kwargs

    async def chat(
        self,
        messages: list[dict],
        tools: list[dict] | None = None,
        thinking_enabled: bool = False,
    ) -> ChatCompletion:
        """
        向 LLM 发送消息并获取完整响应。

        参数：
          messages:         对话历史列表
          tools:            可选，工具定义列表（OpenAI 格式）
          thinking_enabled: 是否启用思维链（DeepSeek Reasoning）

        返回：
          ChatCompletion 对象
        """
        kwargs = self._build_kwargs(messages, tools, thinking_enabled)
        return await self.client.chat.completions.create(**kwargs)

    async def chat_stream(
        self,
        messages: list[dict],
        tools: list[dict] | None = None,
        thinking_enabled: bool = False,
    ):
        """
        向 LLM 发送消息并获取流式响应。

        参数：
          messages:         对话历史列表
          tools:            可选，工具定义列表（OpenAI 格式）
          thinking_enabled: 是否启用思维链

        返回：
          AsyncStream[ChatCompletionChunk] 异步迭代器
        """
        kwargs = self._build_kwargs(messages, tools, thinking_enabled, stream=True)
        return await self.client.chat.completions.create(**kwargs)
```

- [ ] **Step 4: 运行测试确认通过**

```bash
uv run pytest tests/test_llm.py -v
```

Expected: ALL PASS

- [ ] **Step 5: Commit**

```bash
git add my_small_agent/llm.py tests/test_llm.py
git commit -m "feat(llm): add chat_stream() and thinking parameter support"
```

---

### Task 3: 新增工具 — web_search + current_time

**Files:**
- Create: `my_small_agent/tools/web_search.py`
- Create: `my_small_agent/tools/current_time.py`
- Modify: `my_small_agent/tools/__init__.py`
- Modify: `my_small_agent/__main__.py`
- Create: `tests/test_tools_new.py`

**Interfaces:**
- Consumes: `Tool` 基类, `ToolRegistry`, `Settings.timezone`
- Produces: `WebSearchTool`, `CurrentTimeTool`, `create_default_registry(settings: Settings) -> ToolRegistry`

- [ ] **Step 1: 写失败测试 — current_time 工具**

创建 `tests/test_tools_new.py`：

```python
"""新增工具（web_search, current_time）的单元测试。"""

import pytest
from unittest.mock import patch, AsyncMock, MagicMock


@pytest.mark.asyncio
async def test_current_time_returns_formatted_time():
    """current_time 工具应返回格式化的当前时间字符串。"""
    from my_small_agent.tools.current_time import CurrentTimeTool

    tool = CurrentTimeTool(timezone="Asia/Shanghai")
    result = await tool.execute()

    # 验证返回格式包含年月日和时区信息
    assert "202" in result  # 年份
    assert "CST" in result or "Asia/Shanghai" in result or ":" in result
    assert tool.name == "current_time"
    assert tool.danger_level == "safe"


@pytest.mark.asyncio
async def test_current_time_respects_timezone():
    """current_time 工具应尊重传入的时区配置。"""
    from my_small_agent.tools.current_time import CurrentTimeTool

    tool = CurrentTimeTool(timezone="UTC")
    result = await tool.execute()
    assert "UTC" in result


@pytest.mark.asyncio
async def test_web_search_tool_metadata():
    """web_search 工具的元数据应正确设置。"""
    from my_small_agent.tools.web_search import WebSearchTool

    tool = WebSearchTool()
    assert tool.name == "web_search"
    assert tool.danger_level == "safe"
    assert "query" in tool.parameters["properties"]


@pytest.mark.asyncio
async def test_web_search_formats_results():
    """web_search 工具应格式化搜索结果。"""
    from my_small_agent.tools.web_search import WebSearchTool

    tool = WebSearchTool()

    mock_results = [
        {"title": "Result 1", "href": "https://example.com/1", "body": "First result"},
        {"title": "Result 2", "href": "https://example.com/2", "body": "Second result"},
    ]

    with patch("my_small_agent.tools.web_search.AsyncDDGS") as MockDDGS:
        mock_instance = AsyncMock()
        mock_instance.atext = AsyncMock(return_value=mock_results)
        mock_instance.__aenter__ = AsyncMock(return_value=mock_instance)
        mock_instance.__aexit__ = AsyncMock(return_value=None)
        MockDDGS.return_value = mock_instance

        result = await tool.execute(query="test query", max_results=2)

    assert "Result 1" in result
    assert "https://example.com/1" in result
    assert "Result 2" in result


@pytest.mark.asyncio
async def test_web_search_handles_no_results():
    """web_search 工具在无结果时应返回提示。"""
    from my_small_agent.tools.web_search import WebSearchTool

    tool = WebSearchTool()

    with patch("my_small_agent.tools.web_search.AsyncDDGS") as MockDDGS:
        mock_instance = AsyncMock()
        mock_instance.atext = AsyncMock(return_value=[])
        mock_instance.__aenter__ = AsyncMock(return_value=mock_instance)
        mock_instance.__aexit__ = AsyncMock(return_value=None)
        MockDDGS.return_value = mock_instance

        result = await tool.execute(query="nonexistent query")

    assert "No results found" in result
```

- [ ] **Step 2: 运行测试确认失败**

```bash
uv run pytest tests/test_tools_new.py -v
```

Expected: FAIL — 模块不存在

- [ ] **Step 3: 实现 current_time 工具**

创建 `my_small_agent/tools/current_time.py`：

```python
"""
当前时间工具 - 返回配置时区下的当前日期时间。

安全级别：safe（只读操作，自动执行）

配合 web_search 使用，让 LLM 知道"现在"是什么时候，
从而能搜索最新信息或判断时效性。
"""

from datetime import datetime
from zoneinfo import ZoneInfo

from my_small_agent.tools.base import Tool


class CurrentTimeTool(Tool):
    """返回配置时区下的当前日期和时间。"""

    # --- 工具元数据 ---
    name = "current_time"
    description = "Get the current date and time in the configured timezone."

    # 无需参数
    parameters = {
        "type": "object",
        "properties": {},
    }

    # 安全级别：safe（只读，自动执行）
    danger_level = "safe"

    def __init__(self, timezone: str = "Asia/Shanghai") -> None:
        """初始化时接收时区字符串（如 'Asia/Shanghai'）。"""
        self._timezone = timezone

    async def execute(self, **kwargs) -> str:
        """返回当前时间的格式化字符串。"""
        tz = ZoneInfo(self._timezone)
        now = datetime.now(tz)
        return now.strftime("%Y-%m-%d %H:%M:%S %Z (%A)")
```

- [ ] **Step 4: 实现 web_search 工具**

创建 `my_small_agent/tools/web_search.py`：

```python
"""
网页搜索工具 - 使用 DuckDuckGo 搜索引擎查询网页信息。

安全级别：safe（只读搜索，无副作用，自动执行）

使用 duckduckgo-search 库的 AsyncDDGS 异步接口，
无需 API Key，免费使用。
"""

from duckduckgo_search import AsyncDDGS

from my_small_agent.tools.base import Tool


class WebSearchTool(Tool):
    """使用 DuckDuckGo 搜索网页并返回结构化结果。"""

    # --- 工具元数据 ---
    name = "web_search"
    description = "Search the web using DuckDuckGo and return top results with titles, URLs, and snippets."

    parameters = {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "The search query string.",
            },
            "max_results": {
                "type": "integer",
                "description": "Maximum number of results to return (default: 5).",
            },
        },
        "required": ["query"],
    }

    # 安全级别：safe（只读搜索，自动执行）
    danger_level = "safe"

    async def execute(self, **kwargs) -> str:
        """
        执行搜索并返回格式化结果。

        返回格式示例：
          1. 标题
             URL: https://...
             摘要内容
        """
        query = kwargs["query"]
        max_results = kwargs.get("max_results", 5)

        try:
            async with AsyncDDGS() as ddgs:
                results = await ddgs.atext(query, max_results=max_results)

            if not results:
                return "No results found."

            formatted = []
            for i, r in enumerate(results, 1):
                formatted.append(
                    f"{i}. {r['title']}\n"
                    f"   URL: {r['href']}\n"
                    f"   {r['body']}"
                )
            return "\n\n".join(formatted)

        except Exception as e:
            return f"Error searching: {e}"
```

- [ ] **Step 5: 更新工具注册表**

修改 `my_small_agent/tools/__init__.py`：

```python
"""
工具注册表模块 - 中心化注册和管理所有可用工具。

设计思路：
  - ToolRegistry 是一个字典容器，以工具名称为 key 存储工具实例
  - 注册后的工具可以转换为 OpenAI 要求的 tools 参数格式
  - create_default_registry(settings) 工厂函数一键注册所有内置工具
  - 未来添加新工具只需：1) 继承 Tool 基类  2) 在注册表中 register
"""

from my_small_agent.config import Settings
from my_small_agent.tools.base import Tool
from my_small_agent.tools.current_time import CurrentTimeTool
from my_small_agent.tools.file_read import ReadFileTool
from my_small_agent.tools.file_write import WriteFileTool
from my_small_agent.tools.list_dir import ListDirectoryTool
from my_small_agent.tools.shell_exec import ExecuteShellTool
from my_small_agent.tools.web_search import WebSearchTool


class ToolRegistry:
    """
    中心化工具注册表。

    职责：
      - register(): 注册新工具
      - get():      按名称查找工具
      - get_openai_tools(): 将所有工具转为 OpenAI API 格式
      - list_all(): 列出所有已注册工具
    """

    def __init__(self) -> None:
        self._tools: dict[str, Tool] = {}

    def register(self, tool: Tool) -> None:
        """注册一个工具实例到注册表。"""
        self._tools[tool.name] = tool

    def get(self, name: str) -> Tool | None:
        """通过名称查找工具，找不到返回 None。"""
        return self._tools.get(name)

    def get_openai_tools(self) -> list[dict]:
        """将所有已注册工具转换为 OpenAI API 的 tools 参数格式。"""
        return [
            {
                "type": "function",
                "function": {
                    "name": tool.name,
                    "description": tool.description,
                    "parameters": tool.parameters,
                },
            }
            for tool in self._tools.values()
        ]

    def list_all(self) -> list[Tool]:
        """返回所有已注册工具的列表。"""
        return list(self._tools.values())


def create_default_registry(settings: Settings) -> ToolRegistry:
    """
    创建并返回一个包含所有内置工具的注册表。

    内置工具：
      - read_file:       读取文件（安全）
      - write_file:      写入文件（危险，需确认）
      - list_directory:  列出目录（安全）
      - execute_shell:   执行命令（危险，需确认）
      - web_search:      网页搜索（安全）
      - current_time:    当前时间（安全）
    """
    registry = ToolRegistry()
    registry.register(ReadFileTool())
    registry.register(WriteFileTool())
    registry.register(ListDirectoryTool())
    registry.register(ExecuteShellTool())
    registry.register(WebSearchTool())
    registry.register(CurrentTimeTool(timezone=settings.timezone))
    return registry
```

- [ ] **Step 6: 更新入口点**

修改 `my_small_agent/__main__.py` 中 `create_default_registry()` 的调用：

```python
# 原来：registry = create_default_registry()
# 改为：
registry = create_default_registry(settings)
```

- [ ] **Step 7: 运行测试确认通过**

```bash
uv run pytest tests/test_tools_new.py -v
```

Expected: ALL PASS

- [ ] **Step 8: 运行全部测试确保无回归**

```bash
uv run pytest tests/ -v
```

Expected: ALL PASS（注意 `tests/test_tools_registry.py` 中如果有调用 `create_default_registry()` 无参数的测试需要修复）

- [ ] **Step 9: Commit**

```bash
git add my_small_agent/tools/current_time.py my_small_agent/tools/web_search.py my_small_agent/tools/__init__.py my_small_agent/__main__.py tests/test_tools_new.py
git commit -m "feat(tools): add web_search and current_time tools"
```

---

### Task 4: Agent 核心 — AgentResponse + Thinking 历史管理

**Files:**
- Modify: `my_small_agent/agent.py`
- Modify: `tests/test_agent.py`

**Interfaces:**
- Consumes: `LLMClient.chat(messages, tools?, thinking_enabled?)`, `Settings.enable_streaming`, `Settings.enable_thinking`
- Produces: `AgentResponse(content: str, thinking: str)`, `Agent.run_turn() -> AgentResponse`, `Agent.strip_thinking_from_history()`, `Agent.streaming_enabled: bool`, `Agent.thinking_enabled: bool`

- [ ] **Step 1: 写失败测试 — AgentResponse 数据类**

在 `tests/test_agent.py` 追加：

```python
from my_small_agent.agent import AgentResponse


def test_agent_response_dataclass():
    """AgentResponse 应正确存储 content 和 thinking。"""
    resp = AgentResponse(content="hello", thinking="let me think...")
    assert resp.content == "hello"
    assert resp.thinking == "let me think..."


def test_agent_response_default_thinking():
    """AgentResponse 的 thinking 字段默认为空字符串。"""
    resp = AgentResponse(content="hello")
    assert resp.thinking == ""
```

- [ ] **Step 2: 写失败测试 — strip_thinking_from_history**

```python
@pytest.mark.asyncio
async def test_strip_thinking_from_history(monkeypatch):
    """strip_thinking_from_history 应移除历史中的 reasoning_content。"""
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    from my_small_agent.config import Settings
    from my_small_agent.llm import LLMClient
    from my_small_agent.tools import ToolRegistry

    settings = Settings(_env_file=None)
    llm = LLMClient(settings)
    registry = ToolRegistry()
    agent = Agent(llm, registry, settings)

    # 模拟带 thinking 的历史
    agent.messages.append({
        "role": "assistant",
        "content": "answer",
        "reasoning_content": "thinking process",
    })

    agent.strip_thinking_from_history()

    # reasoning_content 应被移除
    assistant_msg = agent.messages[-1]
    assert "reasoning_content" not in assistant_msg
    assert assistant_msg["content"] == "answer"
```

- [ ] **Step 3: 写失败测试 — Agent 运行时状态初始化**

```python
@pytest.mark.asyncio
async def test_agent_runtime_state_from_settings(monkeypatch):
    """Agent 应从 Settings 初始化 streaming 和 thinking 状态。"""
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.setenv("ENABLE_STREAMING", "false")
    monkeypatch.setenv("ENABLE_THINKING", "false")
    from my_small_agent.config import Settings
    from my_small_agent.llm import LLMClient
    from my_small_agent.tools import ToolRegistry

    settings = Settings(_env_file=None)
    llm = LLMClient(settings)
    registry = ToolRegistry()
    agent = Agent(llm, registry, settings)

    assert agent.streaming_enabled is False
    assert agent.thinking_enabled is False
```

- [ ] **Step 4: 运行测试确认失败**

```bash
uv run pytest tests/test_agent.py::test_agent_response_dataclass tests/test_agent.py::test_agent_response_default_thinking tests/test_agent.py::test_strip_thinking_from_history tests/test_agent.py::test_agent_runtime_state_from_settings -v
```

Expected: FAIL

- [ ] **Step 5: 实现 Agent 变更**

修改 `my_small_agent/agent.py`，添加 `AgentResponse` 数据类、运行时状态、`strip_thinking_from_history()`，并修改 `run_turn()` 返回 `AgentResponse`：

```python
"""
Agent 核心模块 - 管理对话循环和工具调用的核心逻辑。
"""

import json
from dataclasses import dataclass
from typing import Any, Callable, Coroutine

from my_small_agent.config import Settings
from my_small_agent.llm import LLMClient
from my_small_agent.tools import ToolRegistry

ConfirmCallback = Callable[[str, str, dict], Coroutine[Any, Any, bool]]

SYSTEM_PROMPT = """你是一个运行在命令行终端中的通用任务助手（CLI Agent）。

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
"""


@dataclass
class AgentResponse:
    """Agent 单轮对话的返回结果。"""
    content: str           # 最终文本回复
    thinking: str = ""     # 思维链内容（thinking 关闭时为空）


class Agent:
    """Agent 核心类 - 驱动对话循环和工具执行。"""

    def __init__(
        self,
        llm: LLMClient,
        registry: ToolRegistry,
        settings: Settings,
    ) -> None:
        self.llm = llm
        self.registry = registry
        self.max_iterations = settings.max_iterations

        # 运行时状态（可通过 CLI 命令动态切换）
        self.streaming_enabled = settings.enable_streaming
        self.thinking_enabled = settings.enable_thinking

        # 初始化对话历史
        self.messages: list[dict] = [
            {"role": "system", "content": SYSTEM_PROMPT}
        ]

    async def run_turn(
        self,
        user_input: str,
        confirm_callback: ConfirmCallback,
    ) -> AgentResponse:
        """
        执行一轮完整的对话（非流式模式）。

        返回 AgentResponse，包含最终文本和可选的思维链内容。
        """
        self.messages.append({"role": "user", "content": user_input})
        tools = self.registry.get_openai_tools()
        iteration = 0

        while iteration < self.max_iterations:
            iteration += 1

            response = await self.llm.chat(
                messages=self.messages,
                tools=tools if tools else None,
                thinking_enabled=self.thinking_enabled,
            )

            message = response.choices[0].message

            if not message.tool_calls:
                content = message.content or ""
                thinking = getattr(message, 'reasoning_content', '') or ''
                # 保存到历史（含 thinking）
                msg_dict = {"role": "assistant", "content": content}
                if thinking:
                    msg_dict["reasoning_content"] = thinking
                self.messages.append(msg_dict)
                return AgentResponse(content=content, thinking=thinking)

            # 工具调用处理（与原来相同）
            self.messages.append(message.model_dump())

            for tool_call in message.tool_calls:
                tool_name = tool_call.function.name
                arguments = json.loads(tool_call.function.arguments)

                tool = self.registry.get(tool_name)
                if tool is None:
                    result = f"Error: Unknown tool '{tool_name}'"
                else:
                    if tool.danger_level == "dangerous":
                        confirmed = await confirm_callback(
                            tool_name, tool.description, arguments
                        )
                        if not confirmed:
                            result = "User rejected this tool execution."
                        else:
                            result = await self._execute_tool(tool, arguments)
                    else:
                        result = await self._execute_tool(tool, arguments)

                self.messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": tool_call.id,
                        "content": result,
                    }
                )

        return AgentResponse(
            content="Reached maximum iteration limit. Please try a simpler request."
        )

    async def _execute_tool(self, tool: Any, arguments: dict) -> str:
        """安全地执行工具。"""
        try:
            return await tool.execute(**arguments)
        except Exception as e:
            return f"Error executing {tool.name}: {e}"

    def strip_thinking_from_history(self) -> None:
        """从历史中剔除 reasoning_content 字段，节省 token 开销。"""
        for msg in self.messages:
            if msg.get("role") == "assistant" and "reasoning_content" in msg:
                del msg["reasoning_content"]

    def clear_history(self) -> None:
        """清空对话历史，但保留 system prompt。"""
        self.messages = [self.messages[0]]
```

- [ ] **Step 6: 运行测试确认通过**

```bash
uv run pytest tests/test_agent.py -v
```

Expected: ALL PASS（注意：现有测试中如果有断言 `run_turn()` 返回 `str` 的，需要改为断言 `.content`）

- [ ] **Step 7: 修复现有测试的返回类型断言**

检查 `tests/test_agent.py` 和 `tests/test_integration.py` 中所有 `await agent.run_turn(...)` 的断言，从 `assert result == "..."` 改为 `assert result.content == "..."`。

- [ ] **Step 8: 运行全部测试**

```bash
uv run pytest tests/ -v
```

Expected: ALL PASS

- [ ] **Step 9: Commit**

```bash
git add my_small_agent/agent.py tests/test_agent.py tests/test_integration.py
git commit -m "feat(agent): add AgentResponse, thinking history management, runtime state"
```

---

### Task 5: Agent 流式对话循环 — run_turn_stream()

**Files:**
- Modify: `my_small_agent/agent.py`
- Create: `tests/test_agent_stream.py`

**Interfaces:**
- Consumes: `LLMClient.chat_stream()`, `Agent.streaming_enabled`, `Agent.thinking_enabled`
- Produces: `Agent.run_turn_stream(user_input, confirm_callback) -> AsyncGenerator[tuple[str, str], None]`

- [ ] **Step 1: 写失败测试 — 流式纯文本输出**

创建 `tests/test_agent_stream.py`：

```python
"""Agent 流式对话循环的单元测试。"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from my_small_agent.agent import Agent


@pytest.fixture
def agent_setup(monkeypatch):
    """创建测试用的 Agent 实例。"""
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    from my_small_agent.config import Settings
    from my_small_agent.llm import LLMClient
    from my_small_agent.tools import ToolRegistry

    settings = Settings(_env_file=None)
    llm = LLMClient(settings)
    registry = ToolRegistry()
    agent = Agent(llm, registry, settings)
    return agent


@pytest.mark.asyncio
async def test_run_turn_stream_text_response(agent_setup):
    """流式模式下，纯文本响应应 yield content 事件。"""
    agent = agent_setup

    # 模拟流式 chunk
    chunk1 = MagicMock()
    chunk1.choices = [MagicMock()]
    chunk1.choices[0].delta = MagicMock()
    chunk1.choices[0].delta.content = "Hello"
    chunk1.choices[0].delta.tool_calls = None
    chunk1.choices[0].delta.reasoning_content = None

    chunk2 = MagicMock()
    chunk2.choices = [MagicMock()]
    chunk2.choices[0].delta = MagicMock()
    chunk2.choices[0].delta.content = " World"
    chunk2.choices[0].delta.tool_calls = None
    chunk2.choices[0].delta.reasoning_content = None

    # 模拟异步迭代器
    async def mock_stream():
        for chunk in [chunk1, chunk2]:
            yield chunk

    agent.llm.chat_stream = AsyncMock(return_value=mock_stream())

    events = []
    async for event_type, content in agent.run_turn_stream("hi", AsyncMock()):
        events.append((event_type, content))

    assert ("content", "Hello") in events
    assert ("content", " World") in events


@pytest.mark.asyncio
async def test_run_turn_stream_thinking_events(agent_setup):
    """流式模式下，thinking 内容应 yield thinking 事件。"""
    agent = agent_setup

    chunk1 = MagicMock()
    chunk1.choices = [MagicMock()]
    chunk1.choices[0].delta = MagicMock()
    chunk1.choices[0].delta.content = None
    chunk1.choices[0].delta.tool_calls = None
    chunk1.choices[0].delta.reasoning_content = "Let me think"

    chunk2 = MagicMock()
    chunk2.choices = [MagicMock()]
    chunk2.choices[0].delta = MagicMock()
    chunk2.choices[0].delta.content = "Answer"
    chunk2.choices[0].delta.tool_calls = None
    chunk2.choices[0].delta.reasoning_content = None

    async def mock_stream():
        for chunk in [chunk1, chunk2]:
            yield chunk

    agent.llm.chat_stream = AsyncMock(return_value=mock_stream())

    events = []
    async for event_type, content in agent.run_turn_stream("hi", AsyncMock()):
        events.append((event_type, content))

    assert ("thinking", "Let me think") in events
    assert ("content", "Answer") in events
```

- [ ] **Step 2: 运行测试确认失败**

```bash
uv run pytest tests/test_agent_stream.py -v
```

Expected: FAIL — `run_turn_stream` 不存在

- [ ] **Step 3: 实现 run_turn_stream()**

在 `my_small_agent/agent.py` 的 `Agent` 类中添加：

```python
from typing import AsyncGenerator

async def run_turn_stream(
    self,
    user_input: str,
    confirm_callback: ConfirmCallback,
) -> AsyncGenerator[tuple[str, str], None]:
    """
    流式版本的对话循环。

    yield (event_type, content) 元组：
      - ("thinking", text): 思维链内容片段
      - ("content", text):  正文内容片段
    """
    self.messages.append({"role": "user", "content": user_input})
    tools = self.registry.get_openai_tools()
    iteration = 0

    while iteration < self.max_iterations:
        iteration += 1

        stream = await self.llm.chat_stream(
            messages=self.messages,
            tools=tools if tools else None,
            thinking_enabled=self.thinking_enabled,
        )

        # 从 chunk 中累积完整响应
        full_content = ""
        full_thinking = ""
        tool_calls_data: list[dict] = []

        async for chunk in stream:
            delta = chunk.choices[0].delta

            # 思维内容
            reasoning = getattr(delta, 'reasoning_content', None)
            if reasoning:
                full_thinking += reasoning
                yield ("thinking", reasoning)

            # 正文内容
            if delta.content:
                full_content += delta.content
                yield ("content", delta.content)

            # 工具调用（需要拼接多个 chunk 的 delta）
            if delta.tool_calls:
                for tc_delta in delta.tool_calls:
                    idx = tc_delta.index
                    # 扩展列表长度
                    while len(tool_calls_data) <= idx:
                        tool_calls_data.append({"id": "", "function": {"name": "", "arguments": ""}})
                    # 拼接各字段
                    if tc_delta.id:
                        tool_calls_data[idx]["id"] = tc_delta.id
                    if tc_delta.function:
                        if tc_delta.function.name:
                            tool_calls_data[idx]["function"]["name"] += tc_delta.function.name
                        if tc_delta.function.arguments:
                            tool_calls_data[idx]["function"]["arguments"] += tc_delta.function.arguments

        # 流结束：判断是否有工具调用
        if not tool_calls_data:
            # 纯文本回复 → 保存到历史，结束
            msg_dict: dict = {"role": "assistant", "content": full_content}
            if full_thinking:
                msg_dict["reasoning_content"] = full_thinking
            self.messages.append(msg_dict)
            return

        # 有工具调用 → 保存 assistant 消息（含 tool_calls）
        assistant_msg: dict = {
            "role": "assistant",
            "content": full_content or None,
            "tool_calls": [
                {
                    "id": tc["id"],
                    "type": "function",
                    "function": tc["function"],
                }
                for tc in tool_calls_data
            ],
        }
        if full_thinking:
            assistant_msg["reasoning_content"] = full_thinking
        self.messages.append(assistant_msg)

        # 执行每个工具调用
        for tc in tool_calls_data:
            tool_name = tc["function"]["name"]
            arguments = json.loads(tc["function"]["arguments"])

            tool = self.registry.get(tool_name)
            if tool is None:
                result = f"Error: Unknown tool '{tool_name}'"
            else:
                if tool.danger_level == "dangerous":
                    confirmed = await confirm_callback(
                        tool_name, tool.description, arguments
                    )
                    if not confirmed:
                        result = "User rejected this tool execution."
                    else:
                        result = await self._execute_tool(tool, arguments)
                else:
                    result = await self._execute_tool(tool, arguments)

            self.messages.append(
                {"role": "tool", "tool_call_id": tc["id"], "content": result}
            )

    # 达到最大迭代次数
    yield ("content", "\nReached maximum iteration limit.")
```

- [ ] **Step 4: 运行测试确认通过**

```bash
uv run pytest tests/test_agent_stream.py -v
```

Expected: ALL PASS

- [ ] **Step 5: 运行全部测试**

```bash
uv run pytest tests/ -v
```

Expected: ALL PASS

- [ ] **Step 6: Commit**

```bash
git add my_small_agent/agent.py tests/test_agent_stream.py
git commit -m "feat(agent): add run_turn_stream() async generator for streaming"
```

---

### Task 6: CLI 层 — 新命令 + 流式渲染

**Files:**
- Modify: `my_small_agent/cli.py`
- Modify: `tests/test_integration.py`（可选，验证端到端）

**Interfaces:**
- Consumes: `Agent.run_turn_stream()`, `Agent.run_turn() -> AgentResponse`, `Agent.streaming_enabled`, `Agent.thinking_enabled`, `Agent.strip_thinking_from_history()`
- Produces: CLI 用户交互（终端输出）

- [ ] **Step 1: 实现 CLI 新命令和流式渲染**

重写 `my_small_agent/cli.py`：

```python
"""
CLI 交互层 - 处理终端的用户输入输出和斜杠命令。

使用的库：
  - prompt_toolkit: 提供增强型终端输入
  - rich:           美化输出（Markdown 渲染、面板、加载动画）

交互流程：
  1. 显示欢迎面板
  2. 等待用户输入
  3. 以 "/" 开头 → 解析为命令
  4. 普通文本 → 传给 Agent 处理对话（流式或非流式）
  5. 重复步骤 2-4
"""

from prompt_toolkit import PromptSession
from prompt_toolkit.patch_stdout import patch_stdout
from rich.console import Console
from rich.markdown import Markdown
from rich.panel import Panel
from rich.status import Status

from my_small_agent.agent import Agent


class CLI:
    """终端用户界面 - 用户通过命令行与 Agent 交互。"""

    def __init__(self, agent: Agent) -> None:
        self.agent = agent
        self.console = Console()
        self.session: PromptSession = PromptSession()
        self._running = True

    async def run(self) -> None:
        """启动 REPL 主循环。"""
        self._print_welcome()

        while self._running:
            try:
                with patch_stdout():
                    user_input = await self.session.prompt_async("You> ")

                user_input = user_input.strip()
                if not user_input:
                    continue

                if user_input.startswith("/"):
                    await self._handle_command(user_input)
                    continue

                await self._run_agent_turn(user_input)

            except (KeyboardInterrupt, EOFError):
                self._running = False
                self.console.print("\n[dim]Goodbye![/dim]")

    async def _run_agent_turn(self, user_input: str) -> None:
        """根据 streaming 状态选择流式或非流式对话。"""
        if self.agent.streaming_enabled:
            await self._run_agent_turn_stream(user_input)
        else:
            await self._run_agent_turn_normal(user_input)

    async def _run_agent_turn_normal(self, user_input: str) -> None:
        """非流式模式：等待完整响应后渲染。"""
        with Status("[bold cyan]Thinking...", console=self.console):
            response = await self.agent.run_turn(
                user_input,
                confirm_callback=self._confirm_dangerous_action,
            )

        self.console.print()
        # 如果有 thinking 内容，先展示
        if response.thinking:
            self.console.print(f"[dim]💭 {response.thinking}[/dim]")
            self.console.print()
        self.console.print(Markdown(response.content))
        self.console.print()

    async def _run_agent_turn_stream(self, user_input: str) -> None:
        """流式模式：逐 chunk 打印到终端。"""
        self.console.print()
        in_thinking = False

        async for event_type, content in self.agent.run_turn_stream(
            user_input, self._confirm_dangerous_action
        ):
            if event_type == "thinking":
                if not in_thinking:
                    self.console.print("[dim]💭 ", end="")
                    in_thinking = True
                self.console.print(f"[dim]{content}[/dim]", end="")

            elif event_type == "content":
                if in_thinking:
                    self.console.print()  # 结束 thinking 行
                    self.console.print()
                    in_thinking = False
                self.console.print(content, end="")

        # 结尾换行
        if in_thinking:
            self.console.print()
        self.console.print()
        self.console.print()

    async def _confirm_dangerous_action(
        self, tool_name: str, description: str, arguments: dict
    ) -> bool:
        """危险操作确认回调。"""
        args_display = ", ".join(f"{k}={repr(v)}" for k, v in arguments.items())

        self.console.print(
            Panel(
                f"[bold yellow]⚠️  Dangerous operation[/bold yellow]\n\n"
                f"Tool: [bold]{tool_name}[/bold]\n"
                f"Args: {args_display}",
                title="Confirmation Required",
                border_style="yellow",
            )
        )

        with patch_stdout():
            answer = await self.session.prompt_async("Allow execution? [y/N] ")

        return answer.strip().lower() in ("y", "yes")

    async def _handle_command(self, command: str) -> None:
        """解析并执行斜杠命令。"""
        cmd = command.lower().split()[0]

        if cmd == "/help":
            self._print_help()
        elif cmd == "/tools":
            self._print_tools()
        elif cmd == "/stream":
            self._toggle_stream()
        elif cmd == "/think":
            self._toggle_think()
        elif cmd == "/status":
            self._print_status()
        elif cmd == "/clear":
            self.agent.clear_history()
            self.console.print("[green]Conversation history cleared.[/green]")
        elif cmd == "/exit":
            self._running = False
            self.console.print("[dim]Goodbye![/dim]")
        else:
            self.console.print(
                f"[red]Unknown command: {cmd}[/red]. Type /help for available commands."
            )

    def _toggle_stream(self) -> None:
        """切换流式输出开关。"""
        self.agent.streaming_enabled = not self.agent.streaming_enabled
        state = "开启" if self.agent.streaming_enabled else "关闭"
        self.console.print(f"[cyan]流式输出已{state}[/cyan]")

    def _toggle_think(self) -> None:
        """切换思维链模式开关。"""
        self.agent.thinking_enabled = not self.agent.thinking_enabled
        state = "开启" if self.agent.thinking_enabled else "关闭"
        if not self.agent.thinking_enabled:
            self.agent.strip_thinking_from_history()
        self.console.print(f"[cyan]思维链模式已{state}[/cyan]")

    def _print_status(self) -> None:
        """显示当前 Agent 状态。"""
        streaming = "[green]开启[/green]" if self.agent.streaming_enabled else "[red]关闭[/red]"
        thinking = "[green]开启[/green]" if self.agent.thinking_enabled else "[red]关闭[/red]"
        self.console.print(
            Panel(
                f"  模型:     [bold]{self.agent.llm.model}[/bold]\n"
                f"  流式输出: {streaming}\n"
                f"  思维链:   {thinking}",
                title="当前状态",
                border_style="cyan",
            )
        )

    def _print_welcome(self) -> None:
        """启动时显示欢迎面板。"""
        self.console.print(
            Panel(
                "[bold]MySmallAgent[/bold] - Your CLI assistant\n\n"
                "Type your message to chat, or use commands:\n"
                "  /help   - Show help\n"
                "  /tools  - List available tools\n"
                "  /stream - Toggle streaming output\n"
                "  /think  - Toggle thinking mode\n"
                "  /status - Show current settings\n"
                "  /clear  - Clear history\n"
                "  /exit   - Exit",
                title="Welcome",
                border_style="blue",
            )
        )
        self.console.print()

    def _print_help(self) -> None:
        """显示帮助信息面板。"""
        self.console.print(
            Panel(
                "[bold]Available Commands:[/bold]\n\n"
                "  [cyan]/help[/cyan]   - Show this help message\n"
                "  [cyan]/tools[/cyan]  - List all registered tools\n"
                "  [cyan]/stream[/cyan] - Toggle streaming output\n"
                "  [cyan]/think[/cyan]  - Toggle thinking mode\n"
                "  [cyan]/status[/cyan] - Show current settings\n"
                "  [cyan]/clear[/cyan]  - Clear conversation history\n"
                "  [cyan]/exit[/cyan]   - Exit the program\n\n"
                "[bold]Tips:[/bold]\n"
                "  • Press Ctrl+C or Ctrl+D to exit\n"
                "  • The agent can read/write files, search the web, and run shell commands",
                title="Help",
                border_style="green",
            )
        )

    def _print_tools(self) -> None:
        """列出所有已注册的工具。"""
        tools = self.agent.registry.list_all()
        if not tools:
            self.console.print("[yellow]No tools registered.[/yellow]")
            return

        lines = []
        for tool in tools:
            level_color = "green" if tool.danger_level == "safe" else "yellow"
            level_label = "safe" if tool.danger_level == "safe" else "dangerous"
            lines.append(
                f"  [bold]{tool.name}[/bold]  "
                f"[{level_color}][{level_label}][/{level_color}]\n"
                f"    [dim]{tool.description}[/dim]"
            )

        self.console.print(
            Panel(
                "\n\n".join(lines),
                title=f"Registered Tools ({len(tools)})",
                border_style="cyan",
            )
        )
```

- [ ] **Step 2: 运行全部测试**

```bash
uv run pytest tests/ -v
```

Expected: ALL PASS（CLI 层主要通过集成测试和手动验证）

- [ ] **Step 3: 手动冒烟测试**

```bash
uv run python -m my_small_agent
```

验证：
1. 欢迎面板显示新命令列表
2. `/status` 显示模型名、流式开启、思维链开启
3. `/stream` 切换并反馈
4. `/think` 切换并反馈
5. `/tools` 列出 6 个工具（含 web_search、current_time）
6. 输入一条消息，观察流式输出效果

- [ ] **Step 4: Commit**

```bash
git add my_small_agent/cli.py
git commit -m "feat(cli): add /stream /think /status commands and streaming render"
```

---
