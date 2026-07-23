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
from my_small_agent.qq_bot import (
    MAX_SEGMENTS,
    SEGMENT_LEN,
    _split_segments,
)
from my_small_agent.session import SessionManager
from my_small_agent.qq_bot import _restore_latest_session, validate_qq_settings
from my_small_agent.session import SessionData


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


def _make_session_data(session_id="abc123", title="标题"):
    return SessionData(
        session_id=session_id,
        created_at="2026-07-23T00:00:00+00:00",
        updated_at="2026-07-23T01:00:00+00:00",
        title=title,
        messages=[{"role": "user", "content": "hi"}],
    )


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
