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
