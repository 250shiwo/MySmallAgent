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
