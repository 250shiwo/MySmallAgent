"""
Plan 模块 - 计划数据结构、LLM 输出解析器和渲染函数。

包含：
  - PlanPhase / StepStatus: 枚举类型，标识计划阶段和步骤状态
  - PlanStep / Plan: 数据类，结构化表示计划
  - parse_plan(): 从 LLM 文本输出解析为 Plan 对象
  - render_plan_review(): 渲染计划审阅面板
  - render_plan_progress(): 渲染执行进度面板
  - render_plan_summary(): 渲染完成摘要
"""

import re
from dataclasses import dataclass
from enum import Enum, auto
from typing import Optional


class PlanPhase(Enum):
    """计划生命周期阶段。"""
    PLANNING = auto()    # Agent 使用只读工具探索并生成计划
    REVIEWING = auto()   # 用户审阅计划，可接受/修改/取消
    EXECUTING = auto()   # 计划被接受，逐步执行中
    COMPLETED = auto()   # 所有步骤完成（成功或失败）


class StepStatus(Enum):
    """步骤执行状态。"""
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    DONE = "done"
    FAILED = "failed"
    SKIPPED = "skipped"


@dataclass
class PlanStep:
    """计划中的单个步骤。"""
    index: int              # 1-based 步骤编号
    title: str              # 简短标题（一行）
    description: str        # 详细描述
    status: StepStatus = StepStatus.PENDING


@dataclass
class Plan:
    """完整计划，包含目标和步骤列表。"""
    goal: str                               # 用户原始目标
    steps: list[PlanStep]                   # 步骤列表
    phase: PlanPhase = PlanPhase.PLANNING   # 当前阶段
    raw_plan_text: str = ""                 # LLM 原始输出


# === 解析器 ===

# 步骤正则：编号 + 标题（bold 或纯文本）+ 分隔符 + 描述
_STEP_RE = re.compile(
    r"(?:^|\n)\s*(?:\d+[\.\)])\s+"       # 编号: 1. 或 1)
    r"(?:\*\*(.+?)\*\*|(.+?))"            # 标题: **bold** 或纯文本
    r"\s*(?:--|-|:|—|–)\s*"               # 分隔符: -- - : — –
    r"(.+?)(?=\n\s*\d+[\.\)]|\Z)",        # 描述: 到下一个编号或文末
    re.DOTALL,
)

# Plan 区块正则：## Plan 或 ## Execution Plan 到下一个 ## 或文末
_PLAN_BLOCK_RE = re.compile(
    r"(?:##\s*Plan|##\s*Execution\s*Plan)\s*\n(.*?)(?:\n##\s|\Z)",
    re.DOTALL | re.IGNORECASE,
)

# Goal 正则
_GOAL_RE = re.compile(r"\*\*Goal\*\*:\s*(.+?)(?:\n|$)", re.IGNORECASE)


def parse_plan(llm_output: str, user_goal: str = "") -> Optional[Plan]:
    """
    从 LLM 文本输出解析结构化计划。

    解析策略：
      1. 查找 ## Plan 或 ## Execution Plan 区块
      2. 在区块内提取 Goal 和 Steps
      3. 未找到区块时走宽松回退，在全文搜索编号步骤
      4. 至少 2 个步骤才算有效计划

    参数：
      llm_output: LLM 的完整文本输出
      user_goal: 用户原始目标（Goal 未找到时回退使用）

    返回：
      Plan 对象，解析失败返回 None
    """
    if not llm_output or not llm_output.strip():
        return None

    # 1. 查找 ## Plan 区块
    plan_match = _PLAN_BLOCK_RE.search(llm_output)
    if plan_match:
        plan_text = plan_match.group(1)
        # 2. 提取 Goal
        goal_match = _GOAL_RE.search(plan_text)
        goal = goal_match.group(1).strip() if goal_match else user_goal
        # 3. 提取 Steps
        steps = _parse_steps(plan_text)
        if len(steps) >= 2:
            return Plan(
                goal=goal,
                steps=steps,
                raw_plan_text=llm_output,
            )

    # 4. 宽松回退
    return _try_parse_loose(llm_output, user_goal)


def _parse_steps(text: str) -> list[PlanStep]:
    """从文本中解析编号步骤列表。"""
    steps = []
    for match in _STEP_RE.finditer(text):
        # group(1) = bold 标题, group(2) = 纯文本标题, group(3) = 描述
        title = (match.group(1) or match.group(2) or "").strip()
        description = (match.group(3) or "").strip()
        if title:
            steps.append(PlanStep(
                index=len(steps) + 1,
                title=title,
                description=description,
            ))
    return steps


def _try_parse_loose(text: str, user_goal: str) -> Optional[Plan]:
    """
    宽松回退解析：在全文中搜索编号步骤。

    需要至少 2 个步骤才能成功解析。
    """
    steps = _parse_steps(text)
    if len(steps) < 2:
        return None
    return Plan(
        goal=user_goal,
        steps=steps,
        raw_plan_text=text,
    )


# === 渲染函数 ===

from rich.panel import Panel


# 状态图标和颜色映射
_STATUS_ICONS = {
    StepStatus.PENDING: ("○", "dim", "Pending"),
    StepStatus.IN_PROGRESS: ("●", "yellow", "In Progress..."),
    StepStatus.DONE: ("✓", "green", "Done"),
    StepStatus.FAILED: ("✗", "red", "Failed"),
    StepStatus.SKIPPED: ("—", "dim", "Skipped"),
}


def render_plan_review(plan: "Plan", console) -> None:
    """
    渲染计划审阅面板（品红色边框）。

    展示 Goal 和所有步骤的标题 + 描述，
    供用户审阅后选择 Accept / Modify / Cancel。
    """
    lines = [f"[bold]Goal:[/bold] {plan.goal}\n"]
    lines.append("[bold]Proposed Steps:[/bold]")
    for step in plan.steps:
        lines.append(f"  [cyan]{step.index}.[/cyan] [bold]{step.title}[/bold]")
        lines.append(f"     [dim]{step.description}[/dim]")
    content = "\n".join(lines)
    console.print(Panel(content, title="Plan Mode", border_style="magenta"))


def render_plan_progress(plan: "Plan", console) -> None:
    """
    渲染执行进度面板。

    展示每个步骤的当前状态，用图标和颜色区分：
      ○ Pending（暗色）
      ● In Progress（黄色）
      ✓ Done（绿色）
      ✗ Failed（红色）
      — Skipped（暗色）
    """
    lines = []
    for step in plan.steps:
        icon, color, label = _STATUS_ICONS[step.status]
        lines.append(
            f"  [{color}]{icon}[/{color}]  "
            f"Step {step.index}: {step.title}  "
            f"[{color}]{label}[/{color}]"
        )
    content = "\n".join(lines)
    console.print(Panel(content, title="Plan Progress", border_style="cyan"))


def render_plan_summary(plan: "Plan", console) -> None:
    """
    渲染完成摘要面板。

    边框颜色：无失败为绿色，有失败为黄色。
    """
    done_count = sum(1 for s in plan.steps if s.status == StepStatus.DONE)
    failed_count = sum(1 for s in plan.steps if s.status == StepStatus.FAILED)
    skipped_count = sum(1 for s in plan.steps if s.status == StepStatus.SKIPPED)
    total = len(plan.steps)

    parts = [f"{done_count} completed", f"{failed_count} failed"]
    if skipped_count > 0:
        parts.append(f"{skipped_count} skipped")
    content = ", ".join(parts) + f" (of {total} total)"

    border_color = "yellow" if failed_count > 0 else "green"
    console.print(Panel(content, title="Plan Complete", border_style=border_color))
