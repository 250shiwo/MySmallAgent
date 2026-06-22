# MySmallAgent Core Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 实现一个基于 OpenAI tool_calls 的 CLI Agent，支持对话循环、4 个内置工具和终端交互。

**Architecture:** 模块化分层架构——CLI 层处理用户交互，Agent 层管理对话循环，LLM 层封装 API 调用，Tools 层提供中心化工具注册表。所有 I/O 使用 async/await。

**Tech Stack:** Python 3.11+, openai, pydantic-settings, prompt-toolkit, rich, uv

## Global Constraints

- Python >= 3.11
- 使用 `uv` 管理依赖
- 异步优先（async/await）
- 工具 danger_level: "safe" 自动执行，"dangerous" 需用户确认
- 对话历史纯内存，不持久化
- 所有工具返回值为 `str` 类型

---

### Task 1: 项目脚手架

**Files:**
- Create: `pyproject.toml`
- Create: `.env.example`
- Create: `my_small_agent/__init__.py`
- Create: `my_small_agent/__main__.py` (占位)
- Create: `my_small_agent/tools/__init__.py` (占位)

**Interfaces:**
- Consumes: 无
- Produces: 项目可通过 `uv sync` 安装所有依赖，`python -m my_small_agent` 可运行（即使只打印 hello）

- [ ] **Step 1: 创建 pyproject.toml**

```toml
[project]
name = "my-small-agent"
version = "0.1.0"
description = "A small CLI agent powered by OpenAI tool_calls"
requires-python = ">=3.11"
dependencies = [
    "openai>=1.0",
    "pydantic-settings>=2.0",
    "prompt-toolkit>=3.0",
    "rich>=13.0",
]

[project.scripts]
agent = "my_small_agent.__main__:main_entry"

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.pytest.ini_options]
asyncio_mode = "auto"
testpaths = ["tests"]

[dependency-groups]
dev = [
    "pytest>=8.0",
    "pytest-asyncio>=0.23",
]
```

- [ ] **Step 2: 创建 .env.example**

```env
OPENAI_API_KEY=sk-your-key-here
OPENAI_BASE_URL=https://api.openai.com/v1
OPENAI_MODEL=gpt-4o
MAX_ITERATIONS=10
```

- [ ] **Step 3: 创建包目录和占位文件**

`my_small_agent/__init__.py`:
```python
"""MySmallAgent - A small CLI agent powered by OpenAI tool_calls."""

__version__ = "0.1.0"
```

`my_small_agent/__main__.py`:
```python
"""Entry point for python -m my_small_agent."""

import asyncio


async def main() -> None:
    print("MySmallAgent is starting...")


def main_entry() -> None:
    """Sync entry point for pyproject.toml scripts."""
    asyncio.run(main())


if __name__ == "__main__":
    main_entry()
```

`my_small_agent/tools/__init__.py`:
```python
"""Tool registry and built-in tools."""
```

- [ ] **Step 4: 初始化项目并验证**

```bash
cd c:\Users\chancemate\Desktop\MySmallAgent
uv sync
uv run python -m my_small_agent
```

Expected: 输出 `MySmallAgent is starting...`

- [ ] **Step 5: Commit**

```bash
git add .
git commit -m "feat: project scaffolding with pyproject.toml and package structure"
```

---

### Task 2: 配置管理模块

**Files:**
- Create: `my_small_agent/config.py`
- Create: `tests/__init__.py`
- Create: `tests/test_config.py`

**Interfaces:**
- Consumes: `.env` 文件或环境变量
- Produces: `Settings` 类，属性 `openai_api_key: str`, `openai_base_url: str`, `openai_model: str`, `max_iterations: int`

- [ ] **Step 1: 编写测试**

`tests/__init__.py`:
```python
```

`tests/test_config.py`:
```python
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
```

- [ ] **Step 2: 运行测试确认失败**

```bash
uv run pytest tests/test_config.py -v
```

Expected: FAIL — `ModuleNotFoundError: No module named 'my_small_agent.config'` 或 `ImportError`

- [ ] **Step 3: 实现 config.py**

`my_small_agent/config.py`:
```python
"""Application configuration loaded from environment variables and .env file."""

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Agent configuration settings."""

    openai_api_key: str
    openai_base_url: str = "https://api.openai.com/v1"
    openai_model: str = "gpt-4o"
    max_iterations: int = 10

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
    )
```

- [ ] **Step 4: 运行测试确认通过**

```bash
uv run pytest tests/test_config.py -v
```

Expected: 2 tests PASS

- [ ] **Step 5: Commit**

```bash
git add .
git commit -m "feat: add config module with pydantic-settings"
```

---

### Task 3: 工具基类与注册表

**Files:**
- Create: `my_small_agent/tools/base.py`
- Modify: `my_small_agent/tools/__init__.py` (替换占位内容)
- Create: `tests/test_tools_registry.py`

**Interfaces:**
- Consumes: 无
- Produces:
  - `Tool` 抽象基类: 属性 `name: str`, `description: str`, `parameters: dict`, `danger_level: str`; 方法 `async execute(**kwargs) -> str`
  - `ToolRegistry` 类: 方法 `register(tool: Tool) -> None`, `get(name: str) -> Tool | None`, `get_openai_tools() -> list[dict]`, `list_all() -> list[Tool]`

- [ ] **Step 1: 编写测试**

`tests/test_tools_registry.py`:
```python
"""Tests for tool base class and registry."""

import pytest

from my_small_agent.tools.base import Tool
from my_small_agent.tools import ToolRegistry


class MockTool(Tool):
    name = "mock_tool"
    description = "A mock tool for testing"
    parameters = {
        "type": "object",
        "properties": {
            "input": {"type": "string", "description": "Test input"},
        },
        "required": ["input"],
    }
    danger_level = "safe"

    async def execute(self, **kwargs) -> str:
        return f"mock result: {kwargs.get('input', '')}"


class TestToolRegistry:
    def setup_method(self):
        self.registry = ToolRegistry()
        self.tool = MockTool()

    def test_register_and_get(self):
        self.registry.register(self.tool)
        retrieved = self.registry.get("mock_tool")
        assert retrieved is self.tool

    def test_get_nonexistent_returns_none(self):
        assert self.registry.get("nonexistent") is None

    def test_list_all(self):
        self.registry.register(self.tool)
        tools = self.registry.list_all()
        assert len(tools) == 1
        assert tools[0].name == "mock_tool"

    def test_get_openai_tools_format(self):
        self.registry.register(self.tool)
        openai_tools = self.registry.get_openai_tools()
        assert len(openai_tools) == 1
        tool_def = openai_tools[0]
        assert tool_def["type"] == "function"
        assert tool_def["function"]["name"] == "mock_tool"
        assert tool_def["function"]["description"] == "A mock tool for testing"
        assert tool_def["function"]["parameters"] == self.tool.parameters

    @pytest.mark.asyncio
    async def test_tool_execute(self):
        result = await self.tool.execute(input="hello")
        assert result == "mock result: hello"
```

- [ ] **Step 2: 运行测试确认失败**

```bash
uv run pytest tests/test_tools_registry.py -v
```

Expected: FAIL — ImportError

- [ ] **Step 3: 实现 tools/base.py**

`my_small_agent/tools/base.py`:
```python
"""Abstract base class for all tools."""

from abc import ABC, abstractmethod


class Tool(ABC):
    """Base class for agent tools.

    Subclasses must define class attributes and implement execute().
    """

    name: str
    description: str
    parameters: dict
    danger_level: str  # "safe" | "dangerous"

    @abstractmethod
    async def execute(self, **kwargs) -> str:
        """Execute the tool with given arguments.

        Returns:
            A string representation of the result.
        """
```

- [ ] **Step 4: 实现 tools/__init__.py (ToolRegistry)**

`my_small_agent/tools/__init__.py`:
```python
"""Tool registry - central place to register and retrieve tools."""

from my_small_agent.tools.base import Tool


class ToolRegistry:
    """Central registry for all available tools."""

    def __init__(self) -> None:
        self._tools: dict[str, Tool] = {}

    def register(self, tool: Tool) -> None:
        """Register a tool instance by its name."""
        self._tools[tool.name] = tool

    def get(self, name: str) -> Tool | None:
        """Retrieve a tool by name, or None if not found."""
        return self._tools.get(name)

    def get_openai_tools(self) -> list[dict]:
        """Convert all registered tools to OpenAI tools format."""
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
        """Return a list of all registered tools."""
        return list(self._tools.values())
```

- [ ] **Step 5: 运行测试确认通过**

```bash
uv run pytest tests/test_tools_registry.py -v
```

Expected: 5 tests PASS

- [ ] **Step 6: Commit**

```bash
git add .
git commit -m "feat: add Tool base class and ToolRegistry"
```

---

### Task 4: 四个内置工具

**Files:**
- Create: `my_small_agent/tools/file_read.py`
- Create: `my_small_agent/tools/file_write.py`
- Create: `my_small_agent/tools/list_dir.py`
- Create: `my_small_agent/tools/shell_exec.py`
- Create: `tests/test_tools_builtin.py`

**Interfaces:**
- Consumes: `Tool` 基类
- Produces: `ReadFileTool`, `WriteFileTool`, `ListDirectoryTool`, `ExecuteShellTool` 四个工具类实例；辅助函数 `create_default_registry() -> ToolRegistry`

- [ ] **Step 1: 编写测试**

`tests/test_tools_builtin.py`:
```python
"""Tests for built-in tools."""

import os
import tempfile

import pytest

from my_small_agent.tools.file_read import ReadFileTool
from my_small_agent.tools.file_write import WriteFileTool
from my_small_agent.tools.list_dir import ListDirectoryTool
from my_small_agent.tools.shell_exec import ExecuteShellTool


class TestReadFileTool:
    def setup_method(self):
        self.tool = ReadFileTool()

    def test_metadata(self):
        assert self.tool.name == "read_file"
        assert self.tool.danger_level == "safe"

    @pytest.mark.asyncio
    async def test_read_existing_file(self, tmp_path):
        test_file = tmp_path / "test.txt"
        test_file.write_text("hello world", encoding="utf-8")
        result = await self.tool.execute(path=str(test_file))
        assert result == "hello world"

    @pytest.mark.asyncio
    async def test_read_nonexistent_file(self):
        result = await self.tool.execute(path="/nonexistent/path.txt")
        assert "Error" in result or "error" in result


class TestWriteFileTool:
    def setup_method(self):
        self.tool = WriteFileTool()

    def test_metadata(self):
        assert self.tool.name == "write_file"
        assert self.tool.danger_level == "dangerous"

    @pytest.mark.asyncio
    async def test_write_file(self, tmp_path):
        test_file = tmp_path / "output.txt"
        result = await self.tool.execute(path=str(test_file), content="written content")
        assert "success" in result.lower() or "wrote" in result.lower()
        assert test_file.read_text(encoding="utf-8") == "written content"

    @pytest.mark.asyncio
    async def test_write_creates_directories(self, tmp_path):
        test_file = tmp_path / "sub" / "dir" / "file.txt"
        result = await self.tool.execute(path=str(test_file), content="nested")
        assert test_file.exists()
        assert test_file.read_text(encoding="utf-8") == "nested"


class TestListDirectoryTool:
    def setup_method(self):
        self.tool = ListDirectoryTool()

    def test_metadata(self):
        assert self.tool.name == "list_directory"
        assert self.tool.danger_level == "safe"

    @pytest.mark.asyncio
    async def test_list_directory(self, tmp_path):
        (tmp_path / "file1.txt").write_text("a")
        (tmp_path / "file2.py").write_text("b")
        (tmp_path / "subdir").mkdir()
        result = await self.tool.execute(path=str(tmp_path))
        assert "file1.txt" in result
        assert "file2.py" in result
        assert "subdir" in result

    @pytest.mark.asyncio
    async def test_list_nonexistent_directory(self):
        result = await self.tool.execute(path="/nonexistent/dir")
        assert "Error" in result or "error" in result


class TestExecuteShellTool:
    def setup_method(self):
        self.tool = ExecuteShellTool()

    def test_metadata(self):
        assert self.tool.name == "execute_shell"
        assert self.tool.danger_level == "dangerous"

    @pytest.mark.asyncio
    async def test_execute_simple_command(self):
        result = await self.tool.execute(command="echo hello")
        assert "hello" in result

    @pytest.mark.asyncio
    async def test_execute_failing_command(self):
        result = await self.tool.execute(command="exit 1")
        assert "exit code" in result.lower() or "error" in result.lower() or "1" in result
```

- [ ] **Step 2: 运行测试确认失败**

```bash
uv run pytest tests/test_tools_builtin.py -v
```

Expected: FAIL — ImportError

- [ ] **Step 3: 实现 file_read.py**

`my_small_agent/tools/file_read.py`:
```python
"""Tool for reading file contents."""

import aiofiles

from my_small_agent.tools.base import Tool


class ReadFileTool(Tool):
    """Read the contents of a file at the given path."""

    name = "read_file"
    description = "Read the contents of a file at the specified path."
    parameters = {
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "The absolute or relative path to the file to read.",
            },
        },
        "required": ["path"],
    }
    danger_level = "safe"

    async def execute(self, **kwargs) -> str:
        path = kwargs["path"]
        try:
            with open(path, "r", encoding="utf-8") as f:
                return f.read()
        except FileNotFoundError:
            return f"Error: File not found: {path}"
        except PermissionError:
            return f"Error: Permission denied: {path}"
        except Exception as e:
            return f"Error reading file: {e}"
```

- [ ] **Step 4: 实现 file_write.py**

`my_small_agent/tools/file_write.py`:
```python
"""Tool for writing content to files."""

import os

from my_small_agent.tools.base import Tool


class WriteFileTool(Tool):
    """Write content to a file at the given path."""

    name = "write_file"
    description = "Write content to a file at the specified path. Creates directories if needed."
    parameters = {
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "The absolute or relative path to the file to write.",
            },
            "content": {
                "type": "string",
                "description": "The content to write to the file.",
            },
        },
        "required": ["path", "content"],
    }
    danger_level = "dangerous"

    async def execute(self, **kwargs) -> str:
        path = kwargs["path"]
        content = kwargs["content"]
        try:
            os.makedirs(os.path.dirname(path), exist_ok=True) if os.path.dirname(path) else None
            with open(path, "w", encoding="utf-8") as f:
                f.write(content)
            return f"Successfully wrote {len(content)} characters to {path}"
        except PermissionError:
            return f"Error: Permission denied: {path}"
        except Exception as e:
            return f"Error writing file: {e}"
```

- [ ] **Step 5: 实现 list_dir.py**

`my_small_agent/tools/list_dir.py`:
```python
"""Tool for listing directory contents."""

import os

from my_small_agent.tools.base import Tool


class ListDirectoryTool(Tool):
    """List files and subdirectories in the given path."""

    name = "list_directory"
    description = "List all files and subdirectories in the specified directory path."
    parameters = {
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "The absolute or relative path to the directory to list.",
            },
        },
        "required": ["path"],
    }
    danger_level = "safe"

    async def execute(self, **kwargs) -> str:
        path = kwargs["path"]
        try:
            entries = os.listdir(path)
            if not entries:
                return f"Directory is empty: {path}"
            result_lines = []
            for entry in sorted(entries):
                full_path = os.path.join(path, entry)
                if os.path.isdir(full_path):
                    result_lines.append(f"[DIR]  {entry}")
                else:
                    size = os.path.getsize(full_path)
                    result_lines.append(f"[FILE] {entry} ({size} bytes)")
            return "\n".join(result_lines)
        except FileNotFoundError:
            return f"Error: Directory not found: {path}"
        except PermissionError:
            return f"Error: Permission denied: {path}"
        except Exception as e:
            return f"Error listing directory: {e}"
```

- [ ] **Step 6: 实现 shell_exec.py**

`my_small_agent/tools/shell_exec.py`:
```python
"""Tool for executing shell commands."""

import asyncio

from my_small_agent.tools.base import Tool


class ExecuteShellTool(Tool):
    """Execute a shell command and return its output."""

    name = "execute_shell"
    description = "Execute a shell command and return stdout and stderr."
    parameters = {
        "type": "object",
        "properties": {
            "command": {
                "type": "string",
                "description": "The shell command to execute.",
            },
        },
        "required": ["command"],
    }
    danger_level = "dangerous"

    async def execute(self, **kwargs) -> str:
        command = kwargs["command"]
        try:
            process = await asyncio.create_subprocess_shell(
                command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await asyncio.wait_for(
                process.communicate(), timeout=30.0
            )
            output_parts = []
            if stdout:
                output_parts.append(f"STDOUT:\n{stdout.decode('utf-8', errors='replace')}")
            if stderr:
                output_parts.append(f"STDERR:\n{stderr.decode('utf-8', errors='replace')}")
            if process.returncode != 0:
                output_parts.append(f"Exit code: {process.returncode}")
            return "\n".join(output_parts) if output_parts else "(no output)"
        except asyncio.TimeoutError:
            return "Error: Command timed out after 30 seconds"
        except Exception as e:
            return f"Error executing command: {e}"
```

- [ ] **Step 7: 添加 create_default_registry 到 tools/__init__.py**

在 `my_small_agent/tools/__init__.py` 末尾追加：

```python
from my_small_agent.tools.file_read import ReadFileTool
from my_small_agent.tools.file_write import WriteFileTool
from my_small_agent.tools.list_dir import ListDirectoryTool
from my_small_agent.tools.shell_exec import ExecuteShellTool


def create_default_registry() -> ToolRegistry:
    """Create a registry with all built-in tools registered."""
    registry = ToolRegistry()
    registry.register(ReadFileTool())
    registry.register(WriteFileTool())
    registry.register(ListDirectoryTool())
    registry.register(ExecuteShellTool())
    return registry
```

- [ ] **Step 8: 运行测试确认通过**

```bash
uv run pytest tests/test_tools_builtin.py -v
```

Expected: 全部 PASS

- [ ] **Step 9: Commit**

```bash
git add .
git commit -m "feat: add 4 built-in tools (read_file, write_file, list_directory, execute_shell)"
```

---

### Task 5: LLM 客户端

**Files:**
- Create: `my_small_agent/llm.py`
- Create: `tests/test_llm.py`

**Interfaces:**
- Consumes: `Settings` (from config.py)
- Produces: `LLMClient` 类，方法 `async chat(messages: list[dict], tools: list[dict] | None = None) -> ChatCompletion`

- [ ] **Step 1: 编写测试**

`tests/test_llm.py`:
```python
"""Tests for LLM client."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from my_small_agent.config import Settings
from my_small_agent.llm import LLMClient


@pytest.fixture
def mock_settings():
    """Create mock settings for testing."""
    settings = MagicMock(spec=Settings)
    settings.openai_api_key = "sk-test"
    settings.openai_base_url = "https://api.test.com/v1"
    settings.openai_model = "gpt-4o-mini"
    return settings


class TestLLMClient:
    def test_init(self, mock_settings):
        """LLMClient should initialize with settings."""
        client = LLMClient(mock_settings)
        assert client.model == "gpt-4o-mini"

    @pytest.mark.asyncio
    async def test_chat_calls_openai(self, mock_settings):
        """chat() should call OpenAI API with correct parameters."""
        client = LLMClient(mock_settings)
        mock_response = MagicMock()
        client.client.chat.completions.create = AsyncMock(return_value=mock_response)

        messages = [{"role": "user", "content": "hello"}]
        tools = [{"type": "function", "function": {"name": "test", "parameters": {}}}]

        result = await client.chat(messages, tools=tools)

        client.client.chat.completions.create.assert_called_once_with(
            model="gpt-4o-mini",
            messages=messages,
            tools=tools,
        )
        assert result is mock_response

    @pytest.mark.asyncio
    async def test_chat_without_tools(self, mock_settings):
        """chat() without tools should not pass tools parameter."""
        client = LLMClient(mock_settings)
        mock_response = MagicMock()
        client.client.chat.completions.create = AsyncMock(return_value=mock_response)

        messages = [{"role": "user", "content": "hello"}]
        result = await client.chat(messages)

        client.client.chat.completions.create.assert_called_once_with(
            model="gpt-4o-mini",
            messages=messages,
        )
```

- [ ] **Step 2: 运行测试确认失败**

```bash
uv run pytest tests/test_llm.py -v
```

Expected: FAIL — ImportError

- [ ] **Step 3: 实现 llm.py**

`my_small_agent/llm.py`:
```python
"""OpenAI-compatible LLM client wrapper."""

from openai import AsyncOpenAI
from openai.types.chat import ChatCompletion

from my_small_agent.config import Settings


class LLMClient:
    """Async wrapper around OpenAI chat completions API."""

    def __init__(self, settings: Settings) -> None:
        self.client = AsyncOpenAI(
            api_key=settings.openai_api_key,
            base_url=settings.openai_base_url,
        )
        self.model = settings.openai_model

    async def chat(
        self,
        messages: list[dict],
        tools: list[dict] | None = None,
    ) -> ChatCompletion:
        """Send messages to the LLM and get a response.

        Args:
            messages: Conversation history in OpenAI message format.
            tools: Optional list of tool definitions in OpenAI format.

        Returns:
            The complete chat response.
        """
        kwargs: dict = {
            "model": self.model,
            "messages": messages,
        }
        if tools:
            kwargs["tools"] = tools

        return await self.client.chat.completions.create(**kwargs)
```

- [ ] **Step 4: 运行测试确认通过**

```bash
uv run pytest tests/test_llm.py -v
```

Expected: 3 tests PASS

- [ ] **Step 5: Commit**

```bash
git add .
git commit -m "feat: add async LLM client wrapper"
```

---

### Task 6: Agent 对话循环核心

**Files:**
- Create: `my_small_agent/agent.py`
- Create: `tests/test_agent.py`

**Interfaces:**
- Consumes: `LLMClient`, `ToolRegistry`, `Settings`
- Produces: `Agent` 类，方法:
  - `async run_turn(user_input: str, confirm_callback) -> str` — 执行一轮对话，返回最终文本回复
  - `clear_history() -> None` — 清空历史（保留 system prompt）
  - 属性 `messages: list[dict]` — 当前对话历史

- [ ] **Step 1: 编写测试**

`tests/test_agent.py`:
```python
"""Tests for agent conversation loop."""

import json
from unittest.mock import AsyncMock, MagicMock

import pytest

from my_small_agent.agent import Agent
from my_small_agent.config import Settings
from my_small_agent.llm import LLMClient
from my_small_agent.tools import ToolRegistry
from my_small_agent.tools.base import Tool


class MockSafeTool(Tool):
    name = "safe_tool"
    description = "A safe mock tool"
    parameters = {"type": "object", "properties": {"x": {"type": "string"}}, "required": ["x"]}
    danger_level = "safe"

    async def execute(self, **kwargs) -> str:
        return f"safe result: {kwargs['x']}"


class MockDangerousTool(Tool):
    name = "danger_tool"
    description = "A dangerous mock tool"
    parameters = {"type": "object", "properties": {"cmd": {"type": "string"}}, "required": ["cmd"]}
    danger_level = "dangerous"

    async def execute(self, **kwargs) -> str:
        return f"executed: {kwargs['cmd']}"


def make_text_response(content: str):
    """Create a mock ChatCompletion with text response."""
    message = MagicMock()
    message.content = content
    message.tool_calls = None
    choice = MagicMock()
    choice.message = message
    response = MagicMock()
    response.choices = [choice]
    return response


def make_tool_call_response(tool_name: str, arguments: dict):
    """Create a mock ChatCompletion with a single tool call."""
    tool_call = MagicMock()
    tool_call.id = "call_123"
    tool_call.function.name = tool_name
    tool_call.function.arguments = json.dumps(arguments)

    message = MagicMock()
    message.content = None
    message.tool_calls = [tool_call]
    # Make message serializable for history
    message.model_dump.return_value = {
        "role": "assistant",
        "content": None,
        "tool_calls": [
            {
                "id": "call_123",
                "type": "function",
                "function": {"name": tool_name, "arguments": json.dumps(arguments)},
            }
        ],
    }

    choice = MagicMock()
    choice.message = message
    response = MagicMock()
    response.choices = [choice]
    return response


@pytest.fixture
def mock_settings():
    settings = MagicMock(spec=Settings)
    settings.max_iterations = 10
    return settings


@pytest.fixture
def registry():
    reg = ToolRegistry()
    reg.register(MockSafeTool())
    reg.register(MockDangerousTool())
    return reg


class TestAgent:
    @pytest.mark.asyncio
    async def test_simple_text_response(self, mock_settings, registry):
        """Agent should return text when LLM responds with text."""
        llm = MagicMock(spec=LLMClient)
        llm.chat = AsyncMock(return_value=make_text_response("Hello!"))

        agent = Agent(llm, registry, mock_settings)
        result = await agent.run_turn("Hi", confirm_callback=AsyncMock(return_value=True))
        assert result == "Hello!"

    @pytest.mark.asyncio
    async def test_safe_tool_auto_executes(self, mock_settings, registry):
        """Safe tools should execute without confirmation."""
        llm = MagicMock(spec=LLMClient)
        llm.chat = AsyncMock(
            side_effect=[
                make_tool_call_response("safe_tool", {"x": "test"}),
                make_text_response("Done! Result was: safe result: test"),
            ]
        )

        agent = Agent(llm, registry, mock_settings)
        confirm = AsyncMock(return_value=True)
        result = await agent.run_turn("Use the safe tool", confirm_callback=confirm)

        confirm.assert_not_called()  # safe tool should not ask
        assert "Done!" in result

    @pytest.mark.asyncio
    async def test_dangerous_tool_requires_confirmation(self, mock_settings, registry):
        """Dangerous tools should call confirm_callback before executing."""
        llm = MagicMock(spec=LLMClient)
        llm.chat = AsyncMock(
            side_effect=[
                make_tool_call_response("danger_tool", {"cmd": "rm -rf /"}),
                make_text_response("Executed."),
            ]
        )

        agent = Agent(llm, registry, mock_settings)
        confirm = AsyncMock(return_value=True)
        result = await agent.run_turn("Run danger", confirm_callback=confirm)

        confirm.assert_called_once()

    @pytest.mark.asyncio
    async def test_dangerous_tool_rejected(self, mock_settings, registry):
        """When user rejects dangerous tool, agent should report rejection."""
        llm = MagicMock(spec=LLMClient)
        llm.chat = AsyncMock(
            side_effect=[
                make_tool_call_response("danger_tool", {"cmd": "rm -rf /"}),
                make_text_response("OK, I won't do that."),
            ]
        )

        agent = Agent(llm, registry, mock_settings)
        confirm = AsyncMock(return_value=False)
        result = await agent.run_turn("Run danger", confirm_callback=confirm)
        assert "won't" in result.lower() or "ok" in result.lower()

    @pytest.mark.asyncio
    async def test_clear_history(self, mock_settings, registry):
        """clear_history should reset messages but keep system prompt."""
        llm = MagicMock(spec=LLMClient)
        llm.chat = AsyncMock(return_value=make_text_response("Hi"))

        agent = Agent(llm, registry, mock_settings)
        await agent.run_turn("Hello", confirm_callback=AsyncMock())

        assert len(agent.messages) > 1
        agent.clear_history()
        assert len(agent.messages) == 1
        assert agent.messages[0]["role"] == "system"

    @pytest.mark.asyncio
    async def test_max_iterations_stops_loop(self, mock_settings, registry):
        """Agent should stop after max_iterations to prevent infinite loops."""
        mock_settings.max_iterations = 2
        llm = MagicMock(spec=LLMClient)
        # Always return tool calls — should stop after 2
        llm.chat = AsyncMock(
            return_value=make_tool_call_response("safe_tool", {"x": "loop"})
        )

        agent = Agent(llm, registry, mock_settings)
        result = await agent.run_turn("loop forever", confirm_callback=AsyncMock())
        assert "max" in result.lower() or "迭代" in result or "limit" in result.lower()
```

- [ ] **Step 2: 运行测试确认失败**

```bash
uv run pytest tests/test_agent.py -v
```

Expected: FAIL — ImportError

- [ ] **Step 3: 实现 agent.py**

`my_small_agent/agent.py`:
```python
"""Agent core - manages the conversation loop with tool calling."""

import json
from typing import Any, Callable, Coroutine

from my_small_agent.config import Settings
from my_small_agent.llm import LLMClient
from my_small_agent.tools import ToolRegistry

# Type for the confirmation callback
ConfirmCallback = Callable[[str, str, dict], Coroutine[Any, Any, bool]]

SYSTEM_PROMPT = """You are a helpful assistant with access to tools for file operations and shell commands. Use the available tools when needed to help the user accomplish their tasks."""


class Agent:
    """Core agent that manages conversation loop and tool execution."""

    def __init__(
        self,
        llm: LLMClient,
        registry: ToolRegistry,
        settings: Settings,
    ) -> None:
        self.llm = llm
        self.registry = registry
        self.max_iterations = settings.max_iterations
        self.messages: list[dict] = [
            {"role": "system", "content": SYSTEM_PROMPT}
        ]

    async def run_turn(
        self,
        user_input: str,
        confirm_callback: ConfirmCallback,
    ) -> str:
        """Run a single conversation turn, potentially with multiple tool calls.

        Args:
            user_input: The user's message text.
            confirm_callback: Async function called for dangerous tools.
                Signature: (tool_name, description, arguments) -> bool

        Returns:
            The final text response from the LLM.
        """
        self.messages.append({"role": "user", "content": user_input})

        tools = self.registry.get_openai_tools()
        iteration = 0

        while iteration < self.max_iterations:
            iteration += 1

            response = await self.llm.chat(
                messages=self.messages,
                tools=tools if tools else None,
            )

            message = response.choices[0].message

            # If no tool calls, we have our final answer
            if not message.tool_calls:
                content = message.content or ""
                self.messages.append({"role": "assistant", "content": content})
                return content

            # Process tool calls
            # Add assistant message with tool calls to history
            self.messages.append(message.model_dump())

            for tool_call in message.tool_calls:
                tool_name = tool_call.function.name
                arguments = json.loads(tool_call.function.arguments)

                tool = self.registry.get(tool_name)
                if tool is None:
                    result = f"Error: Unknown tool '{tool_name}'"
                else:
                    # Check danger level
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

                # Add tool result to history
                self.messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": tool_call.id,
                        "content": result,
                    }
                )

        return "Reached maximum iteration limit. Please try a simpler request."

    async def _execute_tool(self, tool: Any, arguments: dict) -> str:
        """Execute a tool and handle any exceptions."""
        try:
            return await tool.execute(**arguments)
        except Exception as e:
            return f"Error executing {tool.name}: {e}"

    def clear_history(self) -> None:
        """Clear conversation history, keeping only the system prompt."""
        self.messages = [self.messages[0]]
```

- [ ] **Step 4: 运行测试确认通过**

```bash
uv run pytest tests/test_agent.py -v
```

Expected: 6 tests PASS

- [ ] **Step 5: Commit**

```bash
git add .
git commit -m "feat: add agent conversation loop with tool calling"
```

---

### Task 7: CLI 交互层

**Files:**
- Create: `my_small_agent/cli.py`
- Modify: `my_small_agent/__main__.py` (连接所有组件)

**Interfaces:**
- Consumes: `Agent`, `Settings`
- Produces: `CLI` 类，方法 `async run() -> None` — 启动交互式 REPL

- [ ] **Step 1: 实现 cli.py**

`my_small_agent/cli.py`:
```python
"""CLI interaction layer - handles user input/output and slash commands."""

import sys

from prompt_toolkit import PromptSession
from prompt_toolkit.patch_stdout import patch_stdout
from rich.console import Console
from rich.markdown import Markdown
from rich.panel import Panel
from rich.status import Status

from my_small_agent.agent import Agent


class CLI:
    """Terminal-based user interface for the agent."""

    def __init__(self, agent: Agent) -> None:
        self.agent = agent
        self.console = Console()
        self.session: PromptSession = PromptSession()
        self._running = True

    async def run(self) -> None:
        """Start the interactive REPL loop."""
        self._print_welcome()

        while self._running:
            try:
                with patch_stdout():
                    user_input = await self.session.prompt_async("You> ")

                user_input = user_input.strip()
                if not user_input:
                    continue

                # Check for slash commands
                if user_input.startswith("/"):
                    await self._handle_command(user_input)
                    continue

                # Run agent turn
                await self._run_agent_turn(user_input)

            except (KeyboardInterrupt, EOFError):
                self._running = False
                self.console.print("\n[dim]Goodbye![/dim]")

    async def _run_agent_turn(self, user_input: str) -> None:
        """Execute an agent turn with loading indicator."""
        with Status("[bold cyan]Thinking...", console=self.console):
            response = await self.agent.run_turn(
                user_input,
                confirm_callback=self._confirm_dangerous_action,
            )

        self.console.print()
        self.console.print(Markdown(response))
        self.console.print()

    async def _confirm_dangerous_action(
        self, tool_name: str, description: str, arguments: dict
    ) -> bool:
        """Ask user to confirm a dangerous tool execution."""
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
        """Process slash commands."""
        cmd = command.lower().split()[0]

        if cmd == "/help":
            self._print_help()
        elif cmd == "/clear":
            self.agent.clear_history()
            self.console.print("[green]Conversation history cleared.[/green]")
        elif cmd == "/exit":
            self._running = False
            self.console.print("[dim]Goodbye![/dim]")
        else:
            self.console.print(f"[red]Unknown command: {cmd}[/red]. Type /help for available commands.")

    def _print_welcome(self) -> None:
        """Print welcome message on startup."""
        self.console.print(
            Panel(
                "[bold]MySmallAgent[/bold] - Your CLI assistant\n\n"
                "Type your message to chat, or use commands:\n"
                "  /help  - Show help\n"
                "  /clear - Clear history\n"
                "  /exit  - Exit",
                title="Welcome",
                border_style="blue",
            )
        )
        self.console.print()

    def _print_help(self) -> None:
        """Print help information."""
        self.console.print(
            Panel(
                "[bold]Available Commands:[/bold]\n\n"
                "  [cyan]/help[/cyan]   - Show this help message\n"
                "  [cyan]/clear[/cyan]  - Clear conversation history\n"
                "  [cyan]/exit[/cyan]   - Exit the program\n\n"
                "[bold]Tips:[/bold]\n"
                "  • Press Ctrl+C or Ctrl+D to exit\n"
                "  • The agent can read/write files, list directories, and run shell commands",
                title="Help",
                border_style="green",
            )
        )
```

- [ ] **Step 2: 更新 __main__.py 连接所有组件**

`my_small_agent/__main__.py`:
```python
"""Entry point for python -m my_small_agent."""

import asyncio
import sys

from rich.console import Console


async def main() -> None:
    """Initialize and run the agent CLI."""
    console = Console()

    try:
        from my_small_agent.config import Settings
        from my_small_agent.llm import LLMClient
        from my_small_agent.tools import create_default_registry
        from my_small_agent.agent import Agent
        from my_small_agent.cli import CLI

        settings = Settings()
        llm_client = LLMClient(settings)
        registry = create_default_registry()
        agent = Agent(llm_client, registry, settings)
        cli = CLI(agent)
        await cli.run()

    except KeyboardInterrupt:
        console.print("\n[dim]Goodbye![/dim]")
    except Exception as e:
        console.print(f"[red]Failed to start: {e}[/red]")
        console.print("[dim]Make sure your .env file is configured correctly.[/dim]")
        sys.exit(1)


def main_entry() -> None:
    """Sync entry point for pyproject.toml scripts."""
    asyncio.run(main())


if __name__ == "__main__":
    main_entry()
```

- [ ] **Step 3: 手动验证启动（需要 .env 配置）**

```bash
# 先创建 .env（填入真实 key 后）
cp .env.example .env
# 编辑 .env 填入 API key
uv run python -m my_small_agent
```

Expected: 显示 Welcome 面板，等待用户输入。输入 `/help` 显示帮助，`/exit` 退出。

- [ ] **Step 4: Commit**

```bash
git add .
git commit -m "feat: add CLI interaction layer and wire up entry point"
```

---

### Task 8: 集成烟雾测试

**Files:**
- Create: `tests/test_integration.py`

**Interfaces:**
- Consumes: 所有模块
- Produces: 确认端到端流程正确的集成测试

- [ ] **Step 1: 编写集成测试**

`tests/test_integration.py`:
```python
"""Integration tests - verify all components work together."""

import json
import os
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from my_small_agent.agent import Agent
from my_small_agent.config import Settings
from my_small_agent.llm import LLMClient
from my_small_agent.tools import ToolRegistry, create_default_registry


def make_text_response(content: str):
    message = MagicMock()
    message.content = content
    message.tool_calls = None
    choice = MagicMock()
    choice.message = message
    response = MagicMock()
    response.choices = [choice]
    return response


def make_tool_call_response(tool_name: str, arguments: dict, call_id: str = "call_1"):
    tool_call = MagicMock()
    tool_call.id = call_id
    tool_call.function.name = tool_name
    tool_call.function.arguments = json.dumps(arguments)
    message = MagicMock()
    message.content = None
    message.tool_calls = [tool_call]
    message.model_dump.return_value = {
        "role": "assistant",
        "content": None,
        "tool_calls": [
            {
                "id": call_id,
                "type": "function",
                "function": {"name": tool_name, "arguments": json.dumps(arguments)},
            }
        ],
    }
    choice = MagicMock()
    choice.message = message
    response = MagicMock()
    response.choices = [choice]
    return response


@pytest.fixture
def settings():
    env = {"OPENAI_API_KEY": "sk-test", "MAX_ITERATIONS": "5"}
    with patch.dict(os.environ, env):
        return Settings(_env_file=None)


@pytest.fixture
def registry():
    return create_default_registry()


class TestIntegration:
    @pytest.mark.asyncio
    async def test_agent_reads_file(self, settings, registry, tmp_path):
        """Agent should be able to read a file via tool call."""
        test_file = tmp_path / "hello.txt"
        test_file.write_text("Hello from file!")

        llm = MagicMock(spec=LLMClient)
        llm.chat = AsyncMock(
            side_effect=[
                make_tool_call_response("read_file", {"path": str(test_file)}),
                make_text_response("The file contains: Hello from file!"),
            ]
        )

        agent = Agent(llm, registry, settings)
        result = await agent.run_turn(
            "Read hello.txt", confirm_callback=AsyncMock(return_value=True)
        )
        assert "Hello from file!" in result

    @pytest.mark.asyncio
    async def test_agent_writes_file_with_confirmation(self, settings, registry, tmp_path):
        """Agent should ask confirmation before writing file."""
        output_file = tmp_path / "output.txt"

        llm = MagicMock(spec=LLMClient)
        llm.chat = AsyncMock(
            side_effect=[
                make_tool_call_response(
                    "write_file",
                    {"path": str(output_file), "content": "new content"},
                ),
                make_text_response("File written successfully."),
            ]
        )

        confirm = AsyncMock(return_value=True)
        agent = Agent(llm, registry, settings)
        result = await agent.run_turn("Write to output.txt", confirm_callback=confirm)

        confirm.assert_called_once()
        assert output_file.read_text() == "new content"

    @pytest.mark.asyncio
    async def test_registry_has_all_tools(self, registry):
        """Default registry should have all 4 built-in tools."""
        tools = registry.list_all()
        names = {t.name for t in tools}
        assert names == {"read_file", "write_file", "list_directory", "execute_shell"}

    @pytest.mark.asyncio
    async def test_openai_tools_format_valid(self, registry):
        """OpenAI tools format should be valid for API calls."""
        openai_tools = registry.get_openai_tools()
        assert len(openai_tools) == 4
        for tool_def in openai_tools:
            assert tool_def["type"] == "function"
            assert "name" in tool_def["function"]
            assert "description" in tool_def["function"]
            assert "parameters" in tool_def["function"]
```

- [ ] **Step 2: 运行全部测试**

```bash
uv run pytest -v
```

Expected: 所有测试 PASS

- [ ] **Step 3: Commit**

```bash
git add .
git commit -m "test: add integration smoke tests"
```

---

## Summary

| Task | 描述 | 产出 |
|------|------|------|
| 1 | 项目脚手架 | pyproject.toml, 包结构, uv 可用 |
| 2 | 配置管理 | Settings 类 + 测试 |
| 3 | 工具基类与注册表 | Tool ABC + ToolRegistry + 测试 |
| 4 | 四个内置工具 | 4 个工具实现 + create_default_registry + 测试 |
| 5 | LLM 客户端 | LLMClient 异步封装 + 测试 |
| 6 | Agent 对话循环 | Agent 核心循环 + 测试 |
| 7 | CLI 交互层 | CLI REPL + 入口点 |
| 8 | 集成测试 | 端到端烟雾测试 |
