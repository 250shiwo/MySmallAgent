# Token估算/上下文压缩/六工具 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 为 MySmallAgent 新增 Token 估算展示、上下文自动/手动压缩、以及六个实用工具。

**Architecture:** 在 `config.py` 增加 4 个配置字段；在 `agent.py` 增加 `estimate_tokens()` 和 `compact_context()` 方法；在 `cli.py` 增强 `/status` 展示并新增 `/compact` 命令及每轮自动触发逻辑；在 `tools/` 目录下新增 6 个工具文件并在注册表注册。

**Tech Stack:** Python 3.11+, pydantic-settings, httpx (新增), rich, asyncio, pathlib, re

## Global Constraints

- Python >= 3.11
- 所有新工具继承 `my_small_agent/tools/base.py` 中的 `Tool` 抽象基类
- 工具 `execute()` 方法必须为 `async def execute(self, **kwargs) -> str`
- 危险操作（写/删除）`danger_level = "dangerous"`，只读操作 `danger_level = "safe"`
- 测试用 `pytest` + `pytest-asyncio`，asyncio_mode = "auto"（`pyproject.toml` 已配置）
- 现有测试必须保持全部通过
- Token 估算算法固定为：所有 message 字段字符串之和 ÷ 4（chars/4）
- 压缩条件：`len(messages) > head_keep + tail_keep`（默认 > 23）
- 压缩算法：`messages[:head_keep] + [summary_msg] + messages[-tail_keep:]`

---

### Task 1: 配置层扩展（新增4个压缩相关字段）

**Files:**
- Modify: `my_small_agent/config.py`
- Modify: `tests/test_config.py`

**Interfaces:**
- Produces:
  - `settings.max_context_tokens: int` (default 200000)
  - `settings.head_keep: int` (default 3)
  - `settings.tail_keep: int` (default 20)
  - `settings.compression_threshold: float` (default 0.8)

- [ ] **Step 1: 写失败测试**

在 `tests/test_config.py` 末尾追加：

```python
def test_compression_fields_defaults(monkeypatch):
    """压缩相关配置项应有正确默认值。"""
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    settings = Settings(_env_file=None)
    assert settings.max_context_tokens == 200000
    assert settings.head_keep == 3
    assert settings.tail_keep == 20
    assert settings.compression_threshold == 0.8


def test_compression_fields_from_env(monkeypatch):
    """压缩相关配置项应能从环境变量读取。"""
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.setenv("MAX_CONTEXT_TOKENS", "128000")
    monkeypatch.setenv("HEAD_KEEP", "5")
    monkeypatch.setenv("TAIL_KEEP", "15")
    monkeypatch.setenv("COMPRESSION_THRESHOLD", "0.9")
    settings = Settings(_env_file=None)
    assert settings.max_context_tokens == 128000
    assert settings.head_keep == 5
    assert settings.tail_keep == 15
    assert settings.compression_threshold == 0.9
```

- [ ] **Step 2: 运行测试确认失败**

```
uv run pytest tests/test_config.py::test_compression_fields_defaults -v
```

期望：FAIL，提示 `Settings` 没有 `max_context_tokens` 属性。

- [ ] **Step 3: 在 config.py 添加 4 个字段**

在 `my_small_agent/config.py` 的 `timezone` 行之后插入：

```python
    max_context_tokens: int = 200000          # 上下文最大 token 数（估算上限）
    head_keep: int = 3                        # 压缩时保留开头消息条数
    tail_keep: int = 20                       # 压缩时保留末尾消息条数
    compression_threshold: float = 0.8       # 自动触发压缩的 token 用量比例
```

- [ ] **Step 4: 运行测试确认通过**

```
uv run pytest tests/test_config.py -v
```

期望：全部 PASS。

- [ ] **Step 5: 提交**

```
git add my_small_agent/config.py tests/test_config.py
git commit -m "feat(config): 新增 max_context_tokens/head_keep/tail_keep/compression_threshold 配置项"
```

---

### Task 2: Token 估算功能（estimate_tokens 方法 + /status 增强）

**Files:**
- Modify: `my_small_agent/agent.py`
- Modify: `my_small_agent/cli.py`
- Modify: `tests/test_agent.py`

**Interfaces:**
- Consumes: `settings.max_context_tokens: int`（Task 1 产出）
- Produces:
  - `agent.estimate_tokens() -> int`：估算当前所有消息的 token 用量
  - `agent.settings: Settings`：存储完整 settings 对象供后续任务使用

- [ ] **Step 1: 写 estimate_tokens 失败测试**

在 `tests/test_agent.py` 的 `mock_settings` fixture 中追加新字段（在已有属性后），并添加测试类：

首先更新 `mock_settings` fixture（在 `settings.enable_thinking = True` 后加）：

```python
    settings.max_context_tokens = 200000
    settings.head_keep = 3
    settings.tail_keep = 20
    settings.compression_threshold = 0.8
```

然后在文件末尾新增：

```python
class TestEstimateTokens:
    def test_empty_messages_returns_zero(self, mock_settings, registry):
        """只有 system prompt 时应返回合理的估算值（大于 0）。"""
        llm = MagicMock(spec=LLMClient)
        agent = Agent(llm, registry, mock_settings)
        tokens = agent.estimate_tokens()
        assert tokens > 0  # system prompt 有内容

    def test_estimate_grows_with_messages(self, mock_settings, registry):
        """添加消息后 token 估算值应增大。"""
        llm = MagicMock(spec=LLMClient)
        agent = Agent(llm, registry, mock_settings)
        before = agent.estimate_tokens()
        agent.messages.append({"role": "user", "content": "a" * 400})
        after = agent.estimate_tokens()
        assert after > before
        # 400 chars / 4 = 100 tokens, 应有近似增量
        assert after - before == pytest.approx(100, abs=5)

    def test_estimate_counts_all_string_fields(self, mock_settings, registry):
        """tool_calls 等非 content 字段也应计入估算。"""
        llm = MagicMock(spec=LLMClient)
        agent = Agent(llm, registry, mock_settings)
        baseline = agent.estimate_tokens()
        agent.messages.append({
            "role": "assistant",
            "content": None,
            "tool_calls": [{"function": {"name": "x" * 40, "arguments": "{}"}}],
        })
        after = agent.estimate_tokens()
        assert after > baseline
```

- [ ] **Step 2: 运行测试确认失败**

```
uv run pytest tests/test_agent.py::TestEstimateTokens -v
```

期望：FAIL，`Agent` 没有 `estimate_tokens` 方法。

- [ ] **Step 3: 在 agent.py 中存储 settings 并实现 estimate_tokens**

在 `Agent.__init__` 的 `self.max_iterations = settings.max_iterations` 行之后添加：

```python
        self.settings = settings  # 保存完整 settings 供压缩功能使用
```

在 `Agent` 类末尾（`clear_history` 方法之后）添加：

```python
    def estimate_tokens(self) -> int:
        """
        估算当前对话历史的 token 用量（chars / 4 算法）。

        遍历所有 message 的每个字段：
          - 字符串值直接计长度
          - 列表/字典值序列化为 JSON 后计长度
        """
        total_chars = 0
        for msg in self.messages:
            for value in msg.values():
                if isinstance(value, str):
                    total_chars += len(value)
                elif isinstance(value, (dict, list)):
                    total_chars += len(json.dumps(value, ensure_ascii=False))
        return total_chars // 4
```

- [ ] **Step 4: 运行测试确认通过**

```
uv run pytest tests/test_agent.py::TestEstimateTokens -v
```

期望：全部 PASS。

- [ ] **Step 5: 增强 /status 显示 Token 用量**

在 `my_small_agent/cli.py` 的 `_print_status` 方法中，替换 Panel 内容，在"当前会话"行之前插入 Token usage 行。

将原 Panel 内容：

```python
        self.console.print(
            Panel(
                f"  模型:       [bold]{self.agent.llm.model}[/bold]\n"
                f"  流式输出:   {streaming}\n"
                f"  思维链:     {thinking}\n"
                f"  详情展示:   {detail}\n"
                f"  当前会话:   [dim]{self.agent.session_id[:8]}[/dim]  "
                f"{self.agent.session_title or '(未命名)'}",
                title="当前状态",
                border_style="cyan",
            )
        )
```

替换为：

```python
        tokens = self.agent.estimate_tokens()
        max_tokens = self.agent.settings.max_context_tokens
        pct = int(tokens / max_tokens * 100) if max_tokens > 0 else 0
        token_line = f"  Token 用量: ~{tokens:,} / {max_tokens:,} ({pct}%)"
        self.console.print(
            Panel(
                f"  模型:       [bold]{self.agent.llm.model}[/bold]\n"
                f"  流式输出:   {streaming}\n"
                f"  思维链:     {thinking}\n"
                f"  详情展示:   {detail}\n"
                f"{token_line}\n"
                f"  当前会话:   [dim]{self.agent.session_id[:8]}[/dim]  "
                f"{self.agent.session_title or '(未命名)'}",
                title="当前状态",
                border_style="cyan",
            )
        )
```

- [ ] **Step 6: 运行所有测试确认不破坏现有功能**

```
uv run pytest tests/ -v
```

期望：全部 PASS。

- [ ] **Step 7: 提交**

```
git add my_small_agent/agent.py my_small_agent/cli.py tests/test_agent.py
git commit -m "feat(agent): 新增 estimate_tokens 方法；/status 展示 token 用量进度"
```

---

### Task 3: 上下文压缩核心功能（compact_context 方法）

**Files:**
- Modify: `my_small_agent/agent.py`
- Modify: `tests/test_agent.py`

**Interfaces:**
- Consumes:
  - `self.settings.head_keep: int`
  - `self.settings.tail_keep: int`
  - `self.llm.chat(messages, tools, thinking_enabled) -> response`
- Produces:
  - `agent.compact_context() -> tuple[int, int]`：返回 `(压缩前消息数, 压缩后消息数)`

- [ ] **Step 1: 写 compact_context 失败测试**

在 `tests/test_agent.py` 文件末尾追加：

```python
COMPACT_SUMMARY_PROMPT_FRAGMENT = "## Goal"  # LLM 收到的 prompt 应含此结构


class TestCompactContext:
    def _make_agent_with_many_messages(self, mock_settings, registry, n_extra=25):
        """创建一个消息数 > head_keep + tail_keep 的 agent。"""
        llm = MagicMock(spec=LLMClient)
        agent = Agent(llm, registry, mock_settings)
        for i in range(n_extra):
            agent.messages.append({"role": "user", "content": f"user msg {i}"})
            agent.messages.append({"role": "assistant", "content": f"assistant reply {i}"})
        return agent, llm

    @pytest.mark.asyncio
    async def test_compact_reduces_message_count(self, mock_settings, registry):
        """压缩后消息总数应 < 压缩前。"""
        agent, llm = self._make_agent_with_many_messages(mock_settings, registry)
        before_count = len(agent.messages)

        summary_response = MagicMock()
        summary_response.choices[0].message.content = "## Goal\n- 测试目标\n## Key Actions\n- 无"
        llm.chat = AsyncMock(return_value=summary_response)

        before, after = await agent.compact_context()
        assert before == before_count
        assert after < before
        # after = head_keep + 1(summary) + tail_keep = 3 + 1 + 20 = 24
        assert after == mock_settings.head_keep + 1 + mock_settings.tail_keep

    @pytest.mark.asyncio
    async def test_compact_preserves_head_and_tail(self, mock_settings, registry):
        """压缩应保留前 head_keep 条和后 tail_keep 条消息。"""
        agent, llm = self._make_agent_with_many_messages(mock_settings, registry, n_extra=15)
        first_msgs = agent.messages[:mock_settings.head_keep]
        last_msgs = agent.messages[-mock_settings.tail_keep:]

        summary_response = MagicMock()
        summary_response.choices[0].message.content = "summary"
        llm.chat = AsyncMock(return_value=summary_response)

        await agent.compact_context()

        assert agent.messages[:mock_settings.head_keep] == first_msgs
        assert agent.messages[-mock_settings.tail_keep:] == last_msgs

    @pytest.mark.asyncio
    async def test_compact_inserts_summary_message(self, mock_settings, registry):
        """压缩后中间应有一条含摘要内容的消息。"""
        agent, llm = self._make_agent_with_many_messages(mock_settings, registry, n_extra=15)

        summary_response = MagicMock()
        summary_response.choices[0].message.content = "## Goal\n压缩测试"
        llm.chat = AsyncMock(return_value=summary_response)

        await agent.compact_context()

        summary_msg = agent.messages[mock_settings.head_keep]
        assert "压缩历史摘要" in summary_msg["content"]
        assert "## Goal" in summary_msg["content"]

    @pytest.mark.asyncio
    async def test_compact_calls_llm_with_structured_prompt(self, mock_settings, registry):
        """compact_context 应调用 LLM 且 prompt 含结构化模板关键词。"""
        agent, llm = self._make_agent_with_many_messages(mock_settings, registry, n_extra=15)

        summary_response = MagicMock()
        summary_response.choices[0].message.content = "ok"
        llm.chat = AsyncMock(return_value=summary_response)

        await agent.compact_context()

        llm.chat.assert_called_once()
        call_args = llm.chat.call_args
        prompt_msgs = call_args.kwargs.get("messages") or call_args.args[0]
        prompt_text = prompt_msgs[0]["content"]
        assert "## Goal" in prompt_text
        assert "## Key Actions" in prompt_text
        assert "## Current State" in prompt_text
```

- [ ] **Step 2: 运行测试确认失败**

```
uv run pytest tests/test_agent.py::TestCompactContext -v
```

期望：FAIL，`Agent` 没有 `compact_context` 方法。

- [ ] **Step 3: 在 agent.py 中实现 compact_context**

在 `estimate_tokens` 方法之后添加：

```python
    async def compact_context(self) -> tuple[int, int]:
        """
        压缩对话历史，用 LLM 生成的摘要替换中间消息。

        算法：
          保留 messages[:head_keep] + [摘要消息] + messages[-tail_keep:]

        返回：(压缩前消息数, 压缩后消息数)
        """
        head = self.settings.head_keep
        tail = self.settings.tail_keep
        middle = self.messages[head:-tail]

        # 将中间消息序列化为文本供 LLM 压缩
        middle_text = "\n\n".join(
            f"[{m.get('role', 'unknown')}]: "
            + (m.get("content") or json.dumps(m.get("tool_calls", ""), ensure_ascii=False))
            for m in middle
        )

        summary_prompt = (
            "请将以下对话历史压缩为简洁摘要，严格使用以下格式：\n\n"
            "## Goal           — 用户目标（1-2 句）\n"
            "## Key Actions    — 已执行的操作列表\n"
            "## Current State  — 当前进展\n"
            "## Decisions      — 重要技术决策\n"
            "## Technical Details — 需要精确保留的值\n"
            "## User Preferences — 用户表达的偏好\n\n"
            "对话内容：\n"
            f"{middle_text}"
        )

        response = await self.llm.chat(
            messages=[{"role": "user", "content": summary_prompt}],
            tools=None,
            thinking_enabled=False,
        )
        summary = response.choices[0].message.content or "(摘要生成失败)"

        before_count = len(self.messages)
        summary_msg = {
            "role": "assistant",
            "content": f"[压缩历史摘要]\n\n{summary}",
        }
        self.messages = self.messages[:head] + [summary_msg] + self.messages[-tail:]
        after_count = len(self.messages)

        return before_count, after_count
```

- [ ] **Step 4: 运行测试确认通过**

```
uv run pytest tests/test_agent.py::TestCompactContext -v
```

期望：全部 PASS。

- [ ] **Step 5: 运行全量测试**

```
uv run pytest tests/ -v
```

期望：全部 PASS。

- [ ] **Step 6: 提交**

```
git add my_small_agent/agent.py tests/test_agent.py
git commit -m "feat(agent): 新增 compact_context 方法，支持 LLM 摘要驱动的上下文压缩"
```

---

### Task 4: /compact 命令与自动压缩触发（CLI 层）

**Files:**
- Modify: `my_small_agent/cli.py`

**Interfaces:**
- Consumes:
  - `agent.compact_context() -> tuple[int, int]`（Task 3 产出）
  - `agent.estimate_tokens() -> int`（Task 2 产出）
  - `agent.settings.head_keep/tail_keep/max_context_tokens/compression_threshold`（Task 1 产出）

- [ ] **Step 1: 在 _handle_command 中注册 /compact 命令**

在 `cli.py` 的 `_handle_command` 方法中，在 `elif cmd == "/clear":` 行之前插入：

```python
        elif cmd == "/compact":
            await self._compact_context()
```

- [ ] **Step 2: 实现 _compact_context 方法**

在 `cli.py` 的 `_new_session` 方法之后添加：

```python
    async def _compact_context(self) -> None:
        """
        手动触发上下文压缩。

        检查消息总数是否 > head_keep + tail_keep（默认 23），
        满足条件则调用 LLM 生成摘要并替换中间消息，展示压缩前后对比。
        """
        min_required = self.agent.settings.head_keep + self.agent.settings.tail_keep
        if len(self.agent.messages) <= min_required:
            self.console.print(
                f"[yellow]⚠ 消息总数（{len(self.agent.messages)} 条）不超过 {min_required} 条，"
                f"无需压缩。[/yellow]"
            )
            return

        self.console.print("[dim]⚡ 正在压缩上下文...[/dim]")
        try:
            before, after = await self.agent.compact_context()
            self.console.print(
                f"[green]✓ 上下文已压缩：{before} 条 → {after} 条消息 "
                f"（节省 {before - after} 条）[/green]"
            )
        except Exception as e:
            self.console.print(f"[red]✗ 压缩失败：{e}[/red]")
```

- [ ] **Step 3: 在帮助文本中注册 /compact**

在 `_print_help` 方法的 Panel 内容中，在 `/clear` 行之前插入：

```
"  [cyan]/compact[/cyan]   - Compress conversation context (keeps first 3 + last 20)\n"
```

在 `_print_welcome` 方法的 Panel 内容中，在 `/clear` 行之前插入：

```
"  /compact  - Compress conversation context\n"
```

在 `_handle_command` 的文档字符串列表中添加：

```
          /compact  → 手动压缩上下文（保留前3条+后20条）
```

- [ ] **Step 4: 在每轮对话后自动检查并触发压缩**

在 `_run_agent_turn` 方法中，在 `self._save_session()` 调用之后添加自动检查：

```python
    async def _run_agent_turn(self, user_input: str) -> None:
        """根据 streaming 状态选择流式或非流式对话，完成后自动保存会话。"""
        if self.agent.streaming_enabled:
            await self._run_agent_turn_stream(user_input)
        else:
            await self._run_agent_turn_normal(user_input)
        # 对话完成后自动保存会话
        self._save_session()
        # 检查是否需要自动压缩
        await self._auto_compact_if_needed()

    async def _auto_compact_if_needed(self) -> None:
        """当 token 估算超过阈值时自动触发上下文压缩。"""
        tokens = self.agent.estimate_tokens()
        threshold = int(
            self.agent.settings.max_context_tokens * self.agent.settings.compression_threshold
        )
        min_required = self.agent.settings.head_keep + self.agent.settings.tail_keep
        if tokens >= threshold and len(self.agent.messages) > min_required:
            self.console.print(
                f"[dim]⚡ Token 用量（{tokens:,}）达到阈值（{threshold:,}），自动压缩中...[/dim]"
            )
            try:
                before, after = await self.agent.compact_context()
                self.console.print(
                    f"[dim]✓ 自动压缩完成：{before} 条 → {after} 条[/dim]"
                )
            except Exception as e:
                self.console.print(f"[dim]⚠ 自动压缩失败：{e}[/dim]")
```

注意：此步骤需要将 `_run_agent_turn` 中原有的两行替换为上方完整的两个方法。

- [ ] **Step 5: 运行全量测试**

```
uv run pytest tests/ -v
```

期望：全部 PASS。

- [ ] **Step 6: 提交**

```
git add my_small_agent/cli.py
git commit -m "feat(cli): 新增 /compact 命令，支持手动和自动上下文压缩"
```

---

### Task 5: 六个实用工具（grep_search / fetch_url / tree / find_file / file_delete / system_info）

**Files:**
- Create: `my_small_agent/tools/grep_search.py`
- Create: `my_small_agent/tools/fetch_url.py`
- Create: `my_small_agent/tools/tree.py`
- Create: `my_small_agent/tools/find_file.py`
- Create: `my_small_agent/tools/file_delete.py`
- Create: `my_small_agent/tools/system_info.py`
- Modify: `my_small_agent/tools/__init__.py`
- Modify: `pyproject.toml`（添加 `httpx` 依赖）
- Create: `tests/test_tools_utility.py`

**Interfaces:**
- Produces:
  - `GrepSearchTool` (name=`grep_search`, safe)
  - `FetchUrlTool` (name=`fetch_url`, safe)
  - `TreeTool` (name=`tree`, safe)
  - `FindFileTool` (name=`find_file`, safe)
  - `DeleteFileTool` (name=`file_delete`, dangerous)
  - `SystemInfoTool` (name=`system_info`, safe)

- [ ] **Step 1: 添加 httpx 依赖**

在 `pyproject.toml` 的 `dependencies` 列表中，在 `"ddgs>=7.0",` 之后添加：

```toml
    "httpx>=0.27",
```

然后同步依赖：

```
uv sync
```

- [ ] **Step 2: 写全部 6 个工具的失败测试**

新建 `tests/test_tools_utility.py`：

```python
"""六个实用工具的单元测试。"""

import os
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ─── grep_search ────────────────────────────────────────────────────────────

class TestGrepSearch:
    @pytest.mark.asyncio
    async def test_finds_matching_lines(self, tmp_path):
        from my_small_agent.tools.grep_search import GrepSearchTool
        (tmp_path / "a.txt").write_text("hello world\nfoo bar\n")
        tool = GrepSearchTool()
        result = await tool.execute(pattern="hello", path=str(tmp_path))
        assert "hello world" in result
        assert "a.txt" in result

    @pytest.mark.asyncio
    async def test_no_match_returns_message(self, tmp_path):
        from my_small_agent.tools.grep_search import GrepSearchTool
        (tmp_path / "b.txt").write_text("nothing here\n")
        tool = GrepSearchTool()
        result = await tool.execute(pattern="xyz_not_found", path=str(tmp_path))
        assert "No matches" in result

    @pytest.mark.asyncio
    async def test_regex_pattern(self, tmp_path):
        from my_small_agent.tools.grep_search import GrepSearchTool
        (tmp_path / "c.txt").write_text("def foo():\n    pass\n")
        tool = GrepSearchTool()
        result = await tool.execute(pattern=r"def \w+", path=str(tmp_path))
        assert "def foo" in result

    @pytest.mark.asyncio
    async def test_invalid_regex_returns_error(self, tmp_path):
        from my_small_agent.tools.grep_search import GrepSearchTool
        tool = GrepSearchTool()
        result = await tool.execute(pattern="[invalid", path=str(tmp_path))
        assert "Invalid regex" in result

    def test_metadata(self):
        from my_small_agent.tools.grep_search import GrepSearchTool
        tool = GrepSearchTool()
        assert tool.name == "grep_search"
        assert tool.danger_level == "safe"
        assert "pattern" in tool.parameters["properties"]


# ─── fetch_url ──────────────────────────────────────────────────────────────

class TestFetchUrl:
    @pytest.mark.asyncio
    async def test_fetches_and_strips_html(self):
        from my_small_agent.tools.fetch_url import FetchUrlTool
        import httpx

        mock_response = MagicMock()
        mock_response.text = "<html><body><p>Hello World</p></body></html>"
        mock_response.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.get = AsyncMock(return_value=mock_response)

        with patch("my_small_agent.tools.fetch_url.httpx.AsyncClient", return_value=mock_client):
            tool = FetchUrlTool()
            result = await tool.execute(url="https://example.com")

        assert "Hello World" in result
        assert "<p>" not in result  # HTML 标签应被移除

    @pytest.mark.asyncio
    async def test_timeout_returns_error(self):
        from my_small_agent.tools.fetch_url import FetchUrlTool
        import httpx

        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.get = AsyncMock(side_effect=httpx.TimeoutException("timeout"))

        with patch("my_small_agent.tools.fetch_url.httpx.AsyncClient", return_value=mock_client):
            tool = FetchUrlTool()
            result = await tool.execute(url="https://example.com")

        assert "timed out" in result.lower() or "timeout" in result.lower()

    def test_metadata(self):
        from my_small_agent.tools.fetch_url import FetchUrlTool
        tool = FetchUrlTool()
        assert tool.name == "fetch_url"
        assert tool.danger_level == "safe"
        assert "url" in tool.parameters["properties"]


# ─── tree ────────────────────────────────────────────────────────────────────

class TestTree:
    @pytest.mark.asyncio
    async def test_shows_directory_structure(self, tmp_path):
        from my_small_agent.tools.tree import TreeTool
        (tmp_path / "src").mkdir()
        (tmp_path / "src" / "main.py").write_text("")
        (tmp_path / "README.md").write_text("")
        tool = TreeTool()
        result = await tool.execute(path=str(tmp_path))
        assert "src" in result
        assert "main.py" in result
        assert "README.md" in result

    @pytest.mark.asyncio
    async def test_respects_max_depth(self, tmp_path):
        from my_small_agent.tools.tree import TreeTool
        deep = tmp_path / "a" / "b" / "c"
        deep.mkdir(parents=True)
        (deep / "deep.txt").write_text("")
        tool = TreeTool()
        result = await tool.execute(path=str(tmp_path), max_depth=1)
        assert "a" in result
        assert "deep.txt" not in result

    @pytest.mark.asyncio
    async def test_nonexistent_path_returns_error(self):
        from my_small_agent.tools.tree import TreeTool
        tool = TreeTool()
        result = await tool.execute(path="/nonexistent/path/xyz")
        assert "Error" in result

    def test_metadata(self):
        from my_small_agent.tools.tree import TreeTool
        tool = TreeTool()
        assert tool.name == "tree"
        assert tool.danger_level == "safe"


# ─── find_file ───────────────────────────────────────────────────────────────

class TestFindFile:
    @pytest.mark.asyncio
    async def test_finds_matching_files(self, tmp_path):
        from my_small_agent.tools.find_file import FindFileTool
        (tmp_path / "config.json").write_text("{}")
        (tmp_path / "main.py").write_text("")
        sub = tmp_path / "sub"
        sub.mkdir()
        (sub / "settings.json").write_text("{}")
        tool = FindFileTool()
        result = await tool.execute(pattern="*.json", path=str(tmp_path))
        assert "config.json" in result
        assert "settings.json" in result
        assert "main.py" not in result

    @pytest.mark.asyncio
    async def test_no_match_returns_message(self, tmp_path):
        from my_small_agent.tools.find_file import FindFileTool
        (tmp_path / "only.txt").write_text("")
        tool = FindFileTool()
        result = await tool.execute(pattern="*.xyz", path=str(tmp_path))
        assert "No files found" in result

    def test_metadata(self):
        from my_small_agent.tools.find_file import FindFileTool
        tool = FindFileTool()
        assert tool.name == "find_file"
        assert tool.danger_level == "safe"
        assert "pattern" in tool.parameters["properties"]


# ─── file_delete ─────────────────────────────────────────────────────────────

class TestFileDelete:
    @pytest.mark.asyncio
    async def test_deletes_existing_file(self, tmp_path):
        from my_small_agent.tools.file_delete import DeleteFileTool
        target = tmp_path / "to_delete.txt"
        target.write_text("bye")
        tool = DeleteFileTool()
        result = await tool.execute(path=str(target))
        assert "Successfully deleted" in result
        assert not target.exists()

    @pytest.mark.asyncio
    async def test_nonexistent_file_returns_error(self, tmp_path):
        from my_small_agent.tools.file_delete import DeleteFileTool
        tool = DeleteFileTool()
        result = await tool.execute(path=str(tmp_path / "ghost.txt"))
        assert "not found" in result.lower() or "Error" in result

    @pytest.mark.asyncio
    async def test_directory_returns_error(self, tmp_path):
        from my_small_agent.tools.file_delete import DeleteFileTool
        d = tmp_path / "mydir"
        d.mkdir()
        tool = DeleteFileTool()
        result = await tool.execute(path=str(d))
        assert "directory" in result.lower() or "Error" in result

    def test_metadata(self):
        from my_small_agent.tools.file_delete import DeleteFileTool
        tool = DeleteFileTool()
        assert tool.name == "file_delete"
        assert tool.danger_level == "dangerous"


# ─── system_info ─────────────────────────────────────────────────────────────

class TestSystemInfo:
    @pytest.mark.asyncio
    async def test_returns_os_and_python(self):
        from my_small_agent.tools.system_info import SystemInfoTool
        tool = SystemInfoTool()
        result = await tool.execute()
        assert "OS" in result
        assert "Python" in result
        assert "CWD" in result

    @pytest.mark.asyncio
    async def test_python_version_matches(self):
        from my_small_agent.tools.system_info import SystemInfoTool
        tool = SystemInfoTool()
        result = await tool.execute()
        major_minor = f"{sys.version_info.major}.{sys.version_info.minor}"
        assert major_minor in result

    def test_metadata(self):
        from my_small_agent.tools.system_info import SystemInfoTool
        tool = SystemInfoTool()
        assert tool.name == "system_info"
        assert tool.danger_level == "safe"
```

- [ ] **Step 3: 运行测试确认失败**

```
uv run pytest tests/test_tools_utility.py -v
```

期望：全部 FAIL，所有工具模块不存在。

- [ ] **Step 4: 创建 grep_search.py**

新建 `my_small_agent/tools/grep_search.py`：

```python
"""
grep_search 工具 - 递归搜索项目文件内容。

安全级别：safe（只读操作，不修改文件系统）
"""

import re
from pathlib import Path

from my_small_agent.tools.base import Tool


class GrepSearchTool(Tool):
    """按关键词或正则表达式递归搜索目录下所有文件的内容。"""

    name = "grep_search"
    description = (
        "Recursively search file contents for a keyword or regex pattern. "
        "Returns matching lines with file path and line number."
    )

    parameters = {
        "type": "object",
        "properties": {
            "pattern": {
                "type": "string",
                "description": "Keyword or regex pattern to search for.",
            },
            "path": {
                "type": "string",
                "description": "Directory to search in (default: current directory).",
                "default": ".",
            },
            "file_pattern": {
                "type": "string",
                "description": "Glob pattern to filter file names, e.g. '*.py' (default: '*').",
                "default": "*",
            },
            "ignore_case": {
                "type": "boolean",
                "description": "Case-insensitive search (default: false).",
                "default": False,
            },
            "max_results": {
                "type": "integer",
                "description": "Maximum number of results to return (default: 50).",
                "default": 50,
            },
        },
        "required": ["pattern"],
    }

    danger_level = "safe"

    async def execute(self, **kwargs) -> str:
        pattern = kwargs["pattern"]
        path = kwargs.get("path", ".")
        file_pattern = kwargs.get("file_pattern", "*")
        ignore_case = kwargs.get("ignore_case", False)
        max_results = kwargs.get("max_results", 50)

        flags = re.IGNORECASE if ignore_case else 0
        try:
            regex = re.compile(pattern, flags)
        except re.error as e:
            return f"Invalid regex pattern: {e}"

        root = Path(path)
        if not root.exists():
            return f"Error: Path '{path}' does not exist"

        results: list[str] = []
        for file_path in sorted(root.rglob(file_pattern)):
            if not file_path.is_file():
                continue
            try:
                content = file_path.read_text(encoding="utf-8", errors="replace")
                for lineno, line in enumerate(content.splitlines(), 1):
                    if regex.search(line):
                        results.append(f"{file_path}:{lineno}: {line.rstrip()}")
                        if len(results) >= max_results:
                            results.append(f"... (truncated at {max_results} results)")
                            return "\n".join(results)
            except Exception:
                continue

        if not results:
            return f"No matches found for pattern '{pattern}'"
        return "\n".join(results)
```

- [ ] **Step 5: 创建 fetch_url.py**

新建 `my_small_agent/tools/fetch_url.py`：

```python
"""
fetch_url 工具 - 获取 URL 内容并提取纯文本。

安全级别：safe（只读网络请求）
依赖：httpx（异步 HTTP 客户端）
"""

import html
import re

import httpx

from my_small_agent.tools.base import Tool


class FetchUrlTool(Tool):
    """获取指定 URL 的网页内容并提取纯文本（去除 HTML 标签）。"""

    name = "fetch_url"
    description = "Fetch the content of a URL and extract plain text, stripping HTML tags."

    parameters = {
        "type": "object",
        "properties": {
            "url": {
                "type": "string",
                "description": "The URL to fetch.",
            },
            "timeout": {
                "type": "integer",
                "description": "Request timeout in seconds (default: 15).",
                "default": 15,
            },
        },
        "required": ["url"],
    }

    danger_level = "safe"

    async def execute(self, **kwargs) -> str:
        url = kwargs["url"]
        timeout = kwargs.get("timeout", 15)
        try:
            async with httpx.AsyncClient(
                timeout=timeout, follow_redirects=True
            ) as client:
                response = await client.get(
                    url, headers={"User-Agent": "Mozilla/5.0 (compatible; MySmallAgent/1.0)"}
                )
                response.raise_for_status()
                text = response.text

            # 移除 <script> 和 <style> 标签及其内容
            text = re.sub(
                r"<(script|style)[^>]*>.*?</(script|style)>",
                " ",
                text,
                flags=re.DOTALL | re.IGNORECASE,
            )
            # 移除所有 HTML 标签
            text = re.sub(r"<[^>]+>", " ", text)
            # 解码 HTML 实体（&amp; &lt; 等）
            text = html.unescape(text)
            # 合并空白字符
            text = re.sub(r"\s+", " ", text).strip()
            # 截断过长内容
            if len(text) > 8000:
                text = text[:8000] + "\n...(内容已截断)"
            return text or "(空内容)"

        except httpx.TimeoutException:
            return f"Error: Request timed out after {timeout} seconds"
        except httpx.HTTPStatusError as e:
            return f"Error: HTTP {e.response.status_code} for {url}"
        except Exception as e:
            return f"Error fetching URL: {e}"
```

- [ ] **Step 6: 创建 tree.py**

新建 `my_small_agent/tools/tree.py`：

```python
"""
tree 工具 - 递归展示目录树结构。

安全级别：safe（只读操作）
"""

from pathlib import Path

from my_small_agent.tools.base import Tool


class TreeTool(Tool):
    """递归展示指定目录的树状结构（类似 Unix tree 命令）。"""

    name = "tree"
    description = "Display directory structure as a tree. Similar to the Unix 'tree' command."

    parameters = {
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "Root directory path (default: current directory).",
                "default": ".",
            },
            "max_depth": {
                "type": "integer",
                "description": "Maximum depth to display (default: 3).",
                "default": 3,
            },
            "show_hidden": {
                "type": "boolean",
                "description": "Show hidden files and directories starting with '.' (default: false).",
                "default": False,
            },
        },
        "required": [],
    }

    danger_level = "safe"

    async def execute(self, **kwargs) -> str:
        path = kwargs.get("path", ".")
        max_depth = kwargs.get("max_depth", 3)
        show_hidden = kwargs.get("show_hidden", False)

        root = Path(path)
        if not root.exists():
            return f"Error: Path '{path}' does not exist"

        lines: list[str] = [str(root)]
        self._build_tree(root, lines, "", 0, max_depth, show_hidden)
        return "\n".join(lines)

    def _build_tree(
        self,
        path: Path,
        lines: list[str],
        prefix: str,
        depth: int,
        max_depth: int,
        show_hidden: bool,
    ) -> None:
        if depth >= max_depth:
            return
        try:
            # 目录排前，同类按名称排序
            entries = sorted(
                path.iterdir(), key=lambda x: (x.is_file(), x.name.lower())
            )
        except PermissionError:
            return

        if not show_hidden:
            entries = [e for e in entries if not e.name.startswith(".")]

        for i, entry in enumerate(entries):
            is_last = i == len(entries) - 1
            connector = "└── " if is_last else "├── "
            lines.append(f"{prefix}{connector}{entry.name}")
            if entry.is_dir():
                extension = "    " if is_last else "│   "
                self._build_tree(
                    entry, lines, prefix + extension, depth + 1, max_depth, show_hidden
                )
```

- [ ] **Step 7: 创建 find_file.py**

新建 `my_small_agent/tools/find_file.py`：

```python
"""
find_file 工具 - 按 glob 模式递归搜索文件。

安全级别：safe（只读操作）
"""

from pathlib import Path

from my_small_agent.tools.base import Tool


class FindFileTool(Tool):
    """按文件名 glob 模式在目录中递归搜索文件。"""

    name = "find_file"
    description = (
        "Recursively search for files matching a glob pattern (e.g. '*.py', 'config*.json')."
    )

    parameters = {
        "type": "object",
        "properties": {
            "pattern": {
                "type": "string",
                "description": "Glob pattern to match file names, e.g. '*.py', 'config*.json'.",
            },
            "path": {
                "type": "string",
                "description": "Root directory to search from (default: current directory).",
                "default": ".",
            },
            "max_results": {
                "type": "integer",
                "description": "Maximum number of results to return (default: 50).",
                "default": 50,
            },
        },
        "required": ["pattern"],
    }

    danger_level = "safe"

    async def execute(self, **kwargs) -> str:
        pattern = kwargs["pattern"]
        path = kwargs.get("path", ".")
        max_results = kwargs.get("max_results", 50)

        root = Path(path)
        if not root.exists():
            return f"Error: Path '{path}' does not exist"

        results: list[str] = []
        for match in sorted(root.rglob(pattern)):
            results.append(str(match))
            if len(results) >= max_results:
                results.append(f"... (truncated at {max_results} results)")
                break

        if not results:
            return f"No files found matching '{pattern}'"
        return "\n".join(results)
```

- [ ] **Step 8: 创建 file_delete.py**

新建 `my_small_agent/tools/file_delete.py`：

```python
"""
file_delete 工具 - 删除指定路径的文件。

安全级别：dangerous（破坏性操作，执行前需用户确认）
"""

from pathlib import Path

from my_small_agent.tools.base import Tool


class DeleteFileTool(Tool):
    """删除指定路径的文件（不支持删除目录）。"""

    name = "file_delete"
    description = "Delete a file at the specified path. Directories are not supported."

    parameters = {
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "The path to the file to delete.",
            },
        },
        "required": ["path"],
    }

    danger_level = "dangerous"

    async def execute(self, **kwargs) -> str:
        path = Path(kwargs["path"])
        try:
            if not path.exists():
                return f"Error: File not found: {path}"
            if path.is_dir():
                return f"Error: '{path}' is a directory, not a file. Use shell commands to remove directories."
            path.unlink()
            return f"Successfully deleted: {path}"
        except PermissionError:
            return f"Error: Permission denied: {path}"
        except Exception as e:
            return f"Error deleting file: {e}"
```

- [ ] **Step 9: 创建 system_info.py**

新建 `my_small_agent/tools/system_info.py`：

```python
"""
system_info 工具 - 获取当前运行环境信息。

安全级别：safe（只读操作）
"""

import os
import platform
import sys
from pathlib import Path

from my_small_agent.tools.base import Tool


class SystemInfoTool(Tool):
    """获取当前系统和运行时环境的关键信息，帮助 LLM 做出合理决策。"""

    name = "system_info"
    description = (
        "Get current system and runtime environment information "
        "(OS, Python version, working directory, etc.)."
    )

    parameters = {
        "type": "object",
        "properties": {},
        "required": [],
    }

    danger_level = "safe"

    async def execute(self, **kwargs) -> str:
        info = {
            "OS": f"{platform.system()} {platform.release()} ({platform.machine()})",
            "Python": sys.version.split()[0],
            "CWD": str(Path.cwd()),
            "Home": str(Path.home()),
            "Shell": os.environ.get("SHELL") or os.environ.get("COMSPEC", "unknown"),
            "PATH entries": str(len(os.environ.get("PATH", "").split(os.pathsep))),
        }
        return "\n".join(f"{k}: {v}" for k, v in info.items())
```

- [ ] **Step 10: 在 tools/__init__.py 注册 6 个新工具**

在 `my_small_agent/tools/__init__.py` 中，在现有 import 块末尾添加新导入：

```python
from my_small_agent.tools.grep_search import GrepSearchTool
from my_small_agent.tools.fetch_url import FetchUrlTool
from my_small_agent.tools.tree import TreeTool
from my_small_agent.tools.find_file import FindFileTool
from my_small_agent.tools.file_delete import DeleteFileTool
from my_small_agent.tools.system_info import SystemInfoTool
```

在 `create_default_registry` 函数的 `registry.register(CurrentTimeTool(...))` 行之后添加：

```python
    registry.register(GrepSearchTool())
    registry.register(FetchUrlTool())
    registry.register(TreeTool())
    registry.register(FindFileTool())
    registry.register(DeleteFileTool())
    registry.register(SystemInfoTool())
```

同时更新 `create_default_registry` 的文档注释，在"内置工具"列表末尾追加：

```
      - grep_search:     递归搜索文件内容（安全）
      - fetch_url:       获取URL纯文本（安全）
      - tree:            展示目录树（安全）
      - find_file:       按glob搜索文件（安全）
      - file_delete:     删除文件（危险，需确认）
      - system_info:     获取系统信息（安全）
```

- [ ] **Step 11: 同时更新 agent.py 的 SYSTEM_PROMPT**

在 `agent.py` 的 `SYSTEM_PROMPT` 的"你的能力"列表末尾，将：

```
- 查询当前时间
```

替换为：

```
- 查询当前时间
- 搜索文件内容（grep_search）、获取网页内容（fetch_url）
- 展示目录树（tree）、按名称查找文件（find_file）
- 删除文件（file_delete）、获取系统信息（system_info）
```

- [ ] **Step 12: 运行工具测试确认通过**

```
uv run pytest tests/test_tools_utility.py -v
```

期望：全部 PASS。

- [ ] **Step 13: 运行全量测试**

```
uv run pytest tests/ -v
```

期望：全部 PASS。

- [ ] **Step 14: 提交**

```
git add my_small_agent/tools/grep_search.py my_small_agent/tools/fetch_url.py
git add my_small_agent/tools/tree.py my_small_agent/tools/find_file.py
git add my_small_agent/tools/file_delete.py my_small_agent/tools/system_info.py
git add my_small_agent/tools/__init__.py my_small_agent/agent.py
git add pyproject.toml uv.lock tests/test_tools_utility.py
git commit -m "feat(tools): 新增 grep_search/fetch_url/tree/find_file/file_delete/system_info 六个工具"
```

---

## 自检（Spec Coverage）

| 需求 | 实现任务 |
|------|----------|
| Token 估算 chars/4 算法 | Task 2 Step 3 |
| /status 展示 Token usage | Task 2 Step 5 |
| max_context_tokens 配置项 | Task 1 Step 3 |
| 自动压缩 @ 80% 阈值 | Task 4 Step 4 |
| 压缩算法保留头3尾20 | Task 3 Step 3 |
| LLM 结构化摘要模板 | Task 3 Step 3 |
| /compact 命令 | Task 4 Step 1-3 |
| /compact 消息数检查 (>23) | Task 4 Step 2 |
| /compact 显示压缩前后对比 | Task 4 Step 2 |
| head_keep/tail_keep/compression_threshold 配置项 | Task 1 Step 3 |
| grep_search 工具 | Task 5 Step 4 |
| fetch_url 工具 | Task 5 Step 5 |
| tree 工具 | Task 5 Step 6 |
| find_file 工具 | Task 5 Step 7 |
| file_delete 工具 | Task 5 Step 8 |
| system_info 工具 | Task 5 Step 9 |
