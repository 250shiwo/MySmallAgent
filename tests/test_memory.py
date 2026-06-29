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
