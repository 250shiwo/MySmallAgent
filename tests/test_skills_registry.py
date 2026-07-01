"""技能注册表测试 - 覆盖 SkillInfo、SkillRegistry 核心行为。"""

import json
import pytest
from pathlib import Path

from my_small_agent.skills.registry import SkillInfo, SkillRegistry, parse_skill_md
from my_small_agent.skills import discover_skills, skill_registry, build_skills_index


class TestSkillInfo:
    """SkillInfo 数据类基本测试。"""

    def test_create_skill_info_defaults(self):
        info = SkillInfo(name="test", description="A test skill", prompt_text="Do something")
        assert info.name == "test"
        assert info.description == "A test skill"
        assert info.prompt_text == "Do something"
        assert info.user_invocable is True
        assert info.skill_dir is None

    def test_create_skill_info_explicit(self):
        info = SkillInfo(
            name="secret",
            description="Secret skill",
            prompt_text="Secret instructions",
            user_invocable=False,
            skill_dir=Path("/tmp/secret"),
        )
        assert info.user_invocable is False
        assert info.skill_dir == Path("/tmp/secret")


class TestSkillRegistry:
    """SkillRegistry 注册表核心行为测试。"""

    def setup_method(self):
        self.registry = SkillRegistry()
        self.skill_a = SkillInfo(name="alpha", description="Alpha skill", prompt_text="Alpha instructions")
        self.skill_b = SkillInfo(name="beta", description="Beta skill", prompt_text="Beta instructions", user_invocable=False)

    def test_register_and_get(self):
        self.registry.register(self.skill_a)
        assert self.registry.get_skill("alpha") is self.skill_a
        assert self.registry.get_skill("nonexist") is None

    def test_get_all_names(self):
        self.registry.register(self.skill_a)
        self.registry.register(self.skill_b)
        names = self.registry.get_all_names()
        assert sorted(names) == ["alpha", "beta"]

    def test_activate_success(self):
        self.registry.register(self.skill_a)
        result = self.registry.activate("alpha")
        parsed = json.loads(result)
        assert parsed["name"] == "alpha"
        assert parsed["prompt_text"] == "Alpha instructions"
        assert self.registry.get_active() is self.skill_a

    def test_activate_nonexistent_returns_error(self):
        result = self.registry.activate("nonexist")
        parsed = json.loads(result)
        assert "error" in parsed

    def test_deactivate(self):
        self.registry.register(self.skill_a)
        self.registry.activate("alpha")
        result = self.registry.deactivate()
        assert self.registry.get_active() is None
        assert "deactivated" in result.lower() or "alpha" in result.lower()

    def test_deactivate_when_none_active(self):
        result = self.registry.deactivate()
        assert self.registry.get_active() is None

    def test_on_activate_callback(self):
        called_with = []
        self.registry.set_on_activate(lambda name, text: called_with.append((name, text)))
        self.registry.register(self.skill_a)
        self.registry.activate("alpha")
        assert called_with == [("alpha", "Alpha instructions")]


class TestParseSkillMd:
    """SKILL.md 文件解析测试。"""

    def test_parse_valid_skill_md(self, tmp_path):
        skill_dir = tmp_path / "test_skill"
        skill_dir.mkdir()
        skill_md = skill_dir / "SKILL.md"
        skill_md.write_text(
            "---\n"
            "name: test_skill\n"
            'description: "A test skill for testing"\n'
            "user_invocable: true\n"
            "---\n"
            "\nYou are a test assistant.\n\nDo test things.",
            encoding="utf-8",
        )
        info = parse_skill_md(skill_md)
        assert info.name == "test_skill"
        assert info.description == "A test skill for testing"
        assert info.prompt_text == "You are a test assistant.\n\nDo test things."
        assert info.user_invocable is True
        assert info.skill_dir == skill_dir

    def test_parse_user_invocable_false(self, tmp_path):
        skill_dir = tmp_path / "hidden"
        skill_dir.mkdir()
        skill_md = skill_dir / "SKILL.md"
        skill_md.write_text(
            "---\nname: hidden\ndescription: Hidden\nuser_invocable: false\n---\nSecret.",
            encoding="utf-8",
        )
        info = parse_skill_md(skill_md)
        assert info.user_invocable is False

    def test_parse_missing_frontmatter_raises(self, tmp_path):
        skill_md = tmp_path / "SKILL.md"
        skill_md.write_text("No frontmatter here.", encoding="utf-8")
        with pytest.raises(ValueError, match="missing frontmatter"):
            parse_skill_md(skill_md)

    def test_parse_missing_name_raises(self, tmp_path):
        skill_md = tmp_path / "SKILL.md"
        skill_md.write_text("---\ndescription: test\n---\ncontent", encoding="utf-8")
        with pytest.raises(ValueError, match="missing 'name'"):
            parse_skill_md(skill_md)


class TestDiscoverSkills:
    """技能自动发现测试。"""

    def setup_method(self):
        # 每次测试前清空全局注册表
        skill_registry._skills.clear()
        skill_registry._active_skill = None

    def test_discover_from_directory(self, tmp_path):
        # 创建两个合法技能
        for name in ("alpha", "beta"):
            d = tmp_path / name
            d.mkdir()
            (d / "SKILL.md").write_text(
                f"---\nname: {name}\ndescription: {name} skill\n---\n{name} instructions",
                encoding="utf-8",
            )
        # 创建一个应跳过的目录（无 SKILL.md）
        (tmp_path / "no_skill").mkdir()
        # 创建一个应跳过的隐藏目录
        (tmp_path / ".hidden").mkdir()
        (tmp_path / ".hidden" / "SKILL.md").write_text("---\nname: x\ndescription: x\n---\nx", encoding="utf-8")

        names = discover_skills(tmp_path)
        assert sorted(names) == ["alpha", "beta"]
        assert skill_registry.get_skill("alpha") is not None
        assert skill_registry.get_skill(".hidden") is None

    def test_discover_empty_dir(self, tmp_path):
        names = discover_skills(tmp_path)
        assert names == []


class TestBuildSkillsIndex:
    """技能索引构建测试。"""

    def setup_method(self):
        skill_registry._skills.clear()
        skill_registry._active_skill = None

    def test_build_index_with_skills(self):
        skill_registry.register(SkillInfo(name="a", description="Skill A", prompt_text="x"))
        skill_registry.register(SkillInfo(name="b", description="Skill B", prompt_text="y"))
        index = build_skills_index()
        assert "## Available Skills" in index
        assert "- a: Skill A" in index
        assert "- b: Skill B" in index

    def test_build_index_empty(self):
        index = build_skills_index()
        assert index == ""
