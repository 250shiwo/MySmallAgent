# Skill System Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 为 MySmallAgent 引入完整的技能系统，包含 Skill 自动发现注册、PromptManager、LLM 自主激活/CLI 手动激活、以及 research_topic 组合工具。

**Architecture:** 新增 `my_small_agent/skills/` 包管理技能发现与注册（对称 ToolRegistry 模式），新增 `prompt.py` 从文件加载系统提示词并动态拼接 skills index。技能激活通过 tool result 注入对话历史，保持 system prompt 前缀不变（缓存友好）。

**Tech Stack:** Python 3.11+, pydantic-settings, openai SDK, pytest + pytest-asyncio

## Global Constraints

- Python ≥ 3.11（项目已有约束）
- 无新外部依赖（frontmatter 解析使用正则，不引入 pyyaml）
- 遵循现有中文注释规范
- 所有新工具 danger_level = "safe"
- TDD 流程：先写测试 → 验证失败 → 实现 → 验证通过 → 提交
- 版本号保持 0.1.0 不变（待所有功能合入后统一升版）

---

### Task 1: SkillInfo 数据类 + SkillRegistry + SKILL.md 解析 + 自动发现

**Files:**
- Create: `my_small_agent/skills/__init__.py`
- Create: `my_small_agent/skills/registry.py`
- Create: `my_small_agent/skills/research/SKILL.md`
- Create: `my_small_agent/skills/code_assistant/SKILL.md`
- Test: `tests/test_skills_registry.py`

**Interfaces:**
- Consumes: 无（基础模块）
- Produces:
  - `SkillInfo` dataclass: `name: str, description: str, prompt_text: str, user_invocable: bool, skill_dir: Path | None`
  - `SkillRegistry` class: `register(SkillInfo)`, `activate(name) -> str`, `deactivate() -> str`, `get_active() -> SkillInfo | None`, `get_all_names() -> list[str]`, `get_skill(name) -> SkillInfo | None`, `set_on_activate(callback)`
  - `skill_registry` 全局单例（`SkillRegistry` 实例）
  - `discover_skills(skills_dir: Path | None = None) -> list[str]`
  - `build_skills_index() -> str`

- [ ] **Step 1: 编写 SkillInfo + SkillRegistry 的失败测试**

```python
# tests/test_skills_registry.py
"""技能注册表测试 - 覆盖 SkillInfo、SkillRegistry 核心行为。"""

import json
import pytest
from pathlib import Path

from my_small_agent.skills.registry import SkillInfo, SkillRegistry


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
```

- [ ] **Step 2: 运行测试确认失败**

Run: `cd c:\Users\chancemate\Desktop\MySmallAgent && uv run pytest tests/test_skills_registry.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'my_small_agent.skills'`

- [ ] **Step 3: 实现 SkillInfo + SkillRegistry**

```python
# my_small_agent/skills/registry.py
"""
技能注册表模块 - 管理技能的注册、激活、取消激活。

设计与 ToolRegistry 对称：
  - SkillInfo: 技能元数据（名称、描述、指令内容、是否用户可调用）
  - SkillRegistry: 中心化注册表，管理激活状态和回调
"""

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional


@dataclass
class SkillInfo:
    """
    技能元数据。

    属性：
      name:           技能标识符（如 "research"）
      description:    技能描述，写入 system prompt 供 LLM 判断是否激活
      prompt_text:    SKILL.md 中 frontmatter 之后的完整指令内容
      user_invocable: 用户是否可通过 /skill 命令手动激活
      skill_dir:      技能目录路径（用于调试/扩展）
    """

    name: str
    description: str
    prompt_text: str
    user_invocable: bool = True
    skill_dir: Optional[Path] = None


class SkillRegistry:
    """
    中心化技能注册表。

    职责：
      - register():       注册技能
      - activate(name):   激活技能，返回含指令的 JSON
      - deactivate():     取消激活
      - get_active():     获取当前激活的技能
      - get_all_names():  获取所有已注册技能名称
      - get_skill(name):  按名称查询技能
    """

    def __init__(self) -> None:
        self._skills: dict[str, SkillInfo] = {}
        self._active_skill: Optional[str] = None
        self._on_activate: Optional[Callable] = None

    def register(self, skill_info: SkillInfo) -> None:
        """注册一个技能到注册表。"""
        self._skills[skill_info.name] = skill_info

    def activate(self, name: str) -> str:
        """
        激活指定技能。

        返回 JSON 字符串：
          成功 → {"name": "...", "prompt_text": "..."}
          失败 → {"error": "..."}
        """
        skill = self._skills.get(name)
        if skill is None:
            return json.dumps({"error": f"Skill '{name}' not found"})
        self._active_skill = name
        if self._on_activate:
            self._on_activate(name, skill.prompt_text)
        return json.dumps({"name": skill.name, "prompt_text": skill.prompt_text})

    def deactivate(self) -> str:
        """取消当前激活的技能，返回确认消息。"""
        prev = self._active_skill
        self._active_skill = None
        if prev:
            return f"Skill '{prev}' deactivated. Returned to base mode."
        return "No skill was active."

    def get_active(self) -> Optional[SkillInfo]:
        """获取当前激活的技能，未激活时返回 None。"""
        if self._active_skill:
            return self._skills.get(self._active_skill)
        return None

    def get_all_names(self) -> list[str]:
        """返回所有已注册技能的名称列表。"""
        return list(self._skills.keys())

    def get_skill(self, name: str) -> Optional[SkillInfo]:
        """按名称查询技能，不存在时返回 None。"""
        return self._skills.get(name)

    def set_on_activate(self, callback: Callable) -> None:
        """注册激活回调函数，签名: (name: str, prompt_text: str) -> None。"""
        self._on_activate = callback


def parse_skill_md(skill_md_path: Path) -> SkillInfo:
    """
    解析 SKILL.md 文件，提取 frontmatter 和指令内容。

    格式要求：
      ---
      name: xxx
      description: "xxx"
      user_invocable: true
      ---
      （技能详细指令）
    """
    content = skill_md_path.read_text(encoding="utf-8")
    # 正则提取 YAML frontmatter
    match = re.match(r"^---\s*\n(.*?)\n---\s*\n", content, re.DOTALL)
    if not match:
        raise ValueError(f"Invalid SKILL.md format (missing frontmatter): {skill_md_path}")

    frontmatter_text = match.group(1)
    prompt_text = content[match.end():].strip()

    # 逐行解析 key: value
    meta: dict = {}
    for line in frontmatter_text.strip().splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if ":" not in line:
            continue
        key, _, value = line.partition(":")
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        meta[key] = value

    name = meta.get("name", "")
    description = meta.get("description", "")
    user_invocable_str = meta.get("user_invocable", "true").lower()
    user_invocable = user_invocable_str in ("true", "1", "yes")

    if not name:
        raise ValueError(f"SKILL.md missing 'name' field: {skill_md_path}")
    if not description:
        raise ValueError(f"SKILL.md missing 'description' field: {skill_md_path}")

    return SkillInfo(
        name=name,
        description=description,
        prompt_text=prompt_text,
        user_invocable=user_invocable,
        skill_dir=skill_md_path.parent,
    )
```

```python
# my_small_agent/skills/__init__.py
"""
技能系统入口 - 自动发现、注册技能，构建 skills index。

使用方式：
  from my_small_agent.skills import discover_skills, skill_registry, build_skills_index

  discover_skills()  # 扫描 skills/ 目录并注册
  index = build_skills_index()  # 生成 system prompt 用的技能列表文本
"""

from pathlib import Path
from typing import Optional

from my_small_agent.skills.registry import SkillInfo, SkillRegistry, parse_skill_md

# 全局单例
skill_registry = SkillRegistry()


def discover_skills(skills_dir: Optional[Path] = None) -> list[str]:
    """
    扫描技能目录，解析并注册所有合法的 SKILL.md。

    返回已注册的技能名称列表。
    跳过以 '_' 或 '.' 开头的目录，跳过 __pycache__。
    """
    skills_path = skills_dir or Path(__file__).resolve().parent
    registered: list[str] = []

    if not skills_path.exists():
        return registered

    for item in sorted(skills_path.iterdir()):
        if not item.is_dir():
            continue
        if item.name.startswith(("_", ".")):
            continue
        skill_md = item / "SKILL.md"
        if not skill_md.exists():
            continue
        info = parse_skill_md(skill_md)
        skill_registry.register(info)
        registered.append(info.name)

    return registered


def build_skills_index() -> str:
    """
    构建技能索引文本，拼接到 system prompt 末尾。

    输出示例：
      ## Available Skills
      When a task matches a skill below, call activate_skill(name) to get detailed instructions.

      - research: 搜索研究专家，擅长网络搜索、信息提取和综合分析。
      - code_assistant: 代码助手专家，擅长代码编写、调试和重构。
    """
    names = skill_registry.get_all_names()
    if not names:
        return ""

    lines = ["## Available Skills",
             "When a task matches a skill below, call activate_skill(name) to get detailed instructions.\n"]
    for name in names:
        skill = skill_registry.get_skill(name)
        if skill:
            lines.append(f"- {skill.name}: {skill.description}")

    return "\n".join(lines)
```

- [ ] **Step 4: 运行测试确认通过**

Run: `cd c:\Users\chancemate\Desktop\MySmallAgent && uv run pytest tests/test_skills_registry.py -v`
Expected: All tests PASS

- [ ] **Step 5: 编写 SKILL.md 解析和 discover_skills 的测试**

```python
# 追加到 tests/test_skills_registry.py

from my_small_agent.skills.registry import parse_skill_md
from my_small_agent.skills import discover_skills, skill_registry, build_skills_index


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
```

- [ ] **Step 6: 运行全部测试确认通过**

Run: `cd c:\Users\chancemate\Desktop\MySmallAgent && uv run pytest tests/test_skills_registry.py -v`
Expected: All tests PASS

- [ ] **Step 7: 创建预置技能 SKILL.md 文件**

```markdown
# my_small_agent/skills/research/SKILL.md
---
name: research
description: "搜索研究专家，擅长网络搜索、信息提取和综合分析。"
user_invocable: true
---

You are now operating in **Research Mode**.

## 搜索策略
- 先用宽泛关键词搜索获取整体概况
- 根据初步结果缩窄关键词深入搜索
- 同一查询最多尝试 2 次，不反复换关键词
- 优先使用 research_topic 工具处理复杂研究任务

## 信息提取
- 从多个来源交叉验证关键信息
- 提取核心事实，忽略广告和无关内容
- 对时效性信息注明获取时间

## 综合分析
- 对收集的信息进行结构化整理
- 标注信息来源（URL 或出处）
- 明确区分事实与推测
- 提供简洁的结论和建议

## 输出规范
- 使用清晰的标题和列表组织内容
- 重要数据用粗体标注
- 引用来源放在内容末尾
- 如果信息不足以得出结论，明确告知用户
```

```markdown
# my_small_agent/skills/code_assistant/SKILL.md
---
name: code_assistant
description: "代码助手专家，擅长代码编写、调试、重构和项目结构分析。"
user_invocable: true
---

You are now operating in **Code Assistant Mode**.

## 工作流程
1. 先读取相关文件了解现有代码结构（使用 read_file / tree / list_directory）
2. 理解上下文后再做修改
3. 修改后验证（如有 shell 权限，运行测试或 lint）

## 调试指南
- 先理解错误信息的含义
- 定位可能的问题代码位置
- 提出修复方案并解释原因
- 修复后验证问题已解决

## 代码风格
- 跟随项目现有代码风格
- 不做无关的格式调整
- 变量和函数命名保持一致性
- 添加必要的注释说明意图

## 工具偏好
- 读取文件：使用 read_file
- 了解项目结构：使用 tree 或 list_directory
- 搜索代码：使用 grep_search
- 查找文件：使用 find_file
- 修改文件：使用 write_file（展示修改内容）
- 验证修改：使用 execute_shell 运行测试

## 安全原则
- 修改文件前先确认目标路径正确
- 大规模修改前先备份或确认
- 不执行不确定后果的 shell 命令
```

- [ ] **Step 8: 提交**

```bash
git add my_small_agent/skills/ tests/test_skills_registry.py
git commit -m "feat: add SkillRegistry, SKILL.md parsing, auto-discovery, and preset skills"
```

---

### Task 2: PromptManager + system_prompt.md

**Files:**
- Create: `my_small_agent/prompt.py`
- Create: `my_small_agent/system_prompt.md`
- Test: `tests/test_prompt_manager.py`

**Interfaces:**
- Consumes: `build_skills_index() -> str` (from Task 1)
- Produces:
  - `PromptManager` class: `__init__(base_prompt_path: Path | None)`, `update_skills_index(str)`, `get_system_prompt() -> str`

- [ ] **Step 1: 编写 PromptManager 的失败测试**

```python
# tests/test_prompt_manager.py
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
```

- [ ] **Step 2: 运行测试确认失败**

Run: `cd c:\Users\chancemate\Desktop\MySmallAgent && uv run pytest tests/test_prompt_manager.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'my_small_agent.prompt'`

- [ ] **Step 3: 提取 system_prompt.md**

从 `my_small_agent/agent.py` 的 `SYSTEM_PROMPT` 变量（第 30-64 行）内容提取到独立文件：

```markdown
# my_small_agent/system_prompt.md
（将 agent.py 中 SYSTEM_PROMPT = """...""" 内的完整文本直接复制到此文件，不含 Python 三引号）
```

具体内容为 agent.py 第 30-64 行 `"""` 内的原始文本。

- [ ] **Step 4: 实现 PromptManager**

```python
# my_small_agent/prompt.py
"""
提示词管理模块 - 从文件加载基础系统提示词，动态拼接 skills index。

设计原则：
  - system prompt 前缀在整个会话中保持不变（缓存友好）
  - 技能激活时指令通过 tool result 进入对话历史，不修改 system prompt
"""

from pathlib import Path
from typing import Optional


class PromptManager:
    """
    提示词管理器。

    职责：
      - 从 .md 文件加载基础 system prompt
      - 启动时拼接 skills index
      - 提供统一的 get_system_prompt() 接口给 Agent
    """

    def __init__(self, base_prompt_path: Optional[Path] = None) -> None:
        self._base_prompt = self._load_base_prompt(base_prompt_path)
        self._skills_index: str = ""

    def update_skills_index(self, skills_index: str) -> None:
        """启动时调用一次，设置 skills 列表文本。"""
        self._skills_index = skills_index

    def get_system_prompt(self) -> str:
        """返回完整 system prompt = base + skills index。"""
        if self._skills_index:
            return self._base_prompt + "\n\n" + self._skills_index
        return self._base_prompt

    def _load_base_prompt(self, path: Optional[Path]) -> str:
        """加载基础提示词文件。默认路径: my_small_agent/system_prompt.md。"""
        if path is None:
            path = Path(__file__).resolve().parent / "system_prompt.md"
        return path.read_text(encoding="utf-8").strip()
```

- [ ] **Step 5: 运行测试确认通过**

Run: `cd c:\Users\chancemate\Desktop\MySmallAgent && uv run pytest tests/test_prompt_manager.py -v`
Expected: All tests PASS

- [ ] **Step 6: 提交**

```bash
git add my_small_agent/prompt.py my_small_agent/system_prompt.md tests/test_prompt_manager.py
git commit -m "feat: add PromptManager with file-based system prompt"
```

---

### Task 3: activate_skill / deactivate_skill 工具

**Files:**
- Create: `my_small_agent/tools/activate_skill.py`
- Create: `my_small_agent/tools/deactivate_skill.py`
- Test: `tests/test_tools_skill.py`

**Interfaces:**
- Consumes:
  - `SkillRegistry` (from Task 1): `activate(name) -> str`, `deactivate() -> str`
  - `Tool` base class (existing): `name`, `description`, `parameters`, `danger_level`, `execute(**kwargs)`
- Produces:
  - `ActivateSkillTool(skill_registry: SkillRegistry)` — 工具类，handler 调用 skill_registry.activate()
  - `DeactivateSkillTool(skill_registry: SkillRegistry)` — 工具类，handler 调用 skill_registry.deactivate()
  - `register_skill_tools(registry: ToolRegistry, skill_registry: SkillRegistry)` — 辅助函数

- [ ] **Step 1: 编写失败测试**

```python
# tests/test_tools_skill.py
"""activate_skill / deactivate_skill 工具测试。"""

import json
import pytest

from my_small_agent.skills.registry import SkillInfo, SkillRegistry
from my_small_agent.tools.activate_skill import ActivateSkillTool
from my_small_agent.tools.deactivate_skill import DeactivateSkillTool


@pytest.fixture
def skill_reg():
    reg = SkillRegistry()
    reg.register(SkillInfo(name="research", description="Research expert", prompt_text="Research mode instructions"))
    reg.register(SkillInfo(name="hidden", description="Hidden", prompt_text="Secret", user_invocable=False))
    return reg


class TestActivateSkillTool:
    """activate_skill 工具测试。"""

    @pytest.mark.asyncio
    async def test_activate_existing_skill(self, skill_reg):
        tool = ActivateSkillTool(skill_reg)
        result = await tool.execute(skill_name="research")
        parsed = json.loads(result)
        assert parsed["name"] == "research"
        assert "Research mode instructions" in parsed["prompt_text"]
        assert skill_reg.get_active().name == "research"

    @pytest.mark.asyncio
    async def test_activate_nonexistent_skill(self, skill_reg):
        tool = ActivateSkillTool(skill_reg)
        result = await tool.execute(skill_name="nonexist")
        parsed = json.loads(result)
        assert "error" in parsed

    def test_tool_metadata(self, skill_reg):
        tool = ActivateSkillTool(skill_reg)
        assert tool.name == "activate_skill"
        assert tool.danger_level == "safe"
        assert "skill_name" in tool.parameters["properties"]


class TestDeactivateSkillTool:
    """deactivate_skill 工具测试。"""

    @pytest.mark.asyncio
    async def test_deactivate_active_skill(self, skill_reg):
        skill_reg.activate("research")
        tool = DeactivateSkillTool(skill_reg)
        result = await tool.execute()
        assert skill_reg.get_active() is None
        assert "research" in result.lower() or "deactivat" in result.lower()

    @pytest.mark.asyncio
    async def test_deactivate_when_none_active(self, skill_reg):
        tool = DeactivateSkillTool(skill_reg)
        result = await tool.execute()
        assert skill_reg.get_active() is None

    def test_tool_metadata(self, skill_reg):
        tool = DeactivateSkillTool(skill_reg)
        assert tool.name == "deactivate_skill"
        assert tool.danger_level == "safe"
```

- [ ] **Step 2: 运行测试确认失败**

Run: `cd c:\Users\chancemate\Desktop\MySmallAgent && uv run pytest tests/test_tools_skill.py -v`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: 实现 activate_skill 工具**

```python
# my_small_agent/tools/activate_skill.py
"""
activate_skill 工具 - LLM 自主激活技能。

当 LLM 判断当前任务匹配某个技能时，调用此工具获取技能详细指令。
返回的指令作为 tool result 进入对话历史，system prompt 不变。
"""

from my_small_agent.skills.registry import SkillRegistry
from my_small_agent.tools.base import Tool


class ActivateSkillTool(Tool):
    """激活指定技能并返回其详细指令。"""

    name = "activate_skill"
    description = "Activate a skill by name. Returns the skill's detailed instructions."
    parameters = {
        "type": "object",
        "properties": {
            "skill_name": {
                "type": "string",
                "description": "技能名称（从 Available Skills 列表中选择）",
            }
        },
        "required": ["skill_name"],
    }
    danger_level = "safe"

    def __init__(self, skill_registry: SkillRegistry) -> None:
        self._skill_registry = skill_registry

    async def execute(self, **kwargs) -> str:
        """激活技能并返回含指令的 JSON。"""
        skill_name = kwargs.get("skill_name", "")
        return self._skill_registry.activate(skill_name)
```

- [ ] **Step 4: 实现 deactivate_skill 工具**

```python
# my_small_agent/tools/deactivate_skill.py
"""
deactivate_skill 工具 - 取消当前激活的技能，回到基础模式。
"""

from my_small_agent.skills.registry import SkillRegistry
from my_small_agent.tools.base import Tool


class DeactivateSkillTool(Tool):
    """取消当前激活的技能。"""

    name = "deactivate_skill"
    description = "Deactivate the currently active skill and return to base mode."
    parameters = {
        "type": "object",
        "properties": {},
        "required": [],
    }
    danger_level = "safe"

    def __init__(self, skill_registry: SkillRegistry) -> None:
        self._skill_registry = skill_registry

    async def execute(self, **kwargs) -> str:
        """取消激活并返回确认消息。"""
        return self._skill_registry.deactivate()
```

- [ ] **Step 5: 运行测试确认通过**

Run: `cd c:\Users\chancemate\Desktop\MySmallAgent && uv run pytest tests/test_tools_skill.py -v`
Expected: All tests PASS

- [ ] **Step 6: 提交**

```bash
git add my_small_agent/tools/activate_skill.py my_small_agent/tools/deactivate_skill.py tests/test_tools_skill.py
git commit -m "feat: add activate_skill and deactivate_skill tools"
```

---

### Task 4: ToolRegistry.dispatch() + research_topic 组合工具

**Files:**
- Modify: `my_small_agent/tools/__init__.py` (ToolRegistry 新增 dispatch 方法)
- Create: `my_small_agent/tools/research_topic.py`
- Test: `tests/test_tools_composite.py`

**Interfaces:**
- Consumes:
  - `ToolRegistry` (existing): `get(name) -> Tool | None`
  - `Tool.execute(**kwargs) -> str` (existing)
- Produces:
  - `ToolRegistry.dispatch(name: str, args: dict) -> str` — 新增方法
  - `ResearchTopicTool(registry: ToolRegistry)` — 组合工具类

- [ ] **Step 1: 编写失败测试**

```python
# tests/test_tools_composite.py
"""组合工具测试 - ToolRegistry.dispatch 和 research_topic。"""

import json
import pytest

from my_small_agent.tools import ToolRegistry
from my_small_agent.tools.base import Tool
from my_small_agent.tools.research_topic import ResearchTopicTool


class MockSearchTool(Tool):
    """模拟 web_search 工具。"""
    name = "web_search"
    description = "Mock search"
    parameters = {"type": "object", "properties": {}, "required": []}
    danger_level = "safe"

    async def execute(self, **kwargs) -> str:
        return json.dumps({
            "results": [
                {"title": "Result 1", "href": "https://example.com/1", "body": "body1"},
                {"title": "Result 2", "href": "https://example.com/2", "body": "body2"},
            ]
        })


class MockFetchTool(Tool):
    """模拟 fetch_url 工具。"""
    name = "fetch_url"
    description = "Mock fetch"
    parameters = {"type": "object", "properties": {}, "required": []}
    danger_level = "safe"

    async def execute(self, **kwargs) -> str:
        url = kwargs.get("url", "")
        return f"Content from {url}"


class TestToolRegistryDispatch:
    """ToolRegistry.dispatch 方法测试。"""

    @pytest.mark.asyncio
    async def test_dispatch_existing_tool(self):
        registry = ToolRegistry()
        registry.register(MockSearchTool())
        result = await registry.dispatch("web_search", {"query": "test"})
        parsed = json.loads(result)
        assert "results" in parsed

    @pytest.mark.asyncio
    async def test_dispatch_nonexistent_tool(self):
        registry = ToolRegistry()
        result = await registry.dispatch("nonexist", {})
        parsed = json.loads(result)
        assert "error" in parsed


class TestResearchTopicTool:
    """research_topic 组合工具测试。"""

    @pytest.fixture
    def registry_with_mocks(self):
        registry = ToolRegistry()
        registry.register(MockSearchTool())
        registry.register(MockFetchTool())
        return registry

    @pytest.mark.asyncio
    async def test_research_topic_basic(self, registry_with_mocks):
        tool = ResearchTopicTool(registry_with_mocks)
        result = await tool.execute(query="Python latest version")
        parsed = json.loads(result)
        assert parsed["success"] is True
        assert parsed["query"] == "Python latest version"
        assert len(parsed["sources"]) == 2  # mock 返回 2 个结果，max_sources 默认 3

    @pytest.mark.asyncio
    async def test_research_topic_max_sources(self, registry_with_mocks):
        tool = ResearchTopicTool(registry_with_mocks)
        result = await tool.execute(query="test", max_sources=1)
        parsed = json.loads(result)
        assert len(parsed["sources"]) == 1

    def test_tool_metadata(self, registry_with_mocks):
        tool = ResearchTopicTool(registry_with_mocks)
        assert tool.name == "research_topic"
        assert tool.danger_level == "safe"
        assert "query" in tool.parameters["properties"]
```

- [ ] **Step 2: 运行测试确认失败**

Run: `cd c:\Users\chancemate\Desktop\MySmallAgent && uv run pytest tests/test_tools_composite.py -v`
Expected: FAIL

- [ ] **Step 3: 给 ToolRegistry 添加 dispatch 方法**

在 `my_small_agent/tools/__init__.py` 的 `ToolRegistry` 类中添加：

```python
    async def dispatch(self, name: str, args: dict) -> str:
        """
        内部调用：按名称查找工具并执行，用于组合工具编排。

        工具不存在时返回 JSON 错误信息，不抛异常。
        """
        import json
        tool = self.get(name)
        if tool is None:
            return json.dumps({"error": f"Tool '{name}' not found"})
        try:
            return await tool.execute(**args)
        except Exception as e:
            return json.dumps({"error": f"Tool '{name}' execution failed: {e}"})
```

- [ ] **Step 4: 实现 research_topic 组合工具**

```python
# my_small_agent/tools/research_topic.py
"""
research_topic 组合工具 - 链式编排 web_search + fetch_url 实现深度研究。

工作流程：
  1. 调用 web_search 搜索指定 query
  2. 对搜索结果的前 N 个 URL 调用 fetch_url 获取全文
  3. 将所有结果整合为结构化 JSON 返回
"""

import json

from my_small_agent.tools.base import Tool


class ResearchTopicTool(Tool):
    """深度研究工具：搜索 + 获取页面内容的组合编排。"""

    name = "research_topic"
    description = "Deep research a topic: searches the web, fetches top results, and returns structured sources."
    parameters = {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "搜索查询关键词",
            },
            "max_sources": {
                "type": "integer",
                "description": "最多获取的源数量（默认 3）",
            },
        },
        "required": ["query"],
    }
    danger_level = "safe"

    def __init__(self, registry) -> None:
        """接收 ToolRegistry 引用，用于调用其他工具。"""
        self._registry = registry

    async def execute(self, **kwargs) -> str:
        """执行搜索 + 获取的组合编排。"""
        query = kwargs.get("query", "")
        max_sources = kwargs.get("max_sources", 3)

        # Step 1: 搜索
        search_raw = await self._registry.dispatch("web_search", {"query": query})
        try:
            search_data = json.loads(search_raw)
        except json.JSONDecodeError:
            return json.dumps({"success": False, "error": "Search returned invalid data"})

        if "error" in search_data:
            return json.dumps({"success": False, "error": search_data["error"]})

        # Step 2: 获取页面内容
        results = search_data.get("results", [])[:max_sources]
        sources = []
        for item in results:
            url = item.get("href", "")
            title = item.get("title", "")
            if not url:
                continue
            content = await self._registry.dispatch("fetch_url", {"url": url})
            sources.append({"url": url, "title": title, "content": content})

        # Step 3: 返回整合结果
        return json.dumps({
            "success": True,
            "query": query,
            "sources": sources,
        }, ensure_ascii=False)
```

- [ ] **Step 5: 运行测试确认通过**

Run: `cd c:\Users\chancemate\Desktop\MySmallAgent && uv run pytest tests/test_tools_composite.py -v`
Expected: All tests PASS

- [ ] **Step 6: 提交**

```bash
git add my_small_agent/tools/__init__.py my_small_agent/tools/research_topic.py tests/test_tools_composite.py
git commit -m "feat: add ToolRegistry.dispatch() and research_topic composite tool"
```

---

### Task 5: Agent 集成（PromptManager + Skill 激活）

**Files:**
- Modify: `my_small_agent/agent.py` — 集成 PromptManager，新增 activate_skill/deactivate_skill 方法
- Modify: `my_small_agent/__main__.py` — 启动流程新增 skill 发现和 PromptManager 初始化
- Modify: `my_small_agent/tools/__init__.py` — create_default_registry 新增 skill 工具注册
- Modify: `tests/test_agent.py` — 更新 Agent 初始化参数
- Modify: `tests/test_agent_stream.py` — 更新 Agent 初始化参数
- Test: `tests/test_agent_skill.py` — Agent skill 激活集成测试

**Interfaces:**
- Consumes:
  - `PromptManager` (from Task 2): `get_system_prompt() -> str`
  - `SkillRegistry` (from Task 1): `activate()`, `deactivate()`, `get_active()`
  - `ActivateSkillTool` / `DeactivateSkillTool` (from Task 3)
  - `discover_skills()`, `build_skills_index()`, `skill_registry` (from Task 1)
- Produces:
  - `Agent.__init__` 新增 `prompt_manager: PromptManager | None = None` 参数
  - `Agent.activate_skill(name: str) -> str` — CLI 手动激活，注入消息对
  - `Agent.deactivate_skill() -> str` — CLI 手动取消

- [ ] **Step 1: 编写 Agent skill 集成的失败测试**

```python
# tests/test_agent_skill.py
"""Agent 技能激活集成测试。"""

import json
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from pathlib import Path

from my_small_agent.agent import Agent
from my_small_agent.config import Settings
from my_small_agent.tools import ToolRegistry
from my_small_agent.prompt import PromptManager
from my_small_agent.skills.registry import SkillInfo, SkillRegistry


@pytest.fixture
def mock_settings():
    with patch.object(Settings, "__init__", lambda self: None):
        s = Settings.__new__(Settings)
        s.openai_api_key = "test-key"
        s.openai_base_url = "http://test"
        s.openai_model = "test-model"
        s.max_iterations = 5
        s.enable_streaming = False
        s.enable_thinking = False
        s.timezone = "UTC"
        s.max_context_tokens = 100000
        s.head_keep = 3
        s.tail_keep = 20
        s.compression_threshold = 0.8
        return s


@pytest.fixture
def mock_prompt_manager(tmp_path):
    prompt_file = tmp_path / "prompt.md"
    prompt_file.write_text("Base prompt.", encoding="utf-8")
    pm = PromptManager(base_prompt_path=prompt_file)
    pm.update_skills_index("## Available Skills\n- research: Expert")
    return pm


@pytest.fixture
def skill_reg():
    reg = SkillRegistry()
    reg.register(SkillInfo(name="research", description="Expert", prompt_text="Research instructions here."))
    reg.register(SkillInfo(name="auto_only", description="Auto", prompt_text="Auto only.", user_invocable=False))
    return reg


class TestAgentWithPromptManager:
    """Agent 使用 PromptManager 初始化测试。"""

    def test_system_prompt_from_prompt_manager(self, mock_settings, mock_prompt_manager):
        llm = MagicMock()
        registry = ToolRegistry()
        agent = Agent(llm, registry, mock_settings, prompt_manager=mock_prompt_manager)
        # system prompt 应包含 base + skills index
        system_msg = agent.messages[0]
        assert system_msg["role"] == "system"
        assert "Base prompt." in system_msg["content"]
        assert "## Available Skills" in system_msg["content"]

    def test_without_prompt_manager_uses_default(self, mock_settings):
        llm = MagicMock()
        registry = ToolRegistry()
        agent = Agent(llm, registry, mock_settings)
        # 应回退到内置 SYSTEM_PROMPT（现在从文件加载）
        assert agent.messages[0]["role"] == "system"
        assert len(agent.messages[0]["content"]) > 50


class TestAgentSkillActivation:
    """Agent 手动技能激活测试。"""

    def test_activate_skill_injects_messages(self, mock_settings, mock_prompt_manager, skill_reg):
        llm = MagicMock()
        registry = ToolRegistry()
        agent = Agent(llm, registry, mock_settings, prompt_manager=mock_prompt_manager)
        agent._skill_registry = skill_reg

        result = agent.activate_skill("research")
        assert "research" in result.lower() or "Research instructions" in result

        # 检查消息注入：应有 assistant(tool_calls) + tool(result) 一对
        # 倒数第二条是 assistant with tool_calls
        assistant_msg = agent.messages[-2]
        assert assistant_msg["role"] == "assistant"
        assert assistant_msg["tool_calls"][0]["function"]["name"] == "activate_skill"
        # 倒数第一条是 tool result
        tool_msg = agent.messages[-1]
        assert tool_msg["role"] == "tool"
        assert "Research instructions here." in tool_msg["content"]

    def test_activate_nonexistent_skill(self, mock_settings, mock_prompt_manager, skill_reg):
        llm = MagicMock()
        registry = ToolRegistry()
        agent = Agent(llm, registry, mock_settings, prompt_manager=mock_prompt_manager)
        agent._skill_registry = skill_reg

        result = agent.activate_skill("nonexist")
        assert "error" in result.lower() or "not found" in result.lower()

    def test_activate_non_invocable_skill_rejected(self, mock_settings, mock_prompt_manager, skill_reg):
        llm = MagicMock()
        registry = ToolRegistry()
        agent = Agent(llm, registry, mock_settings, prompt_manager=mock_prompt_manager)
        agent._skill_registry = skill_reg

        result = agent.activate_skill("auto_only")
        assert "error" in result.lower() or "auto" in result.lower() or "拒绝" in result

    def test_deactivate_skill(self, mock_settings, mock_prompt_manager, skill_reg):
        llm = MagicMock()
        registry = ToolRegistry()
        agent = Agent(llm, registry, mock_settings, prompt_manager=mock_prompt_manager)
        agent._skill_registry = skill_reg

        agent.activate_skill("research")
        result = agent.deactivate_skill()
        assert skill_reg.get_active() is None
```

- [ ] **Step 2: 运行测试确认失败**

Run: `cd c:\Users\chancemate\Desktop\MySmallAgent && uv run pytest tests/test_agent_skill.py -v`
Expected: FAIL

- [ ] **Step 3: 修改 agent.py**

关键修改点：

1. 删除 `SYSTEM_PROMPT` 常量（第 30-64 行）
2. `Agent.__init__` 新增 `prompt_manager` 参数，用其 `get_system_prompt()` 替代硬编码
3. 新增 `Agent._skill_registry` 属性
4. 新增 `Agent.activate_skill(name)` 方法 — CLI 手动激活
5. 新增 `Agent.deactivate_skill()` 方法

修改后的 `__init__` 签名：
```python
def __init__(
    self,
    llm: LLMClient,
    registry: ToolRegistry,
    settings: Settings,
    memory_manager: MemoryManager | None = None,
    prompt_manager: "PromptManager | None" = None,
) -> None:
```

system prompt 初始化逻辑：
```python
# 如果提供了 PromptManager，使用它；否则从默认文件加载
if prompt_manager is not None:
    system_content = prompt_manager.get_system_prompt()
else:
    from my_small_agent.prompt import PromptManager as _PM
    _default_pm = _PM()
    system_content = _default_pm.get_system_prompt()

self.messages: list[dict] = [
    {"role": "system", "content": system_content}
]
```

新增方法：
```python
def activate_skill(self, name: str) -> str:
    """
    CLI 手动激活技能。

    构造模拟的 assistant tool_call + tool result 消息对注入 self.messages，
    使 LLM 后续能看到技能指令。
    user_invocable: false 的技能拒绝手动激活。
    """
    if self._skill_registry is None:
        return "Error: Skill registry not initialized."
    skill = self._skill_registry.get_skill(name)
    if skill is None:
        return f"Error: Skill '{name}' not found."
    if not skill.user_invocable:
        return f"Error: Skill '{name}' is auto-only and cannot be manually activated."

    result_json = self._skill_registry.activate(name)
    parsed = json.loads(result_json)

    # 构造模拟消息对
    tool_call_id = f"manual_{uuid4().hex[:8]}"
    self.messages.append({
        "role": "assistant",
        "content": None,
        "tool_calls": [{
            "id": tool_call_id,
            "type": "function",
            "function": {
                "name": "activate_skill",
                "arguments": json.dumps({"skill_name": name}),
            },
        }],
    })
    self.messages.append({
        "role": "tool",
        "tool_call_id": tool_call_id,
        "content": parsed["prompt_text"],
    })
    return f"Skill '{name}' activated."


def deactivate_skill(self) -> str:
    """CLI 手动取消技能。"""
    if self._skill_registry is None:
        return "No skill registry."
    return self._skill_registry.deactivate()
```

- [ ] **Step 4: 修改 __main__.py**

在 `main()` 函数中，步骤 4（注册表创建）和步骤 5（Agent 创建）之间插入 skill 相关初始化：

```python
from my_small_agent.skills import discover_skills, skill_registry, build_skills_index
from my_small_agent.skills import register_skill_tools
from my_small_agent.prompt import PromptManager
from my_small_agent.tools.research_topic import ResearchTopicTool

# 4.5 发现并注册所有技能
discover_skills()

# 4.6 注册 skill 工具 + 组合工具到 ToolRegistry
register_skill_tools(registry, skill_registry)
registry.register(ResearchTopicTool(registry))

# 4.7 初始化 PromptManager
prompt_manager = PromptManager()
prompt_manager.update_skills_index(build_skills_index())

# 5. 创建 Agent（修改：增加 prompt_manager 参数）
agent = Agent(llm_client, registry, settings, memory_manager=memory_manager, prompt_manager=prompt_manager)
agent._skill_registry = skill_registry
```

- [ ] **Step 5: 在 skills/__init__.py 中新增 register_skill_tools 函数**

```python
def register_skill_tools(tool_registry, skill_reg: SkillRegistry) -> None:
    """将 activate_skill 和 deactivate_skill 工具注册到 ToolRegistry。"""
    from my_small_agent.tools.activate_skill import ActivateSkillTool
    from my_small_agent.tools.deactivate_skill import DeactivateSkillTool
    tool_registry.register(ActivateSkillTool(skill_reg))
    tool_registry.register(DeactivateSkillTool(skill_reg))
```

- [ ] **Step 6: 更新现有 Agent 测试的初始化方式**

检查 `tests/test_agent.py` 和 `tests/test_agent_stream.py`，在 Agent 初始化处确保兼容新增的可选 `prompt_manager` 参数（默认 None 应保持向后兼容，无需修改现有测试）。

验证：
Run: `cd c:\Users\chancemate\Desktop\MySmallAgent && uv run pytest tests/test_agent.py tests/test_agent_stream.py -v`
Expected: All existing tests still PASS

- [ ] **Step 7: 运行新增测试确认通过**

Run: `cd c:\Users\chancemate\Desktop\MySmallAgent && uv run pytest tests/test_agent_skill.py -v`
Expected: All tests PASS

- [ ] **Step 8: 运行全量测试确认无回归**

Run: `cd c:\Users\chancemate\Desktop\MySmallAgent && uv run pytest -v`
Expected: All tests PASS (no regressions)

- [ ] **Step 9: 提交**

```bash
git add my_small_agent/agent.py my_small_agent/__main__.py my_small_agent/skills/__init__.py my_small_agent/tools/__init__.py tests/test_agent_skill.py
git commit -m "feat: integrate PromptManager and skill activation into Agent"
```

---

### Task 6: CLI 新增 /skills、/skill、/unskill 命令 + /status 增强

**Files:**
- Modify: `my_small_agent/cli.py` — 新增命令处理和显示逻辑
- Test: `tests/test_cli_skills.py`

**Interfaces:**
- Consumes:
  - `Agent.activate_skill(name) -> str` (from Task 5)
  - `Agent.deactivate_skill() -> str` (from Task 5)
  - `Agent._skill_registry.get_all_names()`, `get_skill()`, `get_active()` (from Task 1)
- Produces:
  - CLI commands: `/skills`, `/skill <name>`, `/unskill`
  - `/status` 面板新增 "当前技能" 行
  - `/help` 和 `_print_welcome` 更新

- [ ] **Step 1: 编写失败测试**

```python
# tests/test_cli_skills.py
"""CLI 技能命令测试。"""

import pytest
from unittest.mock import MagicMock, AsyncMock, patch
from io import StringIO

from my_small_agent.cli import CLI
from my_small_agent.agent import Agent
from my_small_agent.skills.registry import SkillInfo, SkillRegistry


@pytest.fixture
def mock_cli():
    """创建一个用于测试的 CLI 实例（mock Agent 和 SessionManager）。"""
    agent = MagicMock(spec=Agent)
    agent.streaming_enabled = True
    agent.thinking_enabled = True
    agent.session_id = "test-session-id"
    agent.session_title = "Test"
    agent.messages = [{"role": "system", "content": "prompt"}]
    agent.settings = MagicMock()
    agent.settings.max_context_tokens = 100000
    agent.estimate_tokens = MagicMock(return_value=5000)
    agent.llm = MagicMock()
    agent.llm.model = "test-model"

    # Skill registry
    skill_reg = SkillRegistry()
    skill_reg.register(SkillInfo(name="research", description="Research expert", prompt_text="Research mode"))
    skill_reg.register(SkillInfo(name="code_assistant", description="Code helper", prompt_text="Code mode"))
    skill_reg.register(SkillInfo(name="auto_skill", description="Auto only", prompt_text="Auto", user_invocable=False))
    agent._skill_registry = skill_reg

    agent.activate_skill = MagicMock(return_value="Skill 'research' activated.")
    agent.deactivate_skill = MagicMock(return_value="Skill 'research' deactivated.")

    session_manager = MagicMock()
    cli = CLI(agent, session_manager)
    return cli


class TestSkillsCommand:
    """测试 /skills 命令。"""

    @pytest.mark.asyncio
    async def test_skills_lists_all(self, mock_cli, capsys):
        await mock_cli._handle_command("/skills")
        # 验证 console 输出（通过 mock 的 print 调用检查）
        # 由于 rich Console 直接输出到终端，我们检查 print 被调用
        mock_cli.console.print.assert_called()

    @pytest.mark.asyncio
    async def test_skill_activate(self, mock_cli):
        await mock_cli._handle_command("/skill research")
        mock_cli.agent.activate_skill.assert_called_once_with("research")

    @pytest.mark.asyncio
    async def test_skill_no_args_shows_usage(self, mock_cli):
        await mock_cli._handle_command("/skill")
        mock_cli.console.print.assert_called()

    @pytest.mark.asyncio
    async def test_unskill(self, mock_cli):
        await mock_cli._handle_command("/unskill")
        mock_cli.agent.deactivate_skill.assert_called_once()
```

- [ ] **Step 2: 运行测试确认失败**

Run: `cd c:\Users\chancemate\Desktop\MySmallAgent && uv run pytest tests/test_cli_skills.py -v`
Expected: FAIL — /skills 等命令未实现

- [ ] **Step 3: 修改 cli.py — 新增命令路由**

在 `_handle_command` 方法（第 225 行起）的命令分支中添加：

```python
elif cmd == "/skills":
    self._print_skills()
elif cmd == "/skill":
    self._activate_skill(command)
elif cmd == "/unskill":
    self._deactivate_skill()
```

- [ ] **Step 4: 实现 _print_skills 方法**

```python
def _print_skills(self) -> None:
    """列出所有可用技能，标记当前激活的和 auto-only 的。"""
    skill_reg = getattr(self.agent, '_skill_registry', None)
    if skill_reg is None:
        self.console.print("[yellow]技能系统未初始化。[/yellow]")
        return

    names = skill_reg.get_all_names()
    if not names:
        self.console.print("[dim]暂无可用技能。[/dim]")
        return

    active = skill_reg.get_active()
    lines = []
    for name in names:
        skill = skill_reg.get_skill(name)
        if skill is None:
            continue
        marker = "[cyan]▶[/cyan] " if (active and active.name == name) else "  "
        invocable_tag = "" if skill.user_invocable else " [dim](auto-only)[/dim]"
        lines.append(f"{marker}[bold]{skill.name}[/bold]{invocable_tag}\n    [dim]{skill.description}[/dim]")

    self.console.print(
        Panel(
            "\n\n".join(lines),
            title=f"可用技能 ({len(names)})",
            border_style="magenta",
        )
    )
```

- [ ] **Step 5: 实现 _activate_skill 和 _deactivate_skill 方法**

```python
def _activate_skill(self, command: str) -> None:
    """手动激活指定技能。"""
    parts = command.strip().split(maxsplit=1)
    if len(parts) < 2 or not parts[1].strip():
        self.console.print(
            "[yellow]用法：/skill <name>[/yellow]\n"
            "  使用 /skills 查看可用技能列表"
        )
        return
    name = parts[1].strip()
    result = self.agent.activate_skill(name)
    if "error" in result.lower():
        self.console.print(f"[red]{result}[/red]")
    else:
        self.console.print(f"[green]✓ {result}[/green]")

def _deactivate_skill(self) -> None:
    """取消当前激活的技能。"""
    result = self.agent.deactivate_skill()
    self.console.print(f"[cyan]{result}[/cyan]")
```

- [ ] **Step 6: 修改 _print_status — 新增 Active Skill 行**

在 `_print_status` 方法中 Panel 内容新增一行：

```python
skill_reg = getattr(self.agent, '_skill_registry', None)
active_skill = skill_reg.get_active() if skill_reg else None
skill_display = f"[green]{active_skill.name}[/green]" if active_skill else "[dim]无[/dim]"
```

并在面板内容中加入 `f"  当前技能:   {skill_display}\n"`。

- [ ] **Step 7: 更新 _print_welcome 和 _print_help**

在欢迎面板和帮助面板中各添加 3 行：
```
  /skills  - List available skills
  /skill   - Activate a skill: /skill <name>
  /unskill - Deactivate current skill
```

- [ ] **Step 8: 运行测试确认通过**

Run: `cd c:\Users\chancemate\Desktop\MySmallAgent && uv run pytest tests/test_cli_skills.py -v`
Expected: All tests PASS

- [ ] **Step 9: 运行全量测试确认无回归**

Run: `cd c:\Users\chancemate\Desktop\MySmallAgent && uv run pytest -v`
Expected: All tests PASS

- [ ] **Step 10: 提交**

```bash
git add my_small_agent/cli.py tests/test_cli_skills.py
git commit -m "feat: add /skills, /skill, /unskill CLI commands and /status enhancement"
```

---

### Task 7: 全量集成验证 + 现有测试适配

**Files:**
- Modify: `tests/test_agent.py` — 如需适配新参数
- Modify: `tests/test_agent_stream.py` — 如需适配新参数
- No new files

**Interfaces:**
- Consumes: All above tasks
- Produces: 全量测试通过的确认

- [ ] **Step 1: 运行全量测试**

Run: `cd c:\Users\chancemate\Desktop\MySmallAgent && uv run pytest -v`

如果有失败的现有测试，分析原因并修复。典型需要修复的情况：
- `test_agent.py` 中 Agent 初始化如果依赖 `SYSTEM_PROMPT` 常量（已删除），需要改为从 PromptManager 获取或 mock
- `test_agent.py` 中如果断言 `messages[0]["content"]` 等于特定字符串，需要更新

- [ ] **Step 2: 修复任何回归测试**

逐个修复失败的测试，确保：
- Agent 无 prompt_manager 参数时仍可正常工作（回退到默认 PromptManager）
- 旧测试不依赖被删除的 `SYSTEM_PROMPT` 常量

- [ ] **Step 3: 全量测试确认通过**

Run: `cd c:\Users\chancemate\Desktop\MySmallAgent && uv run pytest -v`
Expected: ALL tests PASS (0 failures)

- [ ] **Step 4: 提交（如有修改）**

```bash
git add -A
git commit -m "fix: adapt existing tests for skill system integration"
```
