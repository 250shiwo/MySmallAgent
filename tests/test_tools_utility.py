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
