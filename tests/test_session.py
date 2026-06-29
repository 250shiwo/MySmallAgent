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
