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
