# QQ 机器人接入实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 为 MySmallAgent 增加 QQ 私聊前端：通过官方 botpy SDK（WebSocket Gateway + REST API v2）接入 QQ 开放平台，用户在 QQ 客户端与机器人私聊即可驱动 Agent。

**Architecture:** 新增 `qq_bot.py` 作为与 `cli.py` 平级的常驻桥接进程（无界面）：botpy WebSocket 收 C2C 私聊消息 → 单 Agent 实例 `run_turn()` → C2C 被动回复（带原 msg_id、分段发送）。组装链复用 `__main__.py` 模式；Agent 核心零改动。设计文档：`docs/superpowers/specs/2026-07-23-qq-bot-integration-design.md`。

**Tech Stack:** qq-botpy≥1.1.5（import 名 botpy）、asyncio、pytest + pytest-asyncio、uv

## Global Constraints

- Python ≥ 3.11；依赖变更后必须先 `uv sync` 再 `uv run ...`
- 测试运行命令统一 `uv run pytest <path> -v`；async 测试函数**无需装饰器**（pyproject 已配 `asyncio_mode = "auto"`）
- 修改已有文件一律增量编辑，禁止整文件覆写；新文件注释用中文，匹配现有模块 docstring 风格
- Windows PowerShell：命令分隔用 `;` 不用 `&&`
- botpy 事件回调方法**不写类型注解**（botpy 按方法名分发，duck typing；测试用 `SimpleNamespace` 构造消息）
- QQ 侧不使用流式（`run_turn_stream`）、不发送 thinking 内容、不提供斜杠命令
- 被动回复必须携带原消息 `msg_id`；单条事件消息被动回复 ≤4 次（占位 1 + 正文 ≤3 段）

---

### Task 1: 依赖与配置层扩展

**Files:**
- Modify: `pyproject.toml`
- Modify: `my_small_agent/config.py`
- Modify: `.env.example`
- Test: `tests/test_config.py`

**Interfaces:**
- Consumes: 现有 `Settings`（pydantic-settings，env 前缀即字段名大写）
- Produces: `Settings.qq_appid: str = ""`、`Settings.qq_appsecret: str = ""`、`Settings.qq_allowed_users: str = ""`（后续 Task 2/5 使用）

- [ ] **Step 1: 写失败测试（追加到 tests/test_config.py 末尾）**

```python
def test_qq_fields_defaults(monkeypatch):
    """QQ 机器人配置项应有正确默认值（空字符串）。"""
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    settings = Settings(_env_file=None)
    assert settings.qq_appid == ""
    assert settings.qq_appsecret == ""
    assert settings.qq_allowed_users == ""


def test_qq_fields_from_env(monkeypatch):
    """QQ 机器人配置项应能从环境变量读取。"""
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.setenv("QQ_APPID", "123456789")
    monkeypatch.setenv("QQ_APPSECRET", "my-secret")
    monkeypatch.setenv("QQ_ALLOWED_USERS", "openid-a,openid-b")
    settings = Settings(_env_file=None)
    assert settings.qq_appid == "123456789"
    assert settings.qq_appsecret == "my-secret"
    assert settings.qq_allowed_users == "openid-a,openid-b"
```

- [ ] **Step 2: 运行测试确认失败**

Run: `uv run pytest tests/test_config.py -v`
Expected: 2 个新测试 FAIL（`AttributeError: 'Settings' object has no attribute 'qq_appid'`）

- [ ] **Step 3: 修改 config.py（增量编辑）**

在 `compression_threshold` 字段之后追加：

```python
    # QQ 机器人配置（仅 qq_bot.py 前端使用；CLI 模式可留空）
    qq_appid: str = ""                 # QQ 机器人 AppID（q.qq.com/qqbot/openclaw/ 创建后获取）
    qq_appsecret: str = ""             # QQ 机器人 AppSecret（仅显示一次，须立即保存）
    qq_allowed_users: str = ""         # 可选：允许的 openid 白名单（逗号分隔），空 = 不限制
```

- [ ] **Step 4: 修改 pyproject.toml（增量编辑）**

dependencies 列表末尾（`"questionary>=2.0",` 之后）追加：

```toml
    "qq-botpy>=1.1.5",
```

`[project.scripts]` 下追加：

```toml
agent-qq = "my_small_agent.qq_bot:main_entry"
```

注意：`agent-qq` 入口指向的模块 Task 5 才创建，此为正常的前向引用（pip/uv 安装 script 时不校验模块存在）。

- [ ] **Step 5: 修改 .env.example（增量编辑，末尾追加）**

```env
# QQ 机器人（可选，仅 QQ 前端 agent-qq 需要）
QQ_APPID=
QQ_APPSECRET=
QQ_ALLOWED_USERS=
```

- [ ] **Step 6: 安装依赖并运行测试确认通过**

Run: `uv sync`
Expected: 安装成功，含 `qq-botpy`

Run: `uv run pytest tests/test_config.py -v`
Expected: 全部 PASS（含 2 个新测试）

- [ ] **Step 7: Commit**

```bash
git add pyproject.toml my_small_agent/config.py .env.example tests/test_config.py uv.lock
git commit -m "feat(config): add QQ bot settings and qq-botpy dependency"
```

---

### Task 2: QQBotClient 最小消息链路

**Files:**
- Create: `my_small_agent/qq_bot.py`
- Test: `tests/test_qq_bot.py`

**Interfaces:**
- Consumes: `Settings.qq_appid/qq_appsecret/qq_allowed_users`（Task 1）；`Agent.run_turn(user_input, confirm_callback) -> AgentResponse`；`SessionManager`（本 Task 仅持有，不调用）
- Produces: `QQBotClient(agent, session_manager, settings)`；`_auto_approve(tool_name, description, arguments) -> bool`；`PLACEHOLDER_TEXT = "🤔 思考中..."`；`EMPTY_REPLY_TEXT = "(无文本回复)"`；测试 helper `make_client()` / `make_message()`（Task 3/4 复用）

- [ ] **Step 1: 写失败测试（新建 tests/test_qq_bot.py）**

```python
"""Tests for qq_bot module."""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

from my_small_agent.agent import AgentResponse
from my_small_agent.config import Settings
from my_small_agent.qq_bot import (
    PLACEHOLDER_TEXT,
    QQBotClient,
    _auto_approve,
)
from my_small_agent.session import SessionManager


def make_message(content="你好", msg_id="msg-1", openid="openid-user-1", attachments=None):
    """构造模拟 C2C 消息（duck typing：id/content/author.union_openid/attachments）。"""
    return SimpleNamespace(
        id=msg_id,
        content=content,
        author=SimpleNamespace(union_openid=openid),
        attachments=attachments,
    )


def make_client(allowed_users: str = ""):
    """构造 QQBotClient 及 mock 依赖；api 替换为 AsyncMock，全程不触网。"""
    settings = Settings(_env_file=None, openai_api_key="sk-test", qq_allowed_users=allowed_users)
    agent = MagicMock()
    agent.messages = []
    agent.session_title = ""
    agent.session_id = "test-session-id"
    agent.created_at = "2026-07-23T00:00:00+00:00"
    agent.settings = settings
    agent.estimate_tokens = MagicMock(return_value=0)
    agent.run_turn = AsyncMock(return_value=AgentResponse(content="回复内容"))
    session_manager = MagicMock(spec=SessionManager)
    client = QQBotClient(agent=agent, session_manager=session_manager, settings=settings)
    client.api = AsyncMock()
    return client, agent, session_manager


async def test_auto_approve_always_true():
    """危险工具确认回调恒返回 True。"""
    assert await _auto_approve("execute_shell", "执行命令", {"command": "dir"}) is True


async def test_text_message_triggers_run_turn_and_replies_with_msg_id():
    """文本消息驱动 run_turn，正式回复携带原 msg_id。"""
    client, agent, _ = make_client()
    await client.on_c2c_message_create(make_message(content="你好", msg_id="m-1"))
    agent.run_turn.assert_called_once()
    args, kwargs = agent.run_turn.call_args
    assert args[0] == "你好"
    assert kwargs["confirm_callback"] is _auto_approve
    client.api.post_c2c_message.assert_any_await(
        openid="openid-user-1", msg_type=0, msg_id="m-1", content="回复内容"
    )


async def test_placeholder_sent_before_reply():
    """占位消息先于正式回复发送。"""
    client, _, _ = make_client()
    await client.on_c2c_message_create(make_message())
    calls = client.api.post_c2c_message.await_args_list
    assert calls[0].kwargs["content"] == PLACEHOLDER_TEXT
    assert calls[1].kwargs["content"] == "回复内容"


async def test_blank_message_ignored():
    """纯空白文本直接忽略：不调用 run_turn、不回复。"""
    client, agent, _ = make_client()
    await client.on_c2c_message_create(make_message(content="   \n  "))
    agent.run_turn.assert_not_called()
    client.api.post_c2c_message.assert_not_called()


async def test_attachment_message_rejected_with_hint():
    """纯附件消息回复提示，不进入对话。"""
    client, agent, _ = make_client()
    msg = make_message(content="", attachments=[{"url": "http://x/y.png"}])
    await client.on_c2c_message_create(msg)
    agent.run_turn.assert_not_called()
    client.api.post_c2c_message.assert_called_once()
    assert "文字" in client.api.post_c2c_message.call_args.kwargs["content"]


async def test_allowlist_blocks_stranger():
    """配置白名单后，非白名单用户被拒绝。"""
    client, agent, _ = make_client(allowed_users="openid-user-1, openid-user-2")
    await client.on_c2c_message_create(make_message(openid="openid-stranger"))
    agent.run_turn.assert_not_called()
    client.api.post_c2c_message.assert_called_once()
    assert "仅对指定用户开放" in client.api.post_c2c_message.call_args.kwargs["content"]


async def test_allowlist_allows_member():
    """白名单内用户正常对话。"""
    client, agent, _ = make_client(allowed_users="openid-user-1, openid-user-2")
    await client.on_c2c_message_create(make_message(openid="openid-user-2"))
    agent.run_turn.assert_called_once()


async def test_run_turn_exception_replied():
    """run_turn 抛异常时回复错误提示，不崩溃。"""
    client, agent, _ = make_client()
    agent.run_turn = AsyncMock(side_effect=RuntimeError("boom"))
    await client.on_c2c_message_create(make_message())
    contents = [c.kwargs["content"] for c in client.api.post_c2c_message.await_args_list]
    assert any("处理出错" in c for c in contents)


async def test_messages_processed_serially():
    """并发到达的两条消息串行处理（第二条等第一条完成）。"""
    client, agent, _ = make_client()
    order = []

    async def slow_turn(text, confirm_callback):
        order.append(f"start:{text}")
        await asyncio.sleep(0.05)
        order.append(f"end:{text}")
        return AgentResponse(content=f"回复:{text}")

    agent.run_turn = AsyncMock(side_effect=slow_turn)
    await asyncio.gather(
        client.on_c2c_message_create(make_message(content="第一条", msg_id="m1")),
        client.on_c2c_message_create(make_message(content="第二条", msg_id="m2")),
    )
    assert order == ["start:第一条", "end:第一条", "start:第二条", "end:第二条"]
```

- [ ] **Step 2: 运行测试确认失败**

Run: `uv run pytest tests/test_qq_bot.py -v`
Expected: 收集失败或全部 FAIL（`ModuleNotFoundError: No module named 'my_small_agent.qq_bot'`）

- [ ] **Step 3: 实现 my_small_agent/qq_bot.py（新建）**

```python
"""
QQ 机器人前端 - 通过 QQ 开放平台官方 API 接入私聊对话。

这是与 cli.py 平级的另一种 Agent 前端（常驻后台的消息桥接进程，无用户界面）：
  - 用户在 QQ 客户端内与机器人私聊，本进程负责 QQ 服务器 ↔ Agent 的消息搬运
  - 收消息：botpy WebSocket Gateway（出站长连接，无需公网 IP）
  - 发消息：官方 REST API v2 被动回复（必须携带原消息 msg_id）
  - 单会话架构：单个常驻 Agent 实例，记忆/压缩/技能全部生效
  - 危险工具自动批准（confirm_callback 恒 True，仅机器人创建者本人使用）
"""

import asyncio

import botpy
from botpy import logger

from my_small_agent.agent import Agent
from my_small_agent.config import Settings
from my_small_agent.session import SessionManager

# 占位反馈文本（LLM + 工具调用耗时较长时让用户感知处理中）
PLACEHOLDER_TEXT = "🤔 思考中..."
# LLM 返回空文本时的兜底提示
EMPTY_REPLY_TEXT = "(无文本回复)"


async def _auto_approve(tool_name: str, description: str, arguments: dict) -> bool:
    """危险工具确认回调：QQ 场景仅创建者本人使用，一律自动批准。"""
    return True


class QQBotClient(botpy.Client):
    """
    QQ 私聊前端。继承 botpy.Client，持有 Agent 实例。

    消息处理模型：
      - asyncio.Lock 串行化：用户连发多条消息时逐条排队，不交错、不丢弃
      - 每条消息先回占位（思考中...），再回正式回复
    """

    def __init__(self, agent: Agent, session_manager: SessionManager, settings: Settings) -> None:
        intents = botpy.Intents(public_guild_messages=True)
        # ext_handlers=False：关闭 botpy 默认的文件日志 handler，仅保留控制台输出
        super().__init__(intents=intents, ext_handlers=False)
        self.agent = agent
        self.session_manager = session_manager
        self.settings = settings
        self._lock = asyncio.Lock()
        # openid 白名单（空集合 = 不限制）
        self._allowed_users: set[str] = {
            u.strip() for u in settings.qq_allowed_users.split(",") if u.strip()
        }

    async def on_ready(self) -> None:
        """WebSocket 连接建立后触发。"""
        logger.info(f"QQ 机器人已就绪：{self.robot.name}")

    async def on_c2c_message_create(self, message) -> None:
        """
        C2C 私聊消息入口。过滤顺序：白名单 → 空文本/附件 → 锁内处理。

        message 关键属性（duck typing）：
          id                    消息 ID（被动回复必须携带）
          content               文本内容
          author.union_openid   发送者 openid
          attachments           附件列表（图片等，可能不存在）
        """
        openid = message.author.union_openid
        content = (message.content or "").strip()

        # 白名单检查：非白名单用户拒绝
        if self._allowed_users and openid not in self._allowed_users:
            await self.api.post_c2c_message(
                openid=openid, msg_type=0, msg_id=message.id,
                content="抱歉，本机器人仅对指定用户开放。",
            )
            return

        # 空文本处理：附件消息给提示；纯空白文本直接忽略（不消耗被动回复次数）
        if not content:
            if getattr(message, "attachments", None):
                await self.api.post_c2c_message(
                    openid=openid, msg_type=0, msg_id=message.id,
                    content="暂只支持文字消息。",
                )
            return

        async with self._lock:
            await self._handle_message(message, openid, content)

    async def _handle_message(self, message, openid: str, content: str) -> None:
        """锁内处理一条消息：占位 → 对话 → 回复。"""
        # 1. 占位反馈（失败不阻塞主流程）
        try:
            await self.api.post_c2c_message(
                openid=openid, msg_type=0, msg_id=message.id, content=PLACEHOLDER_TEXT
            )
        except Exception as e:
            logger.warning(f"占位消息发送失败：{e}")

        # 2. 执行对话（thinking 内容不回传 QQ，仅使用 content）
        try:
            response = await self.agent.run_turn(content, confirm_callback=_auto_approve)
        except Exception as e:
            logger.error(f"run_turn 处理异常：{e}")
            await self._reply(message, openid, f"处理出错：{e}")
            return

        # 3. 发送正式回复（失败仅记日志，继续保存会话，保持历史连续）
        try:
            await self._reply(message, openid, response.content)
        except Exception as e:
            logger.error(f"回复发送失败：{e}")

    async def _reply(self, message, openid: str, content: str) -> None:
        """发送回复，始终携带原消息 msg_id（被动回复）。"""
        await self.api.post_c2c_message(
            openid=openid, msg_type=0, msg_id=message.id,
            content=content or EMPTY_REPLY_TEXT,
        )
```

- [ ] **Step 4: 运行测试确认通过**

Run: `uv run pytest tests/test_qq_bot.py -v`
Expected: 9 个测试全部 PASS

- [ ] **Step 5: 运行全量测试确认无回归**

Run: `uv run pytest -v`
Expected: 全部 PASS

- [ ] **Step 6: Commit**

```bash
git add my_small_agent/qq_bot.py tests/test_qq_bot.py
git commit -m "feat(qq): add QQBotClient with minimal C2C message pipeline"
```

---

### Task 3: 长回复分段发送算法

**Files:**
- Modify: `my_small_agent/qq_bot.py`
- Test: `tests/test_qq_bot.py`

**Interfaces:**
- Consumes: `QQBotClient._reply`（Task 2 初版，本 Task 升级）
- Produces: `SEGMENT_LEN = 1800`、`MAX_SEGMENTS = 3`、`TRUNCATED_SUFFIX = "\n…(回复过长已截断)"`、`_split_segments(content: str) -> list[str]`（模块级纯函数）

- [ ] **Step 1: 写失败测试（追加到 tests/test_qq_bot.py 末尾）**

import 区追加：

```python
from my_small_agent.qq_bot import (
    MAX_SEGMENTS,
    SEGMENT_LEN,
    _split_segments,
)
```

测试函数：

```python
def test_split_short_content_single_segment():
    """短内容不分段。"""
    assert _split_segments("短回复") == ["短回复"]


def test_split_empty_content():
    """空内容返回固定兜底提示。"""
    assert _split_segments("") == ["(无文本回复)"]


def test_split_long_content_prefers_newline():
    """长内容优先在换行处断开。"""
    content = "a" * 1000 + "\n" + "b" * 2000
    segments = _split_segments(content)
    assert segments[0] == "a" * 1000
    assert segments[1].startswith("b")


def test_split_hard_cut_without_newline():
    """无换行时在 SEGMENT_LEN 处硬切。"""
    content = "a" * (SEGMENT_LEN + 100)
    segments = _split_segments(content)
    assert len(segments[0]) == SEGMENT_LEN
    assert segments[1] == "a" * 100


def test_split_truncates_beyond_max_segments():
    """超出 MAX_SEGMENTS 的内容截断并附提示，末段不超长。"""
    content = "a" * (SEGMENT_LEN * MAX_SEGMENTS + 500)
    segments = _split_segments(content)
    assert len(segments) == MAX_SEGMENTS
    assert segments[-1].endswith("…(回复过长已截断)")
    assert len(segments[-1]) <= SEGMENT_LEN


async def test_long_reply_sent_in_segments_with_msg_id():
    """集成：长回复分段发送，每段均携带原 msg_id。"""
    client, agent, _ = make_client()
    agent.run_turn = AsyncMock(return_value=AgentResponse(content="a" * 4000))
    await client.on_c2c_message_create(make_message())
    calls = client.api.post_c2c_message.await_args_list
    assert calls[0].kwargs["content"] == PLACEHOLDER_TEXT
    body = [c.kwargs["content"] for c in calls[1:]]
    assert len(body) == 3  # 4000 字 → 1800 + 1800 + 400
    assert all(len(s) <= SEGMENT_LEN for s in body)
    assert all(c.kwargs["msg_id"] == "msg-1" for c in calls)
```

- [ ] **Step 2: 运行测试确认失败**

Run: `uv run pytest tests/test_qq_bot.py -v`
Expected: 新测试 FAIL（`ImportError: cannot import name 'MAX_SEGMENTS'` 或断言失败）

- [ ] **Step 3: 修改 qq_bot.py（增量编辑）**

常量区（`EMPTY_REPLY_TEXT` 之后）追加：

```python
# 分段发送参数：QQ 单条 C2C 文本上限约 2000 字，预留余量取 1800
SEGMENT_LEN = 1800
# 单条事件消息被动回复次数有限（占位 1 次 + 正文最多 3 段 = 4 次）
MAX_SEGMENTS = 3
# 超出 MAX_SEGMENTS 时的截断提示
TRUNCATED_SUFFIX = "\n…(回复过长已截断)"
```

`_auto_approve` 函数之后追加模块级纯函数：

```python
def _split_segments(content: str) -> list[str]:
    """
    将长回复切分为 ≤SEGMENT_LEN 的分段，最多 MAX_SEGMENTS 段。

    切分优先在换行处断开；找不到换行则硬切。
    超出 MAX_SEGMENTS 的内容截断，末段附加截断提示。
    空内容返回固定兜底提示。
    """
    if not content:
        return [EMPTY_REPLY_TEXT]
    segments: list[str] = []
    remaining = content
    truncated = False
    while remaining:
        if len(segments) >= MAX_SEGMENTS:
            truncated = True
            break
        if len(remaining) <= SEGMENT_LEN:
            segments.append(remaining)
            break
        cut = remaining.rfind("\n", 0, SEGMENT_LEN)
        if cut <= 0:
            cut = SEGMENT_LEN
        segments.append(remaining[:cut])
        remaining = remaining[cut:].lstrip("\n")
    if truncated:
        segments[-1] = segments[-1][: SEGMENT_LEN - len(TRUNCATED_SUFFIX)] + TRUNCATED_SUFFIX
    return segments
```

`_reply` 方法整体替换为：

```python
    async def _reply(self, message, openid: str, content: str) -> None:
        """分段发送回复，每段均携带原消息 msg_id（被动回复）。"""
        for segment in _split_segments(content):
            await self.api.post_c2c_message(
                openid=openid, msg_type=0, msg_id=message.id, content=segment
            )
```

- [ ] **Step 4: 运行测试确认通过**

Run: `uv run pytest tests/test_qq_bot.py -v`
Expected: 全部 PASS（含 6 个新测试）

- [ ] **Step 5: Commit**

```bash
git add my_small_agent/qq_bot.py tests/test_qq_bot.py
git commit -m "feat(qq): split long replies into segments within passive-reply quota"
```

---

### Task 4: 会话持久化与自动压缩接入

**Files:**
- Modify: `my_small_agent/qq_bot.py`
- Test: `tests/test_qq_bot.py`

**Interfaces:**
- Consumes: `SessionManager.save(session_id=..., title=..., created_at=..., messages=...)`；`Agent.estimate_tokens()`；`Agent.compact_context() -> tuple[int, int]`；`Agent.session_title/session_id/created_at/messages`；判定逻辑与 `cli.py:_auto_compact_if_needed` 一致
- Produces: `QQBotClient._save_session()`、`QQBotClient._auto_compact_if_needed() -> bool`

- [ ] **Step 1: 写失败测试（追加到 tests/test_qq_bot.py 末尾）**

```python
async def test_session_saved_after_turn():
    """对话完成后保存会话；title 取首条 user 消息。"""
    client, agent, session_manager = make_client()

    async def fake_turn(text, confirm_callback):
        agent.messages.append({"role": "user", "content": text})
        agent.messages.append({"role": "assistant", "content": "回复内容"})
        return AgentResponse(content="回复内容")

    agent.run_turn = AsyncMock(side_effect=fake_turn)
    await client.on_c2c_message_create(make_message(content="你好"))
    session_manager.save.assert_called_once()
    kwargs = session_manager.save.call_args.kwargs
    assert kwargs["session_id"] == "test-session-id"
    assert kwargs["title"] == "你好"
    assert kwargs["created_at"] == "2026-07-23T00:00:00+00:00"
    assert len(kwargs["messages"]) == 2


async def test_session_save_filters_system_messages():
    """保存的 messages 不含 system prompt。"""
    client, agent, session_manager = make_client()
    agent.messages = [{"role": "system", "content": "sys"}]

    async def fake_turn(text, confirm_callback):
        agent.messages.append({"role": "user", "content": text})
        return AgentResponse(content="回复内容")

    agent.run_turn = AsyncMock(side_effect=fake_turn)
    await client.on_c2c_message_create(make_message())
    messages = session_manager.save.call_args.kwargs["messages"]
    assert all(m["role"] != "system" for m in messages)


async def test_reply_failure_still_saves_session():
    """正式回复发送失败仍保存会话（对话历史连续）。"""
    client, agent, session_manager = make_client()
    # 第一次调用（占位）成功，第二次（正式回复）抛网络异常
    client.api.post_c2c_message = AsyncMock(
        side_effect=[None, RuntimeError("network error")]
    )
    await client.on_c2c_message_create(make_message())
    session_manager.save.assert_called_once()


async def test_session_save_failure_does_not_break():
    """保存失败不中断对话流程。"""
    client, _, session_manager = make_client()
    session_manager.save.side_effect = OSError("disk full")
    await client.on_c2c_message_create(make_message())
    client.api.post_c2c_message.assert_any_await(
        openid="openid-user-1", msg_type=0, msg_id="msg-1", content="回复内容"
    )


async def test_auto_compact_triggered_over_threshold():
    """token 超阈值且消息数足够时触发自动压缩。"""
    client, agent, _ = make_client()
    agent.messages = [{"role": "user", "content": "x"}] * 30  # > head_keep(3)+tail_keep(20)
    agent.estimate_tokens = MagicMock(return_value=2_000_000)  # >= 0.8 * 2_000_000
    agent.compact_context = AsyncMock(return_value=(30, 10))
    await client.on_c2c_message_create(make_message())
    agent.compact_context.assert_called_once()


async def test_auto_compact_skipped_below_threshold():
    """token 未达阈值时不压缩。"""
    client, agent, _ = make_client()
    agent.compact_context = AsyncMock()
    await client.on_c2c_message_create(make_message())
    agent.compact_context.assert_not_called()


async def test_compact_failure_does_not_break_reply():
    """压缩失败仅记日志，不中断对话。"""
    client, agent, _ = make_client()
    agent.messages = [{"role": "user", "content": "x"}] * 30
    agent.estimate_tokens = MagicMock(return_value=2_000_000)
    agent.compact_context = AsyncMock(side_effect=RuntimeError("LLM down"))
    await client.on_c2c_message_create(make_message())
    client.api.post_c2c_message.assert_any_await(
        openid="openid-user-1", msg_type=0, msg_id="msg-1", content="回复内容"
    )
```

- [ ] **Step 2: 运行测试确认失败**

Run: `uv run pytest tests/test_qq_bot.py -v`
Expected: `test_session_saved_after_turn` 等 6 个新测试 FAIL（save 未被调用 / compact 相关断言失败）

- [ ] **Step 3: 修改 qq_bot.py（增量编辑）**

`_handle_message` 末尾（`await self._reply(message, openid, response.content)` 之后）追加：

```python
        # 4. 持久化 + 自动压缩（压缩提示仅记日志，不占被动回复额度）
        self._save_session()
        if await self._auto_compact_if_needed():
            logger.info("上下文已自动压缩")
```

`_reply` 方法之后追加两个新方法：

```python
    def _save_session(self) -> None:
        """保存当前会话到文件。失败时记录警告，不中断对话。"""
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
            logger.warning(f"会话保存失败：{e}")

    async def _auto_compact_if_needed(self) -> bool:
        """token 估算超过阈值时自动压缩（判定逻辑与 cli.py 一致）。返回是否执行了压缩。"""
        tokens = self.agent.estimate_tokens()
        threshold = int(
            self.agent.settings.max_context_tokens * self.agent.settings.compression_threshold
        )
        min_required = self.agent.settings.head_keep + self.agent.settings.tail_keep
        if tokens >= threshold and len(self.agent.messages) > min_required:
            logger.info(f"Token 用量（{tokens:,}）达到阈值（{threshold:,}），自动压缩中...")
            try:
                before, after = await self.agent.compact_context()
                logger.info(f"自动压缩完成：{before} 条 → {after} 条")
            except Exception as e:
                logger.warning(f"自动压缩失败：{e}")
                return False
            return True
        return False
```

- [ ] **Step 4: 运行测试确认通过**

Run: `uv run pytest tests/test_qq_bot.py -v`
Expected: 全部 PASS

- [ ] **Step 5: Commit**

```bash
git add my_small_agent/qq_bot.py tests/test_qq_bot.py
git commit -m "feat(qq): persist session and auto-compact context after each turn"
```

---

### Task 5: 启动入口与会话恢复

**Files:**
- Modify: `my_small_agent/qq_bot.py`
- Test: `tests/test_qq_bot.py`

**Interfaces:**
- Consumes: `SessionManager.list_sessions() -> list[SessionData]`（updated_at 倒序）；`Agent.reset_session(messages=, session_id=, title=, created_at=)`；`__main__.py` 的组装链；Task 1 的配置项
- Produces: `validate_qq_settings(settings) -> str | None`、`_restore_latest_session(agent, session_manager) -> str | None`、`main()`、`main_entry()`（`agent-qq` 命令入口）

- [ ] **Step 1: 写失败测试（追加到 tests/test_qq_bot.py 末尾）**

import 区追加：

```python
from my_small_agent.qq_bot import _restore_latest_session, validate_qq_settings
from my_small_agent.session import SessionData


def _make_session_data(session_id="abc123", title="标题"):
    return SessionData(
        session_id=session_id,
        created_at="2026-07-23T00:00:00+00:00",
        updated_at="2026-07-23T01:00:00+00:00",
        title=title,
        messages=[{"role": "user", "content": "hi"}],
    )
```

测试函数：

```python
def test_validate_settings_missing_appid():
    settings = Settings(_env_file=None, openai_api_key="sk-test")
    assert "QQ_APPID" in validate_qq_settings(settings)


def test_validate_settings_missing_secret():
    settings = Settings(_env_file=None, openai_api_key="sk-test", qq_appid="123")
    assert "QQ_APPSECRET" in validate_qq_settings(settings)


def test_validate_settings_ok():
    settings = Settings(_env_file=None, openai_api_key="sk-test",
                        qq_appid="123", qq_appsecret="s")
    assert validate_qq_settings(settings) is None


def test_restore_latest_session_success():
    """恢复最近一次会话：调用 reset_session 并返回标题。"""
    agent = MagicMock()
    sm = MagicMock(spec=SessionManager)
    sm.list_sessions.return_value = [_make_session_data()]
    title = _restore_latest_session(agent, sm)
    assert title == "标题"
    agent.reset_session.assert_called_once_with(
        messages=[{"role": "user", "content": "hi"}],
        session_id="abc123",
        title="标题",
        created_at="2026-07-23T00:00:00+00:00",
    )


def test_restore_latest_session_empty():
    """无历史会话时返回 None，不调用 reset_session。"""
    agent = MagicMock()
    sm = MagicMock(spec=SessionManager)
    sm.list_sessions.return_value = []
    assert _restore_latest_session(agent, sm) is None
    agent.reset_session.assert_not_called()


def test_restore_latest_session_failure():
    """恢复失败返回 None（以新会话启动），不抛出。"""
    agent = MagicMock()
    agent.reset_session.side_effect = ValueError("bad data")
    sm = MagicMock(spec=SessionManager)
    sm.list_sessions.return_value = [_make_session_data()]
    assert _restore_latest_session(agent, sm) is None
```

- [ ] **Step 2: 运行测试确认失败**

Run: `uv run pytest tests/test_qq_bot.py -v`
Expected: 新测试 FAIL（`ImportError: cannot import name '_restore_latest_session'`）

- [ ] **Step 3: 修改 qq_bot.py（增量编辑）**

import 区顶部追加：

```python
import sys
from pathlib import Path
```

`validate_qq_settings` 与 `_restore_latest_session` 追加在 `_split_segments` 函数之后：

```python
def validate_qq_settings(settings: Settings) -> str | None:
    """校验 QQ 配置完整性。返回错误描述；配置完整返回 None。"""
    if not settings.qq_appid:
        return "缺少 QQ_APPID 配置"
    if not settings.qq_appsecret:
        return "缺少 QQ_APPSECRET 配置"
    return None


def _restore_latest_session(agent: Agent, session_manager: SessionManager) -> str | None:
    """
    恢复最近一次会话（机器人重启后对话不断片）。

    成功返回会话标题；无历史或恢复失败返回 None（以新会话启动）。
    """
    sessions = session_manager.list_sessions()
    if not sessions:
        return None
    latest = sessions[0]
    try:
        agent.reset_session(
            messages=latest.messages,
            session_id=latest.session_id,
            title=latest.title,
            created_at=latest.created_at,
        )
    except Exception as e:
        logger.warning(f"会话恢复失败，以新会话启动：{e}")
        return None
    return latest.title
```

文件末尾追加 `main()` / `main_entry()`：

```python
def main() -> None:
    """
    主函数 - 初始化所有组件并启动 QQ 机器人。

    组装链与 __main__.py 一致（QQBotClient 替代 CLI）：
      Settings → LLMClient → MemoryManager → ToolRegistry → Agent → QQBotClient
    全程同步：client.run() 内部自行创建事件循环（asyncio.run）。
    """
    try:
        from my_small_agent.llm import LLMClient
        from my_small_agent.tools import create_default_registry
        from my_small_agent.memory import MemoryManager
        from my_small_agent.skills import (
            discover_skills,
            skill_registry,
            build_skills_index,
            register_skill_tools,
        )
        from my_small_agent.prompt import PromptManager
        from my_small_agent.tools.research_topic import ResearchTopicTool

        # 1. 加载配置并校验 QQ 凭证（缺失时打印指引并退出，不抛堆栈）
        settings = Settings()
        if error := validate_qq_settings(settings):
            print(f"错误：{error}")
            print(
                "请先在 https://q.qq.com/qqbot/openclaw/ 创建机器人，"
                "并将 AppID/AppSecret 填入 .env（参考 .env.example）"
            )
            sys.exit(1)

        # 2. 组装组件（与 __main__.py 相同）
        llm_client = LLMClient(settings)
        memory_manager = MemoryManager(Path(".genesis") / "memory")
        registry = create_default_registry(
            settings,
            memory_manager=memory_manager,
            sessions_dir=Path(".genesis") / "sessions",
        )
        discover_skills()
        register_skill_tools(registry, skill_registry)
        registry.register(ResearchTopicTool(registry))
        prompt_manager = PromptManager()
        prompt_manager.update_skills_index(build_skills_index())

        agent = Agent(
            llm_client, registry, settings,
            memory_manager=memory_manager, prompt_manager=prompt_manager,
        )
        agent._skill_registry = skill_registry

        session_manager = SessionManager(Path(".genesis") / "sessions")

        # 3. 恢复最近一次会话（存在则恢复，失败则新会话）
        title = _restore_latest_session(agent, session_manager)
        if title:
            print(f"已恢复最近会话：{title}")

        # 4. 启动机器人（阻塞；WebSocket 长连接，断线由 botpy 自动重连）
        client = QQBotClient(agent=agent, session_manager=session_manager, settings=settings)
        client.run(appid=settings.qq_appid, secret=settings.qq_appsecret)
    except KeyboardInterrupt:
        print("\nGoodbye!")
    except SystemExit:
        raise
    except Exception as e:
        print(f"Failed to start: {e}")
        print("Make sure your .env file is configured correctly.")
        sys.exit(1)


def main_entry() -> None:
    """同步入口点 - 供 pyproject.toml 的 agent-qq 命令使用。"""
    main()


if __name__ == "__main__":
    main_entry()
```

- [ ] **Step 4: 运行测试确认通过**

Run: `uv run pytest tests/test_qq_bot.py -v`
Expected: 全部 PASS

- [ ] **Step 5: 全量回归**

Run: `uv run pytest -v`
Expected: 全部 PASS（所有既有测试不受影响）

- [ ] **Step 6: Commit**

```bash
git add my_small_agent/qq_bot.py tests/test_qq_bot.py
git commit -m "feat(qq): add agent-qq entrypoint with config check and session restore"
```

---

## 手工验证（任务全部完成后，需要真实 QQ 凭证）

1. 在 https://q.qq.com/qqbot/openclaw/ 创建机器人，AppID/AppSecret 填入 `.env`
2. Run: `uv run agent-qq` → 预期输出"QQ 机器人已就绪"（或先输出"已恢复最近会话"）
3. 手机 QQ 找到机器人，发送"你好" → 收到"🤔 思考中..."，随后收到 Agent 回复
4. 发送一条触发工具调用的请求（如"现在几点"）→ 正常回复
5. Ctrl+C 停止后重新 `uv run agent-qq` → 输出"已恢复最近会话"，对话上下文延续
