# Session Persistence & Recovery Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add session persistence to MySmallAgent — conversations survive process restarts, with `/sessions`, `/resume`, `/new` CLI commands.

**Architecture:** New `session.py` handles all file I/O via atomic writes (temp→rename). `Agent` gains three session metadata fields and a `reset_session()` method. `CLI` auto-saves after each turn and wires in three new commands. `__main__.py` instantiates `SessionManager` and passes it to `CLI`.

**Tech Stack:** Python stdlib only (`uuid`, `json`, `os`, `pathlib`, `datetime`, `tempfile`). Tests use `pytest` + `tmp_path` fixture. Run with `uv run pytest`.

## Global Constraints

- Session files at `.genesis/sessions/{session_id}.json` relative to CWD
- Atomic write: write `.tmp` in same directory → `os.replace()` to target
- `messages` in session file never includes the system prompt (`role: system`)
- Session title = first 50 chars of first `role=user` message; fallback `"New Session"`
- All timestamps: ISO 8601 with UTC timezone (`datetime.now(timezone.utc).isoformat()`)
- Run tests: `uv run pytest tests/ -v`
- Modify existing files with `SearchReplace`, not full rewrites

---

### Task 1: session.py — 持久化核心模块

**Files:**
- Create: `my_small_agent/session.py`
- Create: `tests/test_session.py`

**Interfaces:**
- Produces:
  - `class AmbiguousPrefixError(Exception)` — `find_by_prefix()` 多匹配时抛出
  - `@dataclass class SessionData` — fields: `session_id: str`, `created_at: str`, `updated_at: str`, `title: str`, `messages: list[dict]`
  - `class SessionManager(sessions_dir: Path)`
  - `SessionManager.save(session_id: str, title: str, created_at: str, messages: list[dict]) -> None`
  - `SessionManager.load(session_id: str) -> SessionData | None`
  - `SessionManager.list_sessions() -> list[SessionData]` — 按 `updated_at` 倒序
  - `SessionManager.find_by_prefix(prefix: str) -> SessionData | None` — 多匹配抛 `AmbiguousPrefixError`

- [ ] **Step 1: 编写失败测试**

创建 `tests/test_session.py`：

```python
"""SessionManager 持久化模块的测试套件。"""

import json
from pathlib import Path

import pytest

from my_small_agent.session import AmbiguousPrefixError, SessionData, SessionManager


def test_save_creates_file(tmp_path):
    """save() 应创建对应的 JSON 文件。"""
    sm = SessionManager(tmp_path)
    sm.save("test-id-1", "Test Title", "2026-06-29T14:00:00+00:00", [])
    assert (tmp_path / "test-id-1.json").exists()


def test_save_file_content_is_correct(tmp_path):
    """save() 写入的 JSON 内容应与参数一致。"""
    sm = SessionManager(tmp_path)
    messages = [{"role": "user", "content": "hello"}]
    sm.save("abc-123", "My Session", "2026-06-29T14:00:00+00:00", messages)
    data = json.loads((tmp_path / "abc-123.json").read_text(encoding="utf-8"))
    assert data["session_id"] == "abc-123"
    assert data["title"] == "My Session"
    assert data["messages"] == messages
    assert "created_at" in data
    assert "updated_at" in data


def test_save_no_tmp_file_left(tmp_path):
    """原子写后不应留下 .tmp 临时文件。"""
    sm = SessionManager(tmp_path)
    sm.save("test-id", "T", "2026-06-29T14:00:00+00:00", [])
    assert list(tmp_path.glob("*.tmp")) == []


def test_save_creates_directory(tmp_path):
    """save() 应自动创建不存在的嵌套目录。"""
    nested = tmp_path / "a" / "b"
    sm = SessionManager(nested)
    sm.save("test-id", "T", "2026-06-29T14:00:00+00:00", [])
    assert nested.exists()


def test_load_returns_session_data(tmp_path):
    """load() 应返回正确填充的 SessionData。"""
    sm = SessionManager(tmp_path)
    messages = [{"role": "user", "content": "hello"}]
    sm.save("abc-123", "Test", "2026-06-29T14:00:00+00:00", messages)
    data = sm.load("abc-123")
    assert data is not None
    assert isinstance(data, SessionData)
    assert data.session_id == "abc-123"
    assert data.title == "Test"
    assert data.messages == messages


def test_load_returns_none_for_missing_file(tmp_path):
    """load() 文件不存在时应返回 None，不抛异常。"""
    sm = SessionManager(tmp_path)
    assert sm.load("nonexistent") is None


def test_load_returns_none_for_corrupt_json(tmp_path):
    """load() JSON 损坏时应返回 None，不抛异常。"""
    (tmp_path / "bad-id.json").write_text("not valid json", encoding="utf-8")
    sm = SessionManager(tmp_path)
    assert sm.load("bad-id") is None


def test_list_sessions_sorted_by_updated_at_descending(tmp_path):
    """list_sessions() 应按 updated_at 倒序返回。"""
    sm = SessionManager(tmp_path)
    for sid, updated in [
        ("id-old", "2026-06-29T10:00:00+00:00"),
        ("id-new", "2026-06-29T12:00:00+00:00"),
        ("id-mid", "2026-06-29T11:00:00+00:00"),
    ]:
        data = {
            "session_id": sid,
            "created_at": "2026-06-29T10:00:00+00:00",
            "updated_at": updated,
            "title": sid,
            "messages": [],
        }
        (tmp_path / f"{sid}.json").write_text(
            json.dumps(data), encoding="utf-8"
        )
    sessions = sm.list_sessions()
    assert [s.session_id for s in sessions] == ["id-new", "id-mid", "id-old"]


def test_list_sessions_empty_directory(tmp_path):
    """list_sessions() 目录为空时应返回空列表。"""
    sm = SessionManager(tmp_path)
    assert sm.list_sessions() == []


def test_list_sessions_skips_corrupt_files(tmp_path):
    """list_sessions() 应跳过 JSON 损坏的文件，不崩溃。"""
    sm = SessionManager(tmp_path)
    sm.save("good-id", "Good", "2026-06-29T10:00:00+00:00", [])
    (tmp_path / "bad-id.json").write_text("not json", encoding="utf-8")
    sessions = sm.list_sessions()
    assert len(sessions) == 1
    assert sessions[0].session_id == "good-id"


def test_find_by_prefix_unique_match(tmp_path):
    """find_by_prefix() 唯一匹配时应返回对应 SessionData。"""
    sm = SessionManager(tmp_path)
    sm.save("abc12345-fullid", "A", "2026-06-29T10:00:00+00:00", [])
    result = sm.find_by_prefix("abc12345")
    assert result is not None
    assert result.session_id == "abc12345-fullid"


def test_find_by_prefix_no_match_returns_none(tmp_path):
    """find_by_prefix() 无匹配时应返回 None。"""
    sm = SessionManager(tmp_path)
    assert sm.find_by_prefix("xyz99") is None


def test_find_by_prefix_ambiguous_raises(tmp_path):
    """find_by_prefix() 多个匹配时应抛出 AmbiguousPrefixError。"""
    sm = SessionManager(tmp_path)
    sm.save("abc111-id", "A", "2026-06-29T10:00:00+00:00", [])
    sm.save("abc222-id", "B", "2026-06-29T11:00:00+00:00", [])
    with pytest.raises(AmbiguousPrefixError):
        sm.find_by_prefix("abc")
```

- [ ] **Step 2: 运行测试，确认失败**

```
uv run pytest tests/test_session.py -v
```

期望：`ImportError: cannot import name 'SessionManager' from 'my_small_agent.session'`（模块不存在）

- [ ] **Step 3: 实现 session.py**

创建 `my_small_agent/session.py`：

```python
"""
会话持久化模块 - 负责会话数据的读写和查询。

设计思路：
  - SessionData 是纯数据容器（dataclass），不含 IO 逻辑
  - SessionManager 封装所有文件操作，支持原子写、列表查询、前缀匹配
  - 原子写策略：先写 .tmp 临时文件，再 os.replace() 重命名，防止崩溃丢数据
  - messages 字段不包含 system prompt（加载时由 Agent 重新插入）
"""

import json
import os
import tempfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path


class AmbiguousPrefixError(Exception):
    """find_by_prefix() 匹配到多个会话时抛出此异常。"""


@dataclass
class SessionData:
    """会话的完整数据结构（对应 JSON 文件内容）。"""

    session_id: str
    created_at: str   # ISO 8601 含时区
    updated_at: str   # ISO 8601 含时区
    title: str
    messages: list[dict]


class SessionManager:
    """
    会话持久化管理器。

    职责：
      - save():            原子写会话文件
      - load():            读取单个会话
      - list_sessions():   列出所有会话（按 updated_at 倒序）
      - find_by_prefix():  按 session_id 前缀查找会话
    """

    def __init__(self, sessions_dir: Path) -> None:
        # 会话文件存储目录（可能尚未创建）
        self._dir = sessions_dir

    def save(
        self,
        session_id: str,
        title: str,
        created_at: str,
        messages: list[dict],
    ) -> None:
        """
        原子写会话文件。

        策略：先在目标目录写临时文件，再 os.replace() 重命名。
        失败时清理临时文件，向上抛出异常（调用方负责打印警告）。
        """
        self._dir.mkdir(parents=True, exist_ok=True)
        target = self._dir / f"{session_id}.json"
        data = {
            "session_id": session_id,
            "created_at": created_at,
            "updated_at": datetime.now(timezone.utc).isoformat(),
            "title": title,
            "messages": messages,
        }
        # 在目标目录创建临时文件（同分区，os.replace() 才是原子操作）
        fd, tmp_path = tempfile.mkstemp(dir=self._dir, suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            os.replace(tmp_path, target)
        except Exception:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
            raise

    def load(self, session_id: str) -> SessionData | None:
        """读取指定会话文件。文件不存在或 JSON 损坏时返回 None。"""
        path = self._dir / f"{session_id}.json"
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            return SessionData(
                session_id=data["session_id"],
                created_at=data["created_at"],
                updated_at=data["updated_at"],
                title=data["title"],
                messages=data["messages"],
            )
        except (FileNotFoundError, json.JSONDecodeError, KeyError):
            return None

    def list_sessions(self) -> list[SessionData]:
        """
        列出所有已保存的会话，按 updated_at 倒序排列。
        JSON 损坏的文件自动跳过。
        """
        if not self._dir.exists():
            return []
        sessions = []
        for path in self._dir.glob("*.json"):
            data = self.load(path.stem)
            if data is not None:
                sessions.append(data)
        # ISO 8601 字符串可直接按字典序比较
        sessions.sort(key=lambda s: s.updated_at, reverse=True)
        return sessions

    def find_by_prefix(self, prefix: str) -> SessionData | None:
        """
        按 session_id 前缀查找会话。

        - 无匹配 → 返回 None
        - 唯一匹配 → 返回 SessionData
        - 多个匹配 → 抛出 AmbiguousPrefixError
        """
        all_sessions = self.list_sessions()
        matches = [s for s in all_sessions if s.session_id.startswith(prefix)]
        if len(matches) == 0:
            return None
        if len(matches) > 1:
            ids = ", ".join(s.session_id for s in matches)
            raise AmbiguousPrefixError(
                f"前缀 '{prefix}' 匹配到多个会话：{ids}"
            )
        return matches[0]
```

- [ ] **Step 4: 运行测试，确认全部通过**

```
uv run pytest tests/test_session.py -v
```

期望：13 个测试全部 PASS

- [ ] **Step 5: Commit**

```
git add my_small_agent/session.py tests/test_session.py
git commit -m "feat: add SessionManager with atomic write and prefix lookup"
```

---

### Task 2: Agent 会话元数据字段与 reset_session()

**Files:**
- Modify: `my_small_agent/agent.py`
- Modify: `tests/test_agent.py`（末尾追加新用例，不修改现有用例）

**Interfaces:**
- Consumes: `uuid.uuid4`, `datetime.now(timezone.utc).isoformat()`
- Produces:
  - `Agent.session_id: str` — UUID4 字符串，`__init__` 时自动生成
  - `Agent.session_title: str` — 默认 `""`
  - `Agent.created_at: str` — ISO 8601 UTC 时间戳
  - `Agent.reset_session(messages: list[dict] | None = None, session_id: str | None = None, title: str = "", created_at: str | None = None) -> None`

- [ ] **Step 1: 在 tests/test_agent.py 末尾追加新测试**

在文件末尾（第 234 行之后）追加以下内容（不修改任何现有代码）：

```python


# ---- 会话元数据测试 ----

def test_agent_has_session_id():
    """Agent 初始化后应有非空 session_id。"""
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
    assert isinstance(agent.session_id, str)
    assert len(agent.session_id) > 0


def test_agent_session_ids_are_unique():
    """每次创建 Agent 实例应生成不同的 session_id。"""
    from unittest.mock import MagicMock
    from my_small_agent.config import Settings
    from my_small_agent.llm import LLMClient
    settings = MagicMock(spec=Settings)
    settings.max_iterations = 10
    settings.enable_streaming = True
    settings.enable_thinking = True
    llm = MagicMock(spec=LLMClient)
    registry = ToolRegistry()
    a1 = Agent(llm, registry, settings)
    a2 = Agent(llm, registry, settings)
    assert a1.session_id != a2.session_id


def test_agent_has_empty_session_title_by_default():
    """初始 session_title 应为空字符串。"""
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
    assert agent.session_title == ""


def test_agent_has_created_at():
    """Agent 初始化后应有非空 created_at 时间戳。"""
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
    assert isinstance(agent.created_at, str)
    assert len(agent.created_at) > 0


def test_reset_session_keeps_system_prompt_clears_rest():
    """reset_session() 应保留 messages[0]（system prompt），清空其余。"""
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
    system_msg = agent.messages[0]
    agent.messages.append({"role": "user", "content": "hello"})
    agent.reset_session()
    assert len(agent.messages) == 1
    assert agent.messages[0] is system_msg


def test_reset_session_loads_provided_messages():
    """reset_session(messages=...) 应在 system prompt 后追加传入的消息。"""
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
    msgs = [
        {"role": "user", "content": "hi"},
        {"role": "assistant", "content": "hello"},
    ]
    agent.reset_session(messages=msgs)
    assert len(agent.messages) == 3   # system + 2
    assert agent.messages[1] == msgs[0]
    assert agent.messages[2] == msgs[1]


def test_reset_session_generates_new_id():
    """reset_session() 不传 session_id 时应生成新 UUID。"""
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
    old_id = agent.session_id
    agent.reset_session()
    assert agent.session_id != old_id


def test_reset_session_with_explicit_metadata():
    """reset_session() 传入 session_id/title/created_at 时应使用传入值。"""
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
    agent.reset_session(
        session_id="custom-id-abc",
        title="My Title",
        created_at="2026-01-01T00:00:00+00:00",
    )
    assert agent.session_id == "custom-id-abc"
    assert agent.session_title == "My Title"
    assert agent.created_at == "2026-01-01T00:00:00+00:00"


def test_clear_history_generates_new_session_id():
    """clear_history() 应生成新的 session_id（不再复用旧 ID）。"""
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
    old_id = agent.session_id
    agent.clear_history()
    assert agent.session_id != old_id
    assert len(agent.messages) == 1
    assert agent.messages[0]["role"] == "system"
```

- [ ] **Step 2: 运行新增测试，确认失败**

```
uv run pytest tests/test_agent.py -v -k "session or reset or created_at"
```

期望：所有新测试 FAIL（`AttributeError: 'Agent' object has no attribute 'session_id'`）

- [ ] **Step 3: 修改 agent.py — 新增 import**

在 `agent.py` 顶部的 import 区块中，在 `import json` 行之后添加：

```python
from datetime import datetime, timezone
from uuid import uuid4
```

- [ ] **Step 4: 修改 agent.py — 新增三个字段**

在 `Agent.__init__` 中，在 `self.messages = [...]` 初始化之后追加：

```python
        # 会话元数据（用于持久化）
        self.session_id: str = str(uuid4())
        self.session_title: str = ""
        self.created_at: str = datetime.now(timezone.utc).isoformat()
```

- [ ] **Step 5: 修改 agent.py — 新增 reset_session() 方法**

在 `clear_history()` 方法之后添加 `reset_session()` 方法，并修改 `clear_history()` 使其复用：

```python
    def reset_session(
        self,
        messages: list[dict] | None = None,
        session_id: str | None = None,
        title: str = "",
        created_at: str | None = None,
    ) -> None:
        """
        重置会话状态，用于 /new 和 /resume 命令。

        保留 messages[0]（system prompt），替换其余所有消息。
        不传 session_id 时自动生成新 UUID。
        """
        system_prompt = self.messages[0]
        self.messages = [system_prompt]
        if messages:
            self.messages.extend(messages)
        self.session_id = session_id or str(uuid4())
        self.session_title = title
        self.created_at = created_at or datetime.now(timezone.utc).isoformat()
```

将原有的 `clear_history()` 改为调用 `reset_session()`：

```python
    def clear_history(self) -> None:
        """
        清空对话历史，保留 system prompt，并生成新的 session_id。
        相当于 /new 命令。
        """
        self.reset_session()
```

- [ ] **Step 6: 运行全部 agent 测试，确认通过**

```
uv run pytest tests/test_agent.py tests/test_agent_stream.py -v
```

期望：全部 PASS（新增测试通过，现有测试不受影响）

- [ ] **Step 7: Commit**

```
git add my_small_agent/agent.py tests/test_agent.py
git commit -m "feat: add session_id/title/created_at and reset_session() to Agent"
```

---

### Task 3: CLI 集成 — 自动保存 + 三条新命令 + 入口连线

**Files:**
- Modify: `my_small_agent/cli.py`
- Modify: `my_small_agent/__main__.py`

**Interfaces:**
- Consumes（来自 Task 1）:
  - `SessionManager(sessions_dir: Path)`
  - `SessionManager.save(session_id: str, title: str, created_at: str, messages: list[dict]) -> None`
  - `SessionManager.list_sessions() -> list[SessionData]`
  - `SessionManager.find_by_prefix(prefix: str) -> SessionData | None`（多匹配抛 `AmbiguousPrefixError`）
  - `SessionData.session_id / .title / .updated_at / .messages`
- Consumes（来自 Task 2）:
  - `Agent.session_id / .session_title / .created_at`
  - `Agent.reset_session(messages, session_id, title, created_at)`

- [ ] **Step 1: 修改 cli.py — 顶部新增 import**

在 `cli.py` 顶部 import 区块末尾追加：

```python
from pathlib import Path
from my_small_agent.session import AmbiguousPrefixError, SessionManager
```

- [ ] **Step 2: 修改 cli.py — __init__ 接收 SessionManager**

将 `CLI.__init__` 的签名和首行赋值从：

```python
    def __init__(self, agent: Agent) -> None:
        self.agent = agent
```

改为：

```python
    def __init__(self, agent: Agent, session_manager: SessionManager) -> None:
        self.agent = agent
        self.session_manager = session_manager
```

- [ ] **Step 3: 修改 cli.py — _run_agent_turn 末尾触发自动保存**

将 `_run_agent_turn()` 方法改为：

```python
    async def _run_agent_turn(self, user_input: str) -> None:
        """根据 streaming 状态选择流式或非流式对话，完成后自动保存会话。"""
        if self.agent.streaming_enabled:
            await self._run_agent_turn_stream(user_input)
        else:
            await self._run_agent_turn_normal(user_input)
        # 对话完成后自动保存会话
        self._save_session()
```

在 `_run_agent_turn_normal()` 方法之前，添加 `_save_session()` 方法：

```python
    def _save_session(self) -> None:
        """保存当前会话到文件。失败时打印警告，不中断对话。"""
        # title 为空时，从消息列表取第一条 user 消息的前 50 字符
        if not self.agent.session_title:
            for msg in self.agent.messages:
                if msg.get("role") == "user":
                    self.agent.session_title = msg["content"][:50]
                    break
        title = self.agent.session_title or "New Session"
        # 过滤掉 system prompt，只保存对话消息
        messages = [m for m in self.agent.messages if m.get("role") != "system"]
        try:
            self.session_manager.save(
                session_id=self.agent.session_id,
                title=title,
                created_at=self.agent.created_at,
                messages=messages,
            )
        except Exception as e:
            self.console.print(f"[yellow]⚠ 会话保存失败：{e}[/yellow]")
```

- [ ] **Step 4: 修改 cli.py — _handle_command 新增三个命令分支**

在 `_handle_command()` 方法的 `elif cmd == "/clear":` 分支之前添加：

```python
        elif cmd == "/sessions":
            self._print_sessions()
        elif cmd == "/resume":
            await self._resume_session(command)
        elif cmd == "/new":
            self._new_session()
```

同时将现有 `/clear` 分支改为调用 `reset_session()`：

```python
        elif cmd == "/clear":
            self.agent.reset_session()
            self.console.print("[green]对话历史已清空，已开始新会话。[/green]")
```

- [ ] **Step 5: 修改 cli.py — 添加三个命令处理方法**

在 `_print_tools()` 方法之后追加：

```python
    def _print_sessions(self) -> None:
        """列出所有历史会话，按 updated_at 倒序展示。"""
        sessions = self.session_manager.list_sessions()
        if not sessions:
            self.console.print("[dim]暂无历史会话。使用 /new 开始新会话。[/dim]")
            return

        lines = []
        for i, s in enumerate(sessions, 1):
            # 当前会话用 ▶ 标注
            marker = "[cyan]▶[/cyan] " if s.session_id == self.agent.session_id else "  "
            # 格式化时间：取 updated_at 前 16 字符（YYYY-MM-DDTHH:MM）
            updated = s.updated_at[:16].replace("T", " ")
            short_id = s.session_id[:8]
            lines.append(
                f"{marker}{i}. [dim][{short_id}][/dim]  {s.title}\n"
                f"       [dim]{updated}[/dim]"
            )

        self.console.print(
            Panel(
                "\n\n".join(lines),
                title=f"历史会话 ({len(sessions)})",
                border_style="cyan",
            )
        )

    async def _resume_session(self, command: str) -> None:
        """恢复指定前缀的历史会话。"""
        parts = command.strip().split(maxsplit=1)
        if len(parts) < 2 or not parts[1].strip():
            self.console.print(
                "[yellow]用法：/resume <session_id_prefix>[/yellow]\n"
                "  例如：/resume abc12345"
            )
            return

        prefix = parts[1].strip()
        try:
            session = self.session_manager.find_by_prefix(prefix)
        except AmbiguousPrefixError as e:
            self.console.print(f"[yellow]⚠ {e}[/yellow]")
            return

        if session is None:
            self.console.print(f"[red]未找到匹配前缀 '{prefix}' 的会话。[/red]")
            return

        self.agent.reset_session(
            messages=session.messages,
            session_id=session.session_id,
            title=session.title,
            created_at=session.created_at,
        )
        self.console.print(
            f"[green]✓ 已恢复会话：[bold]{session.title}[/bold][/green]\n"
            f"  [dim]ID: {session.session_id[:8]}  共 {len(session.messages)} 条消息[/dim]"
        )

    def _new_session(self) -> None:
        """创建新会话，清空消息历史。"""
        self.agent.reset_session()
        self.console.print("[green]✓ 已创建新会话。[/green]")
```

- [ ] **Step 6: 修改 cli.py — 更新欢迎面板和帮助面板**

在 `_print_welcome()` 的 Panel 内容中，在 `"  /clear  - Clear history\n"` 之前插入：

```python
"  /sessions - List conversation history\n"
"  /resume   - Resume a past session\n"
"  /new      - Start a new session\n"
```

在 `_print_help()` 的 Panel 内容中，在 `/clear` 行之前同样插入三行说明：

```python
"  [cyan]/sessions[/cyan] - List all saved conversations\n"
"  [cyan]/resume[/cyan]   - Resume a past session: /resume <id_prefix>\n"
"  [cyan]/new[/cyan]      - Start a new session\n"
```

在 `_print_status()` 的 Panel 内容末尾追加会话信息行：

```python
f"  当前会话:   [dim]{self.agent.session_id[:8]}[/dim]  "
f"{self.agent.session_title or '(未命名)'}\n"
```

- [ ] **Step 7: 修改 __main__.py — 接入 SessionManager**

在 `main()` 函数的 import 区添加：

```python
        from pathlib import Path
        from my_small_agent.session import SessionManager
```

在 `agent = Agent(llm_client, registry, settings)` 之后、`cli = CLI(agent)` 之前添加：

```python
        # 5. 创建会话管理器（保存到 .genesis/sessions/）
        session_manager = SessionManager(Path(".genesis") / "sessions")
```

将 `cli = CLI(agent)` 改为：

```python
        # 6. 创建 CLI 并启动交互循环
        cli = CLI(agent, session_manager)
```

同时将原注释 `# 5. 创建 CLI 并启动交互循环` 改为 `# 6. 创建 CLI 并启动交互循环`。

- [ ] **Step 8: 运行全量测试确认无回归**

```
uv run pytest tests/ -v
```

期望：全部 PASS

- [ ] **Step 9: 手动验证**

```
uv run agent
```

依次测试：
1. 发送一条消息 → 确认 `.genesis/sessions/` 目录下出现 `{uuid}.json` 文件
2. `/sessions` → 确认列出该会话
3. `/status` → 确认显示当前会话 ID 前缀
4. `/exit` 退出，再次运行 `uv run agent`
5. `/sessions` → 确认历史会话仍存在
6. 复制 ID 前缀，`/resume <prefix>` → 确认会话恢复，显示原对话条数
7. `/new` → 确认清空并显示新会话提示
8. `/clear` → 确认同样生成新 session_id

- [ ] **Step 10: Commit**

```
git add my_small_agent/cli.py my_small_agent/__main__.py
git commit -m "feat: integrate SessionManager into CLI with /sessions, /resume, /new commands"
```
