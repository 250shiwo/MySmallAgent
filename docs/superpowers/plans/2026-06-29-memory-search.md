# 长期记忆与会话搜索 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add persistent long-term memory (`memory_save` tool) and session keyword search (`session_search` tool) to MySmallAgent, with automatic memory injection as a second system message at startup.

**Architecture:** New `memory.py` module handles all memory file I/O (mirrors `session.py` pattern). Two new tools in `tools/` call into `memory.py` and scan session files. `Agent.__init__` accepts an optional `MemoryManager` and injects loaded memories as a second system message. `reset_session()` is updated to preserve all system messages.

**Tech Stack:** Python stdlib only (`json`, `os`, `secrets`, `tempfile`, `pathlib`, `datetime`). Tests use `pytest` + `tmp_path`. Run with `uv run pytest`.

## Global Constraints

- Memory file at `.genesis/memory/memory.json` relative to CWD
- Memory entry ID format: `"mem_"` + 8 lowercase hex chars (e.g. `mem_a3f8b2c1`), generated via `secrets.token_hex(4)`
- Memory timestamps: UTC ISO 8601, `datetime.now(timezone.utc).isoformat()`
- `memory_save` `danger_level = "safe"` (LLM autonomous, no user confirmation)
- `session_search` `danger_level = "safe"`
- Memory loaded once at `Agent.__init__`, never updated mid-session (preserves prompt cache)
- `create_default_registry` new params are **optional** (None → don't register those tools), backward-compatible with existing tests
- `reset_session()` must preserve ALL `role=system` messages, not just `messages[0]`
- `load_memory_text()` returns `""` (empty string) when file missing, JSON corrupt, or zero entries
- Run tests: `uv run pytest tests/ -v`

---

### Task 1: MemoryManager 持久化核心模块

**Files:**
- Create: `my_small_agent/memory.py`
- Create: `tests/test_memory.py`

**Interfaces:**
- Produces:
  - `class MemoryManager(memory_dir: Path)`
  - `MemoryManager.save_entry(content: str) -> str` — creates new entry, returns `"mem_xxxxxxxx"` id
  - `MemoryManager.load_memory_text() -> str` — returns `"• content\n• content"` format or `""`

- [ ] **Step 1: 编写失败测试**

创建 `tests/test_memory.py`：

```python
"""MemoryManager 持久化模块的测试套件。"""

import json
from pathlib import Path

import pytest

from my_small_agent.memory import MemoryManager


def test_save_entry_creates_file(tmp_path):
    """save_entry() 应创建 memory.json 文件。"""
    mm = MemoryManager(tmp_path)
    mm.save_entry("I prefer dark mode")
    assert (tmp_path / "memory.json").exists()


def test_save_entry_content_is_correct(tmp_path):
    """save_entry() 写入的内容应与参数一致。"""
    mm = MemoryManager(tmp_path)
    mm.save_entry("I prefer dark mode")
    data = json.loads((tmp_path / "memory.json").read_text(encoding="utf-8"))
    assert len(data["entries"]) == 1
    assert data["entries"][0]["content"] == "I prefer dark mode"
    assert "created_at" in data["entries"][0]


def test_save_entry_no_tmp_file_left(tmp_path):
    """原子写后不应留下 .tmp 临时文件。"""
    mm = MemoryManager(tmp_path)
    mm.save_entry("test")
    assert list(tmp_path.glob("*.tmp")) == []


def test_save_entry_creates_directory(tmp_path):
    """save_entry() 应自动创建不存在的目录。"""
    nested = tmp_path / "a" / "b"
    mm = MemoryManager(nested)
    mm.save_entry("test")
    assert nested.exists()


def test_save_entry_appends_to_existing(tmp_path):
    """save_entry() 多次调用应追加条目，不覆盖。"""
    mm = MemoryManager(tmp_path)
    mm.save_entry("first")
    mm.save_entry("second")
    data = json.loads((tmp_path / "memory.json").read_text(encoding="utf-8"))
    assert len(data["entries"]) == 2
    assert data["entries"][0]["content"] == "first"
    assert data["entries"][1]["content"] == "second"


def test_save_entry_returns_mem_id(tmp_path):
    """save_entry() 应返回以 'mem_' 开头、共 12 字符的 ID。"""
    mm = MemoryManager(tmp_path)
    entry_id = mm.save_entry("test")
    assert entry_id.startswith("mem_")
    assert len(entry_id) == 12  # "mem_"(4) + 8 hex chars


def test_save_entry_ids_are_unique(tmp_path):
    """连续调用 save_entry() 应生成不同的 ID。"""
    mm = MemoryManager(tmp_path)
    id1 = mm.save_entry("first")
    id2 = mm.save_entry("second")
    assert id1 != id2


def test_load_memory_text_file_not_exists(tmp_path):
    """load_memory_text() 文件不存在时应返回 ''。"""
    mm = MemoryManager(tmp_path)
    assert mm.load_memory_text() == ""


def test_load_memory_text_corrupt_json(tmp_path):
    """load_memory_text() JSON 损坏时应返回 ''，不崩溃。"""
    (tmp_path / "memory.json").write_text("not valid json", encoding="utf-8")
    mm = MemoryManager(tmp_path)
    assert mm.load_memory_text() == ""


def test_load_memory_text_empty_entries(tmp_path):
    """load_memory_text() entries 为空时应返回 ''。"""
    (tmp_path / "memory.json").write_text('{"entries": []}', encoding="utf-8")
    mm = MemoryManager(tmp_path)
    assert mm.load_memory_text() == ""


def test_load_memory_text_formats_entries(tmp_path):
    """load_memory_text() 有条目时应返回以 '• ' 开头的每行格式。"""
    mm = MemoryManager(tmp_path)
    mm.save_entry("I prefer Python")
    mm.save_entry("Use uv run pytest")
    text = mm.load_memory_text()
    assert "• I prefer Python" in text
    assert "• Use uv run pytest" in text
```

- [ ] **Step 2: 运行测试，确认失败**

```
uv run pytest tests/test_memory.py -v
```

期望：`ImportError: No module named 'my_small_agent.memory'`

- [ ] **Step 3: 实现 memory.py**

创建 `my_small_agent/memory.py`：

```python
"""
长期记忆持久化模块 - 负责跨会话记忆的读写。

设计思路：
  - 记忆只在会话启动时加载一次（保障 prompt 缓存命中）
  - 记忆保存使用原子写（.tmp → os.replace()），防止崩溃数据丢失
  - MemoryManager 与 SessionManager 保持相同的设计风格
"""

import json
import os
import secrets
import tempfile
from datetime import datetime, timezone
from pathlib import Path


class MemoryManager:
    """
    长期记忆管理器。

    职责：
      - save_entry():       原子写新记忆条目到 memory.json
      - load_memory_text(): 加载所有条目并格式化为注入文本
    """

    def __init__(self, memory_dir: Path) -> None:
        # 记忆文件存储目录
        self._dir = memory_dir
        self._file = memory_dir / "memory.json"

    def save_entry(self, content: str) -> str:
        """
        创建新记忆条目并原子写入 memory.json。

        返回生成的条目 ID（格式：'mem_' + 8 位十六进制）。
        """
        self._dir.mkdir(parents=True, exist_ok=True)

        # 加载现有数据（文件不存在或损坏时从空列表开始）
        try:
            data = json.loads(self._file.read_text(encoding="utf-8"))
        except (FileNotFoundError, ValueError):
            data = {"entries": []}

        # 生成唯一 ID：mem_ + 8 位随机十六进制（4 字节 = 8 hex chars）
        entry_id = "mem_" + secrets.token_hex(4)
        entry = {
            "id": entry_id,
            "content": content,
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        data["entries"].append(entry)

        # 原子写：先写临时文件，再 os.replace()
        fd, tmp_path = tempfile.mkstemp(dir=self._dir, suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            os.replace(tmp_path, self._file)
        except Exception:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
            raise

        return entry_id

    def load_memory_text(self) -> str:
        """
        加载所有记忆条目并格式化为注入文本。

        每条记忆占一行，格式：'• content'
        文件不存在、JSON 损坏、或无条目时返回空字符串。
        """
        try:
            data = json.loads(self._file.read_text(encoding="utf-8"))
            entries = data.get("entries", [])
        except (FileNotFoundError, ValueError):
            return ""

        if not entries:
            return ""

        lines = [f"• {e['content']}" for e in entries if e.get("content")]
        return "\n".join(lines)
```

- [ ] **Step 4: 运行测试，确认全部通过**

```
uv run pytest tests/test_memory.py -v
```

期望：11 个测试全部 PASS

- [ ] **Step 5: Commit**

```
git add my_small_agent/memory.py tests/test_memory.py
git commit -m "feat: add MemoryManager with atomic write and formatted load"
```

---

### Task 2: memory_save 和 session_search 工具 + 注册表扩展

**Files:**
- Create: `my_small_agent/tools/memory_save.py`
- Create: `my_small_agent/tools/session_search.py`
- Create: `tests/test_tools_memory_search.py`
- Modify: `my_small_agent/tools/__init__.py`

**Interfaces:**
- Consumes（来自 Task 1）:
  - `MemoryManager(memory_dir: Path)`
  - `MemoryManager.save_entry(content: str) -> str`
- Produces:
  - `class MemorySaveTool(memory_manager: MemoryManager)` — `name="memory_save"`, `danger_level="safe"`
  - `class SessionSearchTool(sessions_dir: Path)` — `name="session_search"`, `danger_level="safe"`
  - `create_default_registry(settings, memory_manager=None, sessions_dir=None) -> ToolRegistry` — 新签名（向后兼容）

- [ ] **Step 1: 编写失败测试**

创建 `tests/test_tools_memory_search.py`：

```python
"""memory_save 和 session_search 工具的测试套件。"""

import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from my_small_agent.tools.memory_save import MemorySaveTool
from my_small_agent.tools.session_search import SessionSearchTool


# ---- memory_save 测试 ----

@pytest.mark.asyncio
async def test_memory_save_calls_manager_and_returns_id():
    """memory_save 应调用 MemoryManager 并返回成功消息。"""
    mm = MagicMock()
    mm.save_entry.return_value = "mem_abc12345"
    tool = MemorySaveTool(mm)
    result = await tool.execute(content="test content")
    mm.save_entry.assert_called_once_with("test content")
    assert result == "Memory saved: mem_abc12345"


@pytest.mark.asyncio
async def test_memory_save_handles_exception():
    """memory_save 出错时应返回错误字符串，不抛异常。"""
    mm = MagicMock()
    mm.save_entry.side_effect = Exception("disk full")
    tool = MemorySaveTool(mm)
    result = await tool.execute(content="test")
    assert "Error saving memory" in result


def test_memory_save_metadata():
    """memory_save 应有正确的 name 和 danger_level。"""
    mm = MagicMock()
    tool = MemorySaveTool(mm)
    assert tool.name == "memory_save"
    assert tool.danger_level == "safe"


# ---- session_search 测试 ----

@pytest.mark.asyncio
async def test_session_search_no_sessions_dir(tmp_path):
    """sessions_dir 不存在时应返回固定提示。"""
    tool = SessionSearchTool(tmp_path / "nonexistent")
    result = await tool.execute(query="hello")
    assert result == "No session history found."


@pytest.mark.asyncio
async def test_session_search_keyword_match(tmp_path):
    """关键词匹配应返回正确格式的结果。"""
    sessions_dir = tmp_path / "sessions"
    sessions_dir.mkdir()
    session_data = {
        "session_id": "abc12345-full",
        "created_at": "2026-06-29T10:00:00+00:00",
        "updated_at": "2026-06-29T10:05:00+00:00",
        "title": "Test",
        "messages": [
            {"role": "user", "content": "I need help with Python scripting"},
        ],
    }
    (sessions_dir / "abc12345-full.json").write_text(
        json.dumps(session_data), encoding="utf-8"
    )
    tool = SessionSearchTool(sessions_dir)
    result = await tool.execute(query="Python")
    assert "abc12345" in result
    assert "Python" in result
    assert "user" in result


@pytest.mark.asyncio
async def test_session_search_case_insensitive(tmp_path):
    """关键词匹配应不区分大小写。"""
    sessions_dir = tmp_path / "sessions"
    sessions_dir.mkdir()
    session_data = {
        "session_id": "xyz99",
        "created_at": "2026-06-29T10:00:00+00:00",
        "updated_at": "2026-06-29T10:05:00+00:00",
        "title": "T",
        "messages": [
            {"role": "user", "content": "I like DARK MODE themes"},
        ],
    }
    (sessions_dir / "xyz99.json").write_text(
        json.dumps(session_data), encoding="utf-8"
    )
    tool = SessionSearchTool(sessions_dir)
    result = await tool.execute(query="dark mode")  # 小写查大写
    assert "DARK MODE" in result


@pytest.mark.asyncio
async def test_session_search_no_match(tmp_path):
    """无匹配时应返回固定提示。"""
    sessions_dir = tmp_path / "sessions"
    sessions_dir.mkdir()
    tool = SessionSearchTool(sessions_dir)
    result = await tool.execute(query="xyz_impossible_99")
    assert "No results found for:" in result


@pytest.mark.asyncio
async def test_session_search_respects_max_results(tmp_path):
    """max_results 应限制返回结果数量。"""
    sessions_dir = tmp_path / "sessions"
    sessions_dir.mkdir()
    session_data = {
        "session_id": "aaa111",
        "created_at": "2026-06-29T10:00:00+00:00",
        "updated_at": "2026-06-29T10:05:00+00:00",
        "title": "T",
        "messages": [
            {"role": "user", "content": f"match keyword {i}"} for i in range(10)
        ],
    }
    (sessions_dir / "aaa111.json").write_text(
        json.dumps(session_data), encoding="utf-8"
    )
    tool = SessionSearchTool(sessions_dir)
    result = await tool.execute(query="match", max_results=3)
    # 3 条结果最多有 2 个换行
    lines = [l for l in result.strip().split("\n") if l.strip()]
    assert len(lines) <= 3


def test_session_search_metadata():
    """session_search 应有正确的 name 和 danger_level。"""
    tool = SessionSearchTool(Path("/tmp"))
    assert tool.name == "session_search"
    assert tool.danger_level == "safe"
```

- [ ] **Step 2: 运行测试，确认失败**

```
uv run pytest tests/test_tools_memory_search.py -v
```

期望：`ImportError: No module named 'my_small_agent.tools.memory_save'`

- [ ] **Step 3: 实现 tools/memory_save.py**

创建 `my_small_agent/tools/memory_save.py`：

```python
"""
长期记忆保存工具 - LLM 自主调用以持久化重要信息。

安全级别：safe（LLM 自主决策，无需用户确认）

记忆在当前会话中不立即生效（保障 prompt 缓存命中），
新记忆将在下次启动时通过 system 消息注入。
"""

from my_small_agent.memory import MemoryManager
from my_small_agent.tools.base import Tool


class MemorySaveTool(Tool):
    """将重要信息持久化到跨会话的长期记忆中。"""

    name = "memory_save"
    description = (
        "Save important information to long-term memory that persists across sessions. "
        "Use for: user preferences, environment details, tool behaviors, stable conventions. "
        "Do NOT save: task progress, session results, or temporary state "
        "(use session_search to recall those)."
    )
    parameters = {
        "type": "object",
        "properties": {
            "content": {
                "type": "string",
                "description": "The information to remember persistently across sessions.",
            }
        },
        "required": ["content"],
    }
    danger_level = "safe"

    def __init__(self, memory_manager: MemoryManager) -> None:
        self._memory_manager = memory_manager

    async def execute(self, **kwargs) -> str:
        """保存记忆条目，返回保存结果。"""
        content = kwargs["content"]
        try:
            entry_id = self._memory_manager.save_entry(content)
            return f"Memory saved: {entry_id}"
        except Exception as e:
            return f"Error saving memory: {e}"
```

- [ ] **Step 4: 实现 tools/session_search.py**

创建 `my_small_agent/tools/session_search.py`：

```python
"""
会话历史搜索工具 - 通过关键词搜索过去的对话记录。

安全级别：safe（只读操作，自动执行）

搜索逻辑：遍历 .genesis/sessions/ 下所有 .json 文件，
对每条消息的 content 做大小写不敏感关键词匹配，
返回匹配消息的摘要（含 session_id 前缀和时间戳）。
"""

import json
from pathlib import Path

from my_small_agent.tools.base import Tool


class SessionSearchTool(Tool):
    """通过关键词搜索历史会话消息。"""

    name = "session_search"
    description = (
        "Search past conversation history by keyword. "
        "Returns matching messages with session ID and timestamp context. "
        "Use to recall previous discussions, decisions, or task details."
    )
    parameters = {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "Keyword to search for in past conversations.",
            },
            "max_results": {
                "type": "integer",
                "description": "Maximum number of results to return (default: 5).",
            },
        },
        "required": ["query"],
    }
    danger_level = "safe"

    def __init__(self, sessions_dir: Path) -> None:
        self._sessions_dir = sessions_dir

    async def execute(self, **kwargs) -> str:
        """执行关键词搜索，返回格式化结果列表。"""
        query = kwargs["query"]
        max_results = kwargs.get("max_results", 5)
        query_lower = query.lower()

        if not self._sessions_dir.exists():
            return "No session history found."

        matches = []
        for path in self._sessions_dir.glob("*.json"):
            if len(matches) >= max_results:
                break
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, ValueError):
                continue

            session_id = data.get("session_id", path.stem)
            short_id = session_id[:8]
            # 格式化时间戳：YYYY-MM-DD HH:MM
            updated = data.get("updated_at", "")[:16].replace("T", " ")

            for msg in data.get("messages", []):
                if len(matches) >= max_results:
                    break
                content = msg.get("content") or ""
                if not isinstance(content, str):
                    continue
                if query_lower in content.lower():
                    role = msg.get("role", "?")
                    snippet = content[:100] + ("..." if len(content) > 100 else "")
                    matches.append(f"[{short_id} | {updated}] {role}: {snippet}")

        if not matches:
            return f"No results found for: {query}"

        return "\n".join(f"{i + 1}. {m}" for i, m in enumerate(matches))
```

- [ ] **Step 5: 更新 tools/__init__.py — 扩展 create_default_registry**

在 `my_small_agent/tools/__init__.py` 中：

1. 添加新 import（在现有 import 区块末尾追加）：

```python
from pathlib import Path

from my_small_agent.memory import MemoryManager
from my_small_agent.tools.memory_save import MemorySaveTool
from my_small_agent.tools.session_search import SessionSearchTool
```

2. 将 `create_default_registry` 函数替换为以下版本（新增两个可选参数，向后兼容）：

```python
def create_default_registry(
    settings: Settings,
    memory_manager: MemoryManager | None = None,
    sessions_dir: Path | None = None,
) -> ToolRegistry:
    """
    创建并返回一个包含所有内置工具的注册表。

    内置工具（始终注册）：
      - read_file:       读取文件（安全）
      - write_file:      写入文件（危险，需确认）
      - list_directory:  列出目录（安全）
      - execute_shell:   执行命令（危险，需确认）
      - web_search:      网页搜索（安全）
      - current_time:    当前时间（安全）

    可选工具（需提供对应参数）：
      - memory_save:     保存长期记忆（safe，需 memory_manager）
      - session_search:  搜索历史会话（safe，需 sessions_dir）
    """
    registry = ToolRegistry()
    registry.register(ReadFileTool())
    registry.register(WriteFileTool())
    registry.register(ListDirectoryTool())
    registry.register(ExecuteShellTool())
    registry.register(WebSearchTool())
    registry.register(CurrentTimeTool(timezone=settings.timezone))
    if memory_manager is not None:
        registry.register(MemorySaveTool(memory_manager))
    if sessions_dir is not None:
        registry.register(SessionSearchTool(sessions_dir))
    return registry
```

- [ ] **Step 6: 运行测试，确认新测试全部通过且无回归**

```
uv run pytest tests/test_tools_memory_search.py tests/test_tools_registry.py tests/test_integration.py -v
```

期望：全部 PASS（含 `test_registry_has_all_tools` — 不传新参数时仍为 6 个工具）

- [ ] **Step 7: Commit**

```
git add my_small_agent/tools/memory_save.py my_small_agent/tools/session_search.py my_small_agent/tools/__init__.py tests/test_tools_memory_search.py
git commit -m "feat: add memory_save and session_search tools with registry integration"
```

---

### Task 3: Agent 记忆注入 + reset_session 调整 + SYSTEM_PROMPT 增补

**Files:**
- Modify: `my_small_agent/agent.py`
- Modify: `tests/test_agent.py`（末尾追加新测试，不修改现有测试）

**Interfaces:**
- Consumes（来自 Task 1）:
  - `MemoryManager(memory_dir: Path)`
  - `MemoryManager.load_memory_text() -> str`
- Produces:
  - `Agent.__init__(llm, registry, settings, memory_manager=None)` — 新签名（向后兼容）
  - `Agent.messages` — 有记忆时包含 2 条 system 消息，无记忆时仍为 1 条
  - `Agent.reset_session()` — 保留所有 `role=system` 消息，而非仅 `messages[0]`

- [ ] **Step 1: 在 tests/test_agent.py 末尾追加新测试**

在文件末尾（紧接最后一行 `assert agent.thinking_enabled is False` 之后）追加：

```python


# ---- 记忆注入测试 ----

def test_agent_without_memory_manager_has_one_system_message():
    """不传 memory_manager 时，messages 应只有 1 条 system 消息。"""
    from unittest.mock import MagicMock
    from my_small_agent.config import Settings
    from my_small_agent.llm import LLMClient
    settings = MagicMock(spec=Settings)
    settings.max_iterations = 10
    settings.enable_streaming = True
    settings.enable_thinking = True
    llm = MagicMock(spec=LLMClient)
    registry = ToolRegistry()
    agent = Agent(llm, registry, settings)
    assert len(agent.messages) == 1
    assert agent.messages[0]["role"] == "system"


def test_agent_with_memory_manager_no_entries_has_one_system_message(tmp_path):
    """MemoryManager 无条目时，messages 应仍只有 1 条 system 消息（不注入空记忆）。"""
    from unittest.mock import MagicMock
    from my_small_agent.config import Settings
    from my_small_agent.llm import LLMClient
    from my_small_agent.memory import MemoryManager
    settings = MagicMock(spec=Settings)
    settings.max_iterations = 10
    settings.enable_streaming = True
    settings.enable_thinking = True
    llm = MagicMock(spec=LLMClient)
    registry = ToolRegistry()
    mm = MemoryManager(tmp_path)  # 无条目
    agent = Agent(llm, registry, settings, memory_manager=mm)
    assert len(agent.messages) == 1


def test_agent_with_memory_injects_second_system_message(tmp_path):
    """MemoryManager 有条目时，应注入第二条 system 消息。"""
    from unittest.mock import MagicMock
    from my_small_agent.config import Settings
    from my_small_agent.llm import LLMClient
    from my_small_agent.memory import MemoryManager
    settings = MagicMock(spec=Settings)
    settings.max_iterations = 10
    settings.enable_streaming = True
    settings.enable_thinking = True
    llm = MagicMock(spec=LLMClient)
    registry = ToolRegistry()
    mm = MemoryManager(tmp_path)
    mm.save_entry("User prefers Python")
    agent = Agent(llm, registry, settings, memory_manager=mm)
    assert len(agent.messages) == 2
    assert agent.messages[1]["role"] == "system"
    assert "Python" in agent.messages[1]["content"]
    assert "[长期记忆" in agent.messages[1]["content"]


def test_reset_session_preserves_memory_system_message(tmp_path):
    """reset_session() 应保留所有 system 消息（含记忆注入消息）。"""
    from unittest.mock import MagicMock
    from my_small_agent.config import Settings
    from my_small_agent.llm import LLMClient
    from my_small_agent.memory import MemoryManager
    settings = MagicMock(spec=Settings)
    settings.max_iterations = 10
    settings.enable_streaming = True
    settings.enable_thinking = True
    llm = MagicMock(spec=LLMClient)
    registry = ToolRegistry()
    mm = MemoryManager(tmp_path)
    mm.save_entry("test memory")
    agent = Agent(llm, registry, settings, memory_manager=mm)
    # 添加一条用户消息
    agent.messages.append({"role": "user", "content": "hello"})
    agent.reset_session()
    # 重置后应保留 2 条 system 消息（SYSTEM_PROMPT + 记忆注入）
    system_msgs = [m for m in agent.messages if m["role"] == "system"]
    assert len(system_msgs) == 2
    # 非 system 消息应被清空
    assert len(agent.messages) == 2
```

- [ ] **Step 2: 运行新增测试，确认失败**

```
uv run pytest tests/test_agent.py -v -k "memory"
```

期望：所有 `test_agent_with_memory` 和 `test_reset_session_preserves_memory` 测试 FAIL

- [ ] **Step 3: 修改 agent.py — 添加 MemoryManager import**

在 `agent.py` 顶部 import 区块，在 `from my_small_agent.tools import ToolRegistry` 之后添加：

```python
from my_small_agent.memory import MemoryManager
```

- [ ] **Step 4: 修改 agent.py — 增补 SYSTEM_PROMPT**

将现有 `SYSTEM_PROMPT` 末尾的：
```python
- 如果搜索无结果或工具失败，直接告知用户并给出建议
"""
```

替换为：
```python
- 如果搜索无结果或工具失败，直接告知用户并给出建议

长期记忆工具使用原则：
- 使用 memory_save 保存：用户偏好、环境细节、工具特性、稳定约定
- 不保存：任务进度、会话结果、临时状态（临时信息用 session_search 回忆）
- 优先保存能减少未来用户纠正/提醒的信息
- 使用 session_search 搜索过去的对话内容
"""
```

- [ ] **Step 5: 修改 agent.py — __init__ 添加 memory_manager 参数和注入逻辑**

将 `Agent.__init__` 方法签名从：
```python
    def __init__(
        self,
        llm: LLMClient,
        registry: ToolRegistry,
        settings: Settings,
    ) -> None:
```

改为：
```python
    def __init__(
        self,
        llm: LLMClient,
        registry: ToolRegistry,
        settings: Settings,
        memory_manager: MemoryManager | None = None,
    ) -> None:
```

在 `self.created_at` 赋值行之后，追加记忆注入逻辑：

```python
        # 注入长期记忆（仅在启动时执行一次，保障 prompt 缓存命中）
        if memory_manager is not None:
            memory_text = memory_manager.load_memory_text()
            if memory_text:
                self.messages.append({
                    "role": "system",
                    "content": (
                        "[长期记忆 - 请参考以下用户偏好和约定]\n\n"
                        f"{memory_text}\n\n"
                        "[本会话中新保存的记忆将在下次会话生效]"
                    ),
                })
```

- [ ] **Step 6: 修改 agent.py — 更新 reset_session() 保留所有 system 消息**

将 `reset_session()` 方法中的：
```python
        system_prompt = self.messages[0]
        self.messages = [system_prompt]
```

替换为：
```python
        # 保留所有 system 消息（含记忆注入消息），清空其余
        system_msgs = [m for m in self.messages if m.get("role") == "system"]
        self.messages = system_msgs
```

同时更新 docstring：
```python
        """
        重置会话状态，用于 /new 和 /resume 命令。

        保留所有 role=system 的消息（包含 SYSTEM_PROMPT 和记忆注入消息）。
        不传 session_id 时自动生成新 UUID。
        """
```

- [ ] **Step 7: 运行全部 agent 测试，确认全部通过**

```
uv run pytest tests/test_agent.py tests/test_agent_stream.py -v
```

期望：全部 PASS（新增测试通过，现有测试无回归；因现有测试不传 memory_manager 故只有 1 条 system 消息，reset 后仍为 1 条，`len == 1` 断言继续成立）

- [ ] **Step 8: Commit**

```
git add my_small_agent/agent.py tests/test_agent.py
git commit -m "feat: inject long-term memory as second system message in Agent"
```

---

### Task 4: __main__.py 接线 + 全量验证

**Files:**
- Modify: `my_small_agent/__main__.py`

**Interfaces:**
- Consumes（来自 Task 1）: `MemoryManager(Path(".genesis") / "memory")`
- Consumes（来自 Task 2）: `create_default_registry(settings, memory_manager, sessions_dir)`
- Consumes（来自 Task 3）: `Agent(llm_client, registry, settings, memory_manager=memory_manager)`

- [ ] **Step 1: 修改 __main__.py — 添加 MemoryManager import 和初始化**

在 `main()` 函数的 import 区块中，在 `from my_small_agent.session import SessionManager` 之后添加：

```python
        from my_small_agent.memory import MemoryManager        # 长期记忆
```

**注意初始化顺序**：memory_manager 必须在 `registry` 和 `agent` **之前**创建（registry 需要它注入工具，agent 需要它注入记忆）。

将 `__main__.py` 中的初始化块整体替换为（从注释 `# 3.` 开始到 `cli = CLI(...)`）：

```python
        # 3. 创建长期记忆管理器（加载 .genesis/memory/memory.json）
        memory_manager = MemoryManager(Path(".genesis") / "memory")

        # 4. 创建工具注册表（含 memory_save 和 session_search）
        registry = create_default_registry(
            settings,
            memory_manager=memory_manager,
            sessions_dir=Path(".genesis") / "sessions",
        )

        # 5. 创建 Agent（组装 LLM + 工具 + 配置 + 长期记忆）
        agent = Agent(llm_client, registry, settings, memory_manager=memory_manager)

        # 6. 创建会话管理器（保存到 .genesis/sessions/）
        session_manager = SessionManager(Path(".genesis") / "sessions")

        # 7. 创建 CLI 并启动交互循环
        cli = CLI(agent, session_manager)
        await cli.run()
```

- [ ] **Step 2: 删除原步骤 2 （已包含在 Step 1 的替换中）**

> 无需单独步骤——Step 1 已完整替换了 registry 和 agent 的初始化调用。

- [ ] **Step 3: 运行全量测试确认无回归**

```
uv run pytest tests/ -v
```

期望：全部 PASS（包含 test_memory.py、test_tools_memory_search.py 的新增测试）

- [ ] **Step 4: 手动验证**

```
uv run agent
```

依次测试：
1. 发送消息，请求 Agent 保存一条记忆（如"请记住我喜欢用 Python"）→ 确认 LLM 调用 `memory_save` → 确认 `.genesis/memory/memory.json` 中出现新条目
2. `/exit` 退出，重新启动 `uv run agent`
3. 确认启动后 Agent 能引用上次保存的记忆（在对话中提及 Python 偏好）
4. 发送消息，请求 Agent 搜索历史会话（如"搜索我们之前讨论过什么"）→ 确认 `session_search` 返回结果
5. `/status` → 确认工具列表包含 `memory_save` 和 `session_search`（用 `/tools` 命令）

- [ ] **Step 5: Commit**

```
git add my_small_agent/__main__.py
git commit -m "feat: wire MemoryManager into Agent and registry in main entry"
```
