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
