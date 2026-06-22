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
