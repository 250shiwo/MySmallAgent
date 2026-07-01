"""PromptManager 测试 - 提示词加载和拼接逻辑。"""

from pathlib import Path

from my_small_agent.prompt import PromptManager


class TestPromptManager:
    """PromptManager 核心行为测试。"""

    def test_load_base_prompt_from_file(self, tmp_path):
        prompt_file = tmp_path / "test_prompt.md"
        prompt_file.write_text("Hello, I am an agent.", encoding="utf-8")
        pm = PromptManager(base_prompt_path=prompt_file)
        assert pm.get_system_prompt() == "Hello, I am an agent."

    def test_load_default_system_prompt(self):
        """默认加载 my_small_agent/system_prompt.md。"""
        pm = PromptManager()
        # 应包含基础提示词内容
        prompt = pm.get_system_prompt()
        assert len(prompt) > 100
        assert "CLI Agent" in prompt or "命令行" in prompt or "终端" in prompt

    def test_update_skills_index(self, tmp_path):
        prompt_file = tmp_path / "base.md"
        prompt_file.write_text("Base prompt content.", encoding="utf-8")
        pm = PromptManager(base_prompt_path=prompt_file)
        pm.update_skills_index("## Available Skills\n- research: Expert")
        result = pm.get_system_prompt()
        assert "Base prompt content." in result
        assert "## Available Skills" in result
        assert "- research: Expert" in result

    def test_no_skills_index_returns_base_only(self, tmp_path):
        prompt_file = tmp_path / "base.md"
        prompt_file.write_text("Just base.", encoding="utf-8")
        pm = PromptManager(base_prompt_path=prompt_file)
        assert pm.get_system_prompt() == "Just base."

    def test_skills_index_appended_with_separator(self, tmp_path):
        prompt_file = tmp_path / "base.md"
        prompt_file.write_text("Base.", encoding="utf-8")
        pm = PromptManager(base_prompt_path=prompt_file)
        pm.update_skills_index("Skills here.")
        # 确认 base 和 index 之间有分隔
        result = pm.get_system_prompt()
        assert result == "Base.\n\nSkills here."
