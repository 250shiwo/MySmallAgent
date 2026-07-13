# Plan Mode 生命周期实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 为现有基础 Plan 模式新增完整的计划生命周期：结构化数据、LLM 输出解析、交互式审阅（Accept/Modify/Cancel）、逐步执行与进度跟踪、完成摘要统计。

**Architecture:** 新增 `plan.py` 模块包含数据结构 + 解析器 + 渲染函数（纯函数，易于测试）。增强 `prompt.py` 的 Plan 提示词为两阶段流程指令。在 `agent.py` 新增 `evaluate_step_success()` 方法。在 `cli.py` 新增 Plan 生命周期编排逻辑。新增 `questionary` 依赖实现方向键导航。

**Tech Stack:** Python 3.11+, Rich, prompt_toolkit, questionary, pytest, pytest-asyncio

## Global Constraints

- Python >= 3.11
- 测试运行命令: `uv run pytest`
- 依赖安装命令: `uv sync`
- asyncio_mode = "auto" (pytest-asyncio)
- 所有代码注释使用中文
- 遵循现有代码风格（dataclass, type hints, docstring）
- 新增依赖: questionary>=2.0

---

## File Structure

### 新增文件
- `my_small_agent/plan.py` — Plan 数据结构（PlanPhase, StepStatus, PlanStep, Plan）+ 解析器（parse_plan）+ 渲染函数（render_plan_review, render_plan_summary, render_plan_progress）
- `tests/test_plan_parser.py` — 解析器单元测试
- `tests/test_plan_mode_lifecycle.py` — 生命周期集成测试

### 修改文件
- `pyproject.toml` — 添加 questionary 依赖
- `my_small_agent/prompt.py` — 增强 _PLAN_PROMPT 为两阶段流程指令
- `my_small_agent/agent.py` — 新增 evaluate_step_success() 方法
- `my_small_agent/cli.py` — 新增 Plan 生命周期编排（_run_plan_turn, _review_plan, _execute_plan）
- `tests/test_plan_mode.py` — 更新现有测试断言

---

### Task 1: 添加 questionary 依赖

**Files:**
- Modify: `pyproject.toml`

**Interfaces:**
- Produces: questionary 包可在项目中 import

- [ ] **Step 1: 添加 questionary 到 pyproject.toml**

在 `pyproject.toml` 的 `dependencies` 列表中添加 `questionary>=2.0`：

```toml
dependencies = [
    "openai>=1.0",
    "pydantic-settings>=2.0",
    "prompt-toolkit>=3.0",
    "rich>=13.0",
    "ddgs>=7.0",
    "httpx>=0.27",
    "tzdata; sys_platform == 'win32'",
    "questionary>=2.0",
]
```

- [ ] **Step 2: 安装依赖**

Run: `uv sync`
Expected: 成功安装 questionary 及其依赖

- [ ] **Step 3: 验证导入**

Run: `uv run python -c "import questionary; print(questionary.__version__)"`
Expected: 打印版本号，无报错

- [ ] **Step 4: 运行现有测试确保无破坏**

Run: `uv run pytest tests/ -q`
Expected: 207 passed

- [ ] **Step 5: Commit**

```bash
git add pyproject.toml uv.lock
git commit -m "deps: add questionary for plan mode arrow-key navigation"
```

---

### Task 2: Plan 数据结构与解析器

**Files:**
- Create: `my_small_agent/plan.py`
- Create: `tests/test_plan_parser.py`

**Interfaces:**
- Produces: `PlanPhase`, `StepStatus`, `PlanStep`, `Plan` 数据结构；`parse_plan(llm_output: str, user_goal: str = "") -> Optional[Plan]` 函数

- [ ] **Step 1: 编写解析器失败测试**

创建 `tests/test_plan_parser.py`：

```python
"""Plan 解析器测试 - 数据结构和 LLM 输出解析。"""

import re
from my_small_agent.plan import PlanPhase, StepStatus, PlanStep, Plan, parse_plan


class TestPlanDataStructures:
    """Plan 数据结构基础测试。"""

    def test_plan_phase_values(self):
        """PlanPhase 应有四个阶段。"""
        assert PlanPhase.PLANNING
        assert PlanPhase.REVIEWING
        assert PlanPhase.EXECUTING
        assert PlanPhase.COMPLETED

    def test_step_status_values(self):
        """StepStatus 应有五个状态值。"""
        assert StepStatus.PENDING.value == "pending"
        assert StepStatus.IN_PROGRESS.value == "in_progress"
        assert StepStatus.DONE.value == "done"
        assert StepStatus.FAILED.value == "failed"
        assert StepStatus.SKIPPED.value == "skipped"

    def test_plan_step_defaults(self):
        """PlanStep 默认状态应为 PENDING。"""
        step = PlanStep(index=1, title="Test", description="Do something")
        assert step.status == StepStatus.PENDING

    def test_plan_defaults(self):
        """Plan 默认阶段应为 PLANNING，raw_plan_text 为空。"""
        plan = Plan(goal="Test goal", steps=[])
        assert plan.phase == PlanPhase.PLANNING
        assert plan.raw_plan_text == ""


class TestParsePlanStandardFormat:
    """标准 ## Plan 格式解析测试。"""

    def test_standard_format(self):
        """标准 ## Plan + ### Steps + **标题** -- 描述 格式。"""
        llm_output = """## Plan
**Goal**: 重构认证模块

### Steps
1. **分析现有代码** -- 读取 auth/ 目录下的所有文件
2. **提取认证逻辑** -- 创建 auth/handler.py
3. **更新导入** -- 修改 main.py 中的导入路径
"""
        plan = parse_plan(llm_output, user_goal="重构认证模块")
        assert plan is not None
        assert plan.goal == "重构认证模块"
        assert len(plan.steps) == 3
        assert plan.steps[0].index == 1
        assert plan.steps[0].title == "分析现有代码"
        assert plan.steps[0].description == "读取 auth/ 目录下的所有文件"
        assert plan.steps[0].status == StepStatus.PENDING
        assert plan.steps[2].title == "更新导入"

    def test_execution_plan_heading(self):
        """## Execution Plan 标题也能解析。"""
        llm_output = """## Execution Plan
**Goal**: Fix the bug

### Steps
1. **Locate bug** -- Find the error in parser.py
2. **Fix bug** -- Patch the regex pattern
"""
        plan = parse_plan(llm_output)
        assert plan is not None
        assert plan.goal == "Fix the bug"
        assert len(plan.steps) == 2

    def test_no_goal_uses_user_goal(self):
        """LLM 输出无 Goal 时回退到 user_goal 参数。"""
        llm_output = """## Plan

### Steps
1. **Step A** -- Do A
2. **Step B** -- Do B
"""
        plan = parse_plan(llm_output, user_goal="用户的目标")
        assert plan is not None
        assert plan.goal == "用户的目标"

    def test_parenthesis_numbering(self):
        """1) 编号格式也能解析。"""
        llm_output = """## Plan
**Goal**: Test

### Steps
1) **First step** -- Do first
2) **Second step** -- Do second
"""
        plan = parse_plan(llm_output)
        assert plan is not None
        assert len(plan.steps) == 2
        assert plan.steps[0].title == "First step"

    def test_plain_text_title(self):
        """纯文本标题（非 bold）也能解析。"""
        llm_output = """## Plan
**Goal**: Test

### Steps
1. First step -- Do first
2. Second step -- Do second
"""
        plan = parse_plan(llm_output)
        assert plan is not None
        assert len(plan.steps) == 2
        assert plan.steps[0].title == "First step"

    def test_em_dash_separator(self):
        """em dash (—) 分隔符也能解析。"""
        llm_output = """## Plan
**Goal**: Test

### Steps
1. **Step A** — Do A
2. **Step B** — Do B
"""
        plan = parse_plan(llm_output)
        assert plan is not None
        assert len(plan.steps) == 2

    def test_colon_separator(self):
        """冒号分隔符也能解析。"""
        llm_output = """## Plan
**Goal**: Test

### Steps
1. **Step A**: Do A
2. **Step B**: Do B
"""
        plan = parse_plan(llm_output)
        assert plan is not None
        assert len(plan.steps) == 2

    def test_raw_plan_text_stored(self):
        """解析后 raw_plan_text 应保存原始 LLM 输出。"""
        llm_output = """## Plan
**Goal**: Test

### Steps
1. **Step A** -- Do A
2. **Step B** -- Do B
"""
        plan = parse_plan(llm_output)
        assert plan is not None
        assert plan.raw_plan_text == llm_output


class TestParsePlanLooseFallback:
    """宽松回退解析测试。"""

    def test_loose_parse_without_plan_heading(self):
        """无 ## Plan 区块但有编号步骤时走宽松回退。"""
        llm_output = """我先分析了代码，然后制定以下计划：

1. **分析现有代码** -- 读取所有相关文件
2. **修改配置** -- 更新 config.py
3. **运行测试** -- 验证修改正确
"""
        plan = parse_plan(llm_output, user_goal="修改配置")
        assert plan is not None
        assert len(plan.steps) == 3
        assert plan.goal == "修改配置"

    def test_loose_parse_plain_text_steps(self):
        """宽松回退也支持纯文本标题。"""
        llm_output = """我的计划如下：

1. First -- do first thing
2. Second -- do second thing
"""
        plan = parse_plan(llm_output)
        assert plan is not None
        assert len(plan.steps) == 2


class TestParsePlanEdgeCases:
    """边界情况测试。"""

    def test_empty_string(self):
        """空字符串应返回 None。"""
        assert parse_plan("") is None

    def test_no_numbered_steps(self):
        """无编号步骤应返回 None。"""
        llm_output = "这是一段普通文本，没有计划步骤。"
        assert parse_plan(llm_output) is None

    def test_single_step_returns_none(self):
        """单个编号步骤不算计划，返回 None。"""
        llm_output = """## Plan

### Steps
1. **Only step** -- Do the only step
"""
        plan = parse_plan(llm_output)
        assert plan is None

    def test_single_step_loose_returns_none(self):
        """宽松回退时单个步骤也返回 None。"""
        llm_output = "1. **Only step** -- Do something"
        assert parse_plan(llm_output) is None

    def test_plan_with_extra_sections(self):
        """Plan 区块后跟其他 ## 区块时只解析 Plan 部分。"""
        llm_output = """## Plan
**Goal**: Test

### Steps
1. **Step A** -- Do A
2. **Step B** -- Do B

## Notes
Some additional notes here.
"""
        plan = parse_plan(llm_output)
        assert plan is not None
        assert len(plan.steps) == 2
        assert plan.goal == "Test"
```

- [ ] **Step 2: 运行测试验证失败**

Run: `uv run pytest tests/test_plan_parser.py -v`
Expected: FAIL with "No module named 'my_small_agent.plan'"

- [ ] **Step 3: 实现 plan.py**

创建 `my_small_agent/plan.py`：

```python
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
```

- [ ] **Step 4: 运行测试验证通过**

Run: `uv run pytest tests/test_plan_parser.py -v`
Expected: 所有测试 PASS

- [ ] **Step 5: 运行全量测试确保无破坏**

Run: `uv run pytest tests/ -q`
Expected: 所有测试 PASS（207 + 新增 = 224+）

- [ ] **Step 6: Commit**

```bash
git add my_small_agent/plan.py tests/test_plan_parser.py
git commit -m "feat: add plan data structures and parser"
```

---

### Task 3: 增强 Plan 提示词

**Files:**
- Modify: `my_small_agent/prompt.py:16-32`
- Modify: `tests/test_plan_mode.py:154-168`

**Interfaces:**
- Consumes: `PLAN_MODE_MARKER` from prompt.py (existing)
- Produces: 更新后的 `_PLAN_PROMPT` 包含两阶段流程指令和固定输出格式

- [ ] **Step 1: 更新现有测试断言**

修改 `tests/test_plan_mode.py` 中的 `TestPromptManagerPlanPrompt` 类：

```python
class TestPromptManagerPlanPrompt:
    def test_get_plan_prompt_contains_marker(self):
        """get_plan_prompt 返回的内容应包含 PLAN_MODE_MARKER。"""
        pm = PromptManager()
        prompt = pm.get_plan_prompt()
        assert PLAN_MODE_MARKER in prompt

    def test_get_plan_prompt_contains_instructions(self):
        """get_plan_prompt 应包含关键指令。"""
        pm = PromptManager()
        prompt = pm.get_plan_prompt()
        assert "计划模式" in prompt
        assert "探索与信息收集" in prompt
        assert "生成计划" in prompt

    def test_plan_prompt_contains_format_specification(self):
        """plan prompt 应包含输出格式规范。"""
        pm = PromptManager()
        prompt = pm.get_plan_prompt()
        assert "## Plan" in prompt
        assert "**Goal**" in prompt
        assert "### Steps" in prompt
        assert "**标题**" in prompt
```

- [ ] **Step 2: 运行测试验证失败**

Run: `uv run pytest tests/test_plan_mode.py::TestPromptManagerPlanPrompt -v`
Expected: FAIL — "探索与信息收集" 不在当前 prompt 中

- [ ] **Step 3: 更新 _PLAN_PROMPT**

修改 `my_small_agent/prompt.py` 中的 `_PLAN_PROMPT` 变量（第 16-32 行）：

```python
_PLAN_PROMPT = f"""{PLAN_MODE_MARKER}

## 计划模式（Plan Mode）

你当前处于计划模式。请严格遵循两阶段流程：

### 阶段一 — 探索与信息收集
1. 使用只读工具（read_file、list_directory、grep_search、tree、find_file 等）充分探索代码库
2. 读取所有相关文件，搜索已有模式和工具函数，追踪依赖关系
3. 记录精确的文件路径、行号、函数名和变量名
4. 识别每个需要创建或修改的文件
5. 如果用户请求存在歧义，基于代码上下文做出合理推断

### 阶段二 — 生成计划
仅在阶段一完成后才输出计划。输出格式必须严格如下：

## Plan
**Goal**: <一句话目标>

### Steps
1. **<标题>** -- <详细描述，含文件路径、行号或函数名、具体变更内容、预期结果>
2. **<标题>** -- <详细描述>
...

### 计划要求
- 步骤数 3-10 个，按依赖排序
- 标题不超过 60 字符
- 每个步骤描述必须包含：具体文件路径、行号或函数名、具体变更内容、预期结果
- 禁止出现"确认"、"询问用户"、"根据用户选择"、"待定"等需要运行时交互的措辞
- 结尾包含验证步骤
- 如果信息确实不足，明确标注假设前提，而非推迟到执行时询问用户
"""
```

- [ ] **Step 4: 运行测试验证通过**

Run: `uv run pytest tests/test_plan_mode.py::TestPromptManagerPlanPrompt -v`
Expected: 所有 3 个测试 PASS

- [ ] **Step 5: 运行全量测试确保无破坏**

Run: `uv run pytest tests/ -q`
Expected: 所有测试 PASS

- [ ] **Step 6: Commit**

```bash
git add my_small_agent/prompt.py tests/test_plan_mode.py
git commit -m "feat: enhance plan prompt with two-phase instructions and format spec"
```

---

### Task 4: Plan 渲染函数

**Files:**
- Modify: `my_small_agent/plan.py` (追加渲染函数)
- Modify: `tests/test_plan_parser.py` (追加渲染测试)

**Interfaces:**
- Consumes: `Plan`, `PlanStep`, `StepStatus` from plan.py; `Console` from rich
- Produces: `render_plan_review(plan, console)`, `render_plan_progress(plan, console)`, `render_plan_summary(plan, console)`

- [ ] **Step 1: 编写渲染函数失败测试**

在 `tests/test_plan_parser.py` 末尾追加：

```python
from io import StringIO
from rich.console import Console

from my_small_agent.plan import render_plan_review, render_plan_progress, render_plan_summary


def _capture_render(render_fn, plan) -> str:
    """用 Rich Console 捕获渲染输出为字符串。"""
    console = Console(file=StringIO(), width=80, force_terminal=False)
    render_fn(plan, console)
    return console.file.getvalue()


class TestRenderPlanReview:
    """计划审阅面板渲染测试。"""

    def test_review_contains_goal(self):
        """审阅面板应包含 Goal。"""
        plan = Plan(
            goal="重构认证模块",
            steps=[
                PlanStep(index=1, title="分析代码", description="读取文件"),
                PlanStep(index=2, title="修改代码", description="写入文件"),
            ],
        )
        output = _capture_render(render_plan_review, plan)
        assert "重构认证模块" in output

    def test_review_contains_step_titles(self):
        """审阅面板应包含所有步骤标题。"""
        plan = Plan(
            goal="Test",
            steps=[
                PlanStep(index=1, title="分析代码", description="读取文件"),
                PlanStep(index=2, title="修改代码", description="写入文件"),
            ],
        )
        output = _capture_render(render_plan_review, plan)
        assert "分析代码" in output
        assert "修改代码" in output

    def test_review_contains_step_descriptions(self):
        """审阅面板应包含步骤描述。"""
        plan = Plan(
            goal="Test",
            steps=[
                PlanStep(index=1, title="Step A", description="读取 auth/ 目录"),
                PlanStep(index=2, title="Step B", description="创建 handler.py"),
            ],
        )
        output = _capture_render(render_plan_review, plan)
        assert "读取 auth/ 目录" in output
        assert "创建 handler.py" in output

    def test_review_panel_border_magenta(self):
        """审阅面板边框应为品红色。"""
        plan = Plan(goal="Test", steps=[
            PlanStep(index=1, title="A", description="d"),
            PlanStep(index=2, title="B", description="d"),
        ])
        output = _capture_render(render_plan_review, plan)
        assert "Plan Mode" in output


class TestRenderPlanProgress:
    """执行进度面板渲染测试。"""

    def test_progress_shows_all_steps(self):
        """进度面板应显示所有步骤。"""
        plan = Plan(goal="Test", steps=[
            PlanStep(index=1, title="Step A", description="Do A"),
            PlanStep(index=2, title="Step B", description="Do B"),
        ])
        output = _capture_render(render_plan_progress, plan)
        assert "Step A" in output
        assert "Step B" in output

    def test_progress_shows_pending_status(self):
        """PENDING 步骤应显示 Pending。"""
        plan = Plan(goal="Test", steps=[
            PlanStep(index=1, title="Step A", description="Do A"),
            PlanStep(index=2, title="Step B", description="Do B"),
        ])
        output = _capture_render(render_plan_progress, plan)
        assert "Pending" in output

    def test_progress_shows_in_progress_status(self):
        """IN_PROGRESS 步骤应显示 In Progress。"""
        plan = Plan(goal="Test", steps=[
            PlanStep(index=1, title="Step A", description="Do A",
                     status=StepStatus.IN_PROGRESS),
            PlanStep(index=2, title="Step B", description="Do B"),
        ])
        output = _capture_render(render_plan_progress, plan)
        assert "In Progress" in output

    def test_progress_shows_done_status(self):
        """DONE 步骤应显示 Done。"""
        plan = Plan(goal="Test", steps=[
            PlanStep(index=1, title="Step A", description="Do A",
                     status=StepStatus.DONE),
            PlanStep(index=2, title="Step B", description="Do B"),
        ])
        output = _capture_render(render_plan_progress, plan)
        assert "Done" in output

    def test_progress_shows_failed_status(self):
        """FAILED 步骤应显示 Failed。"""
        plan = Plan(goal="Test", steps=[
            PlanStep(index=1, title="Step A", description="Do A",
                     status=StepStatus.FAILED),
            PlanStep(index=2, title="Step B", description="Do B"),
        ])
        output = _capture_render(render_plan_progress, plan)
        assert "Failed" in output

    def test_progress_shows_skipped_status(self):
        """SKIPPED 步骤应显示 Skipped。"""
        plan = Plan(goal="Test", steps=[
            PlanStep(index=1, title="Step A", description="Do A",
                     status=StepStatus.SKIPPED),
            PlanStep(index=2, title="Step B", description="Do B"),
        ])
        output = _capture_render(render_plan_progress, plan)
        assert "Skipped" in output


class TestRenderPlanSummary:
    """完成摘要渲染测试。"""

    def test_summary_all_done(self):
        """全部成功时摘要应显示正确统计。"""
        plan = Plan(goal="Test", steps=[
            PlanStep(index=1, title="A", description="d", status=StepStatus.DONE),
            PlanStep(index=2, title="B", description="d", status=StepStatus.DONE),
            PlanStep(index=3, title="C", description="d", status=StepStatus.DONE),
        ])
        output = _capture_render(render_plan_summary, plan)
        assert "3 completed" in output
        assert "0 failed" in output
        assert "3 total" in output

    def test_summary_with_failures(self):
        """有失败时摘要应显示失败数。"""
        plan = Plan(goal="Test", steps=[
            PlanStep(index=1, title="A", description="d", status=StepStatus.DONE),
            PlanStep(index=2, title="B", description="d", status=StepStatus.FAILED),
            PlanStep(index=3, title="C", description="d", status=StepStatus.SKIPPED),
        ])
        output = _capture_render(render_plan_summary, plan)
        assert "1 completed" in output
        assert "1 failed" in output
        assert "1 skipped" in output

    def test_summary_contains_complete_title(self):
        """摘要面板应包含 Plan Complete 标题。"""
        plan = Plan(goal="Test", steps=[
            PlanStep(index=1, title="A", description="d", status=StepStatus.DONE),
            PlanStep(index=2, title="B", description="d", status=StepStatus.DONE),
        ])
        output = _capture_render(render_plan_summary, plan)
        assert "Plan Complete" in output
```

- [ ] **Step 2: 运行测试验证失败**

Run: `uv run pytest tests/test_plan_parser.py::TestRenderPlanReview tests/test_plan_parser.py::TestRenderPlanProgress tests/test_plan_parser.py::TestRenderPlanSummary -v`
Expected: FAIL — "cannot import name 'render_plan_review'"

- [ ] **Step 3: 实现渲染函数**

在 `my_small_agent/plan.py` 末尾追加：

```python
# === 渲染函数 ===

from rich.panel import Panel
from rich.text import Text


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


# 状态图标和颜色映射
_STATUS_ICONS = {
    StepStatus.PENDING: ("○", "dim", "Pending"),
    StepStatus.IN_PROGRESS: ("●", "yellow", "In Progress..."),
    StepStatus.DONE: ("✓", "green", "Done"),
    StepStatus.FAILED: ("✗", "red", "Failed"),
    StepStatus.SKIPPED: ("—", "dim", "Skipped"),
}


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

    parts = [f"{done_count} completed"]
    if failed_count > 0:
        parts.append(f"{failed_count} failed")
    if skipped_count > 0:
        parts.append(f"{skipped_count} skipped")
    parts.append(f"of {total} total")
    content = ", ".join(parts[:-1]) + f" ({parts[-1]})"

    border_color = "yellow" if failed_count > 0 else "green"
    console.print(Panel(content, title="Plan Complete", border_style=border_color))
```

- [ ] **Step 4: 运行测试验证通过**

Run: `uv run pytest tests/test_plan_parser.py -v`
Expected: 所有测试 PASS

- [ ] **Step 5: 运行全量测试确保无破坏**

Run: `uv run pytest tests/ -q`
Expected: 所有测试 PASS

- [ ] **Step 6: Commit**

```bash
git add my_small_agent/plan.py tests/test_plan_parser.py
git commit -m "feat: add plan rendering functions (review, progress, summary)"
```

---

### Task 5: Agent evaluate_step_success 方法

**Files:**
- Modify: `my_small_agent/agent.py` (新增方法)
- Create: `tests/test_plan_mode_lifecycle.py`

**Interfaces:**
- Consumes: `PlanStep` from plan.py, `AgentResponse` from agent.py, `LLMClient` from llm.py
- Produces: `Agent.evaluate_step_success(step: PlanStep, response: AgentResponse) -> bool`

- [ ] **Step 1: 编写 evaluate_step_success 失败测试**

创建 `tests/test_plan_mode_lifecycle.py`：

```python
"""Plan 模式生命周期测试 - 审阅、执行、失败处理。"""

import json
from unittest.mock import AsyncMock, MagicMock

import pytest

from my_small_agent.agent import Agent, AgentResponse
from my_small_agent.config import Settings
from my_small_agent.llm import LLMClient
from my_small_agent.plan import Plan, PlanStep, StepStatus, PlanPhase
from my_small_agent.tools import ToolRegistry
from my_small_agent.tools.base import Tool


class MockSafeTool(Tool):
    name = "safe_tool"
    description = "A safe mock tool"
    parameters = {"type": "object", "properties": {"x": {"type": "string"}}, "required": ["x"]}
    danger_level = "safe"
    category = "read_only"

    async def execute(self, **kwargs) -> str:
        return f"safe result: {kwargs['x']}"


@pytest.fixture
def mock_settings():
    settings = MagicMock(spec=Settings)
    settings.max_iterations = 10
    settings.enable_streaming = True
    settings.enable_thinking = True
    settings.max_context_tokens = 200000
    settings.head_keep = 3
    settings.tail_keep = 20
    settings.compression_threshold = 0.8
    return settings


@pytest.fixture
def registry():
    reg = ToolRegistry()
    reg.register(MockSafeTool())
    return reg


def _make_eval_response(verdict: str):
    """构造 LLM 评估响应 mock。"""
    message = MagicMock()
    message.content = verdict
    choice = MagicMock()
    choice.message = message
    response = MagicMock()
    response.choices = [choice]
    return response


class TestEvaluateStepSuccess:
    """Agent.evaluate_step_success 方法测试。"""

    @pytest.mark.asyncio
    async def test_returns_true_on_success(self, mock_settings, registry):
        """LLM 回答 SUCCESS 时应返回 True。"""
        llm = MagicMock(spec=LLMClient)
        llm.chat = AsyncMock(return_value=_make_eval_response("SUCCESS"))
        agent = Agent(llm, registry, mock_settings)

        step = PlanStep(index=1, title="Test", description="Do something")
        response = AgentResponse(content="Task completed successfully.")

        result = await agent.evaluate_step_success(step, response)
        assert result is True

    @pytest.mark.asyncio
    async def test_returns_false_on_failure(self, mock_settings, registry):
        """LLM 回答 FAILURE 时应返回 False。"""
        llm = MagicMock(spec=LLMClient)
        llm.chat = AsyncMock(return_value=_make_eval_response("FAILURE"))
        agent = Agent(llm, registry, mock_settings)

        step = PlanStep(index=1, title="Test", description="Do something")
        response = AgentResponse(content="Could not complete the task.")

        result = await agent.evaluate_step_success(step, response)
        assert result is False

    @pytest.mark.asyncio
    async def test_eval_uses_step_and_response_content(self, mock_settings, registry):
        """评估调用应包含步骤标题、描述和执行结果。"""
        llm = MagicMock(spec=LLMClient)
        llm.chat = AsyncMock(return_value=_make_eval_response("SUCCESS"))
        agent = Agent(llm, registry, mock_settings)

        step = PlanStep(index=1, title="分析代码", description="读取 auth/ 目录")
        response = AgentResponse(content="已读取所有文件。")

        await agent.evaluate_step_success(step, response)

        # 检查 LLM 调用参数
        call_args = llm.chat.call_args
        messages = call_args.kwargs.get("messages") or call_args.args[0]
        eval_text = messages[0]["content"]
        assert "分析代码" in eval_text
        assert "读取 auth/ 目录" in eval_text
        assert "已读取所有文件。" in eval_text

    @pytest.mark.asyncio
    async def test_eval_no_tools_passed(self, mock_settings, registry):
        """评估调用不应传工具定义。"""
        llm = MagicMock(spec=LLMClient)
        llm.chat = AsyncMock(return_value=_make_eval_response("SUCCESS"))
        agent = Agent(llm, registry, mock_settings)

        step = PlanStep(index=1, title="Test", description="Do something")
        response = AgentResponse(content="Done.")

        await agent.evaluate_step_success(step, response)

        call_kwargs = llm.chat.call_args.kwargs
        assert call_kwargs.get("tools") is None

    @pytest.mark.asyncio
    async def test_eval_thinking_disabled(self, mock_settings, registry):
        """评估调用应禁用 thinking。"""
        llm = MagicMock(spec=LLMClient)
        llm.chat = AsyncMock(return_value=_make_eval_response("SUCCESS"))
        agent = Agent(llm, registry, mock_settings)

        step = PlanStep(index=1, title="Test", description="Do something")
        response = AgentResponse(content="Done.")

        await agent.evaluate_step_success(step, response)

        call_kwargs = llm.chat.call_args.kwargs
        assert call_kwargs.get("thinking_enabled") is False

    @pytest.mark.asyncio
    async def test_eval_truncates_long_response(self, mock_settings, registry):
        """执行结果超过 2000 字符时应截断。"""
        llm = MagicMock(spec=LLMClient)
        llm.chat = AsyncMock(return_value=_make_eval_response("SUCCESS"))
        agent = Agent(llm, registry, mock_settings)

        step = PlanStep(index=1, title="Test", description="Do something")
        long_content = "x" * 3000
        response = AgentResponse(content=long_content)

        await agent.evaluate_step_success(step, response)

        call_args = llm.chat.call_args
        messages = call_args.kwargs.get("messages") or call_args.args[0]
        eval_text = messages[0]["content"]
        assert len(long_content) not in len(eval_text) or eval_text.count("x") <= 2000
```

- [ ] **Step 2: 运行测试验证失败**

Run: `uv run pytest tests/test_plan_mode_lifecycle.py::TestEvaluateStepSuccess -v`
Expected: FAIL — "Agent has no attribute 'evaluate_step_success'"

- [ ] **Step 3: 实现 evaluate_step_success 方法**

在 `my_small_agent/agent.py` 的 `Agent` 类中，在 `compact_context` 方法之前（约第 469 行前）追加：

```python
    async def evaluate_step_success(self, step: Any, response: "AgentResponse") -> bool:
        """
        让 LLM 自评步骤是否成功执行。

        构造简短评估提示，包含步骤描述和 Agent 执行结果，
        让 LLM 判断是否完成了步骤目标。

        参数：
          step:     PlanStep 对象，包含标题和描述
          response: AgentResponse 对象，包含执行结果

        返回：
          True 表示成功，False 表示失败
        """
        eval_prompt = (
            f"请评估以下步骤是否已成功完成：\n\n"
            f"步骤目标：{step.title}\n"
            f"步骤描述：{step.description}\n\n"
            f"执行结果：\n{response.content[:2000]}\n\n"
            f"请只回答 'SUCCESS' 或 'FAILURE'，"
            f"如果有任何未完成的部分则回答 FAILURE。"
        )

        result = await self.llm.chat(
            messages=[{"role": "user", "content": eval_prompt}],
            tools=None,
            thinking_enabled=False,
        )
        verdict = result.choices[0].message.content.strip().upper()
        return "SUCCESS" in verdict
```

- [ ] **Step 4: 运行测试验证通过**

Run: `uv run pytest tests/test_plan_mode_lifecycle.py::TestEvaluateStepSuccess -v`
Expected: 所有 6 个测试 PASS

- [ ] **Step 5: 运行全量测试确保无破坏**

Run: `uv run pytest tests/ -q`
Expected: 所有测试 PASS

- [ ] **Step 6: Commit**

```bash
git add my_small_agent/agent.py tests/test_plan_mode_lifecycle.py
git commit -m "feat: add Agent.evaluate_step_success for LLM self-evaluation"
```

---

### Task 6: CLI Plan 轮次与审阅流程

**Files:**
- Modify: `my_small_agent/cli.py` (新增方法)
- Modify: `tests/test_plan_mode_lifecycle.py` (追加测试)

**Interfaces:**
- Consumes: `parse_plan`, `render_plan_review` from plan.py; `Agent`, `AgentResponse` from agent.py; `questionary`
- Produces: `CLI._run_plan_turn()`, `CLI._run_plan_turn_stream()`, `CLI._run_plan_turn_normal()`, `CLI._review_plan()`

- [ ] **Step 1: 编写审阅流程失败测试**

在 `tests/test_plan_mode_lifecycle.py` 末尾追加：

```python
from unittest.mock import patch
from my_small_agent.cli import CLI
from my_small_agent.session import SessionManager
from my_small_agent.plan import parse_plan


def _make_agent_response(content: str):
    """构造 AgentResponse。"""
    return AgentResponse(content=content)


@pytest.fixture
def cli_instance(mock_settings, registry, tmp_path):
    """构造 CLI 实例（非流式模式）。"""
    llm = MagicMock(spec=LLMClient)
    llm.model = "test-model"
    agent = Agent(llm, registry, mock_settings)
    agent.streaming_enabled = False  # 非流式，简化测试
    session_mgr = SessionManager(tmp_path / "sessions")
    cli = CLI(agent, session_mgr)
    return cli


class TestRunPlanTurn:
    """_run_plan_turn 方法测试。"""

    @pytest.mark.asyncio
    async def test_plan_turn_parses_plan_and_enters_review(self, cli_instance):
        """Plan 模式下 Agent 返回可解析计划时应进入审阅流程。"""
        cli = cli_instance
        cli.agent.plan_mode = True

        plan_text = """## Plan
**Goal**: 测试目标

### Steps
1. **步骤A** -- 做A
2. **步骤B** -- 做B
"""
        # mock Agent.run_turn 返回包含计划的响应
        cli.agent.run_turn = AsyncMock(
            return_value=_make_agent_response(plan_text)
        )
        # mock _review_plan 避免实际执行审阅
        cli._review_plan = AsyncMock()

        await cli._run_plan_turn("测试目标")

        # 验证 _review_plan 被调用，且传入了 Plan 对象
        cli._review_plan.assert_called_once()
        plan_arg = cli._review_plan.call_args.args[0]
        assert plan_arg.goal == "测试目标"
        assert len(plan_arg.steps) == 2

    @pytest.mark.asyncio
    async def test_plan_turn_no_plan_returns_silently(self, cli_instance):
        """Plan 模式下 Agent 返回不可解析的文本时不进入审阅。"""
        cli = cli_instance
        cli.agent.plan_mode = True

        cli.agent.run_turn = AsyncMock(
            return_value=_make_agent_response("这是一段普通回复，不是计划。")
        )
        cli._review_plan = AsyncMock()

        await cli._run_plan_turn("随便聊聊")

        # _review_plan 不应被调用
        cli._review_plan.assert_not_called()


class TestReviewPlan:
    """_review_plan 方法测试。"""

    @pytest.mark.asyncio
    async def test_review_accept_proceeds_to_execute(self, cli_instance):
        """用户选择 Accept 时应进入执行阶段。"""
        cli = cli_instance
        plan = Plan(
            goal="Test",
            steps=[
                PlanStep(index=1, title="Step A", description="Do A"),
                PlanStep(index=2, title="Step B", description="Do B"),
            ],
        )
        # mock questionary.select 返回 "Accept"
        with patch("my_small_agent.cli.questionary") as mock_q:
            mock_q.select.return_value.ask_async = AsyncMock(return_value="Accept")
            cli._execute_plan = AsyncMock()

            await cli._review_plan(plan, "Test")

            cli._execute_plan.assert_called_once_with(plan)
            assert plan.phase == PlanPhase.EXECUTING

    @pytest.mark.asyncio
    async def test_review_cancel_does_not_execute(self, cli_instance):
        """用户选择 Cancel 时不应执行计划。"""
        cli = cli_instance
        plan = Plan(
            goal="Test",
            steps=[
                PlanStep(index=1, title="Step A", description="Do A"),
                PlanStep(index=2, title="Step B", description="Do B"),
            ],
        )
        with patch("my_small_agent.cli.questionary") as mock_q:
            mock_q.select.return_value.ask_async = AsyncMock(return_value="Cancel")
            cli._execute_plan = AsyncMock()

            await cli._review_plan(plan, "Test")

            cli._execute_plan.assert_not_called()

    @pytest.mark.asyncio
    async def test_review_modify_sends_feedback_to_llm(self, cli_instance):
        """用户选择 Modify 时应将反馈发送给 LLM 生成修订版。"""
        cli = cli_instance
        plan = Plan(
            goal="Test",
            steps=[
                PlanStep(index=1, title="Step A", description="Do A"),
                PlanStep(index=2, title="Step B", description="Do B"),
            ],
        )
        revised_text = """## Plan
**Goal**: Test

### Steps
1. **Revised A** -- Do A better
2. **Revised B** -- Do B better
"""
        # mock questionary: 第一次返回 Modify，第二次返回 Accept
        with patch("my_small_agent.cli.questionary") as mock_q:
            mock_q.select.return_value.ask_async = AsyncMock(
                side_effect=["Modify", "Accept"]
            )
            # mock prompt_async 获取用户反馈
            cli.session.prompt_async = AsyncMock(return_value="请修改步骤A")
            # mock Agent 生成修订版
            cli.agent.run_turn = AsyncMock(
                return_value=_make_agent_response(revised_text)
            )
            cli._execute_plan = AsyncMock()

            await cli._review_plan(plan, "Test")

            # 验证执行了修订后的计划
            cli._execute_plan.assert_called_once()
            executed_plan = cli._execute_plan.call_args.args[0]
            assert executed_plan.steps[0].title == "Revised A"

    @pytest.mark.asyncio
    async def test_review_modify_max_3_rounds(self, cli_instance):
        """修改超过 3 轮后第 4 次 Modify 被阻断，最终 Accept。"""
        cli = cli_instance
        plan = Plan(
            goal="Test",
            steps=[
                PlanStep(index=1, title="A", description="d"),
                PlanStep(index=2, title="B", description="d"),
            ],
        )
        revised_text = """## Plan
**Goal**: Test

### Steps
1. **A** -- d
2. **B** -- d
"""
        with patch("my_small_agent.cli.questionary") as mock_q:
            # 3 次 Modify（成功）+ 第 4 次 Modify（被阻断）+ Accept
            mock_q.select.return_value.ask_async = AsyncMock(
                side_effect=["Modify", "Modify", "Modify", "Modify", "Accept"]
            )
            cli.session.prompt_async = AsyncMock(return_value="修改")
            cli.agent.run_turn = AsyncMock(
                return_value=_make_agent_response(revised_text)
            )
            cli._execute_plan = AsyncMock()

            await cli._review_plan(plan, "Test")

            # 验证 prompt_async 只被调用 3 次（第 4 次 Modify 被阻断，不会请求反馈）
            assert cli.session.prompt_async.call_count == 3
            # 验证最终执行了
            cli._execute_plan.assert_called_once()
```

- [ ] **Step 2: 运行测试验证失败**

Run: `uv run pytest tests/test_plan_mode_lifecycle.py::TestRunPlanTurn tests/test_plan_mode_lifecycle.py::TestReviewPlan -v`
Expected: FAIL — "CLI has no attribute '_run_plan_turn'"

- [ ] **Step 3: 实现 CLI Plan 轮次和审阅方法**

在 `my_small_agent/cli.py` 中：

1. 在文件顶部添加 import：

```python
import questionary
from my_small_agent.agent import Agent, AgentResponse
from my_small_agent.plan import (
    Plan, PlanPhase, StepStatus,
    parse_plan, render_plan_review, render_plan_progress, render_plan_summary,
)
```

2. 在 `CLI.__init__` 中添加属性（在 `self._detail_enabled = False` 之后）：

```python
        self._active_plan: Plan | None = None  # 当前活跃计划
```

3. 修改 `_run_agent_turn` 方法（第 85-94 行），在方法开头添加 Plan 模式分支：

```python
    async def _run_agent_turn(self, user_input: str) -> None:
        """根据 streaming 状态选择流式或非流式对话，完成后自动保存会话。"""
        if self.agent.plan_mode:
            await self._run_plan_turn(user_input)
            self._save_session()
            await self._auto_compact_if_needed()
            return

        if self.agent.streaming_enabled:
            await self._run_agent_turn_stream(user_input)
        else:
            await self._run_agent_turn_normal(user_input)
        # 对话完成后自动保存会话
        self._save_session()
        # 检查是否需要自动压缩
        await self._auto_compact_if_needed()
```

4. 在 `_run_agent_turn_normal` 方法之前（第 134 行前）添加 Plan 轮次方法：

```python
    async def _run_plan_turn(self, user_input: str) -> None:
        """
        Plan 模式下的对话轮次：Agent 探索并生成计划，然后进入审阅。

        流程：
          1. 执行 Agent 对话（展示探索过程，捕获完整响应）
          2. 尝试解析计划
          3. 解析成功 → 进入审阅流程
          4. 解析失败 → 按普通回复展示（已由 run_turn 输出）
        """
        # 1. 执行 Agent 对话
        if self.agent.streaming_enabled:
            response = await self._run_plan_turn_stream(user_input)
        else:
            response = await self._run_plan_turn_normal(user_input)

        # 2. 尝试解析计划
        plan = parse_plan(response.content, user_goal=user_input)

        if plan is None:
            return  # 未解析到计划，已按普通回复展示

        # 3. 进入审阅流程
        plan.phase = PlanPhase.REVIEWING
        await self._review_plan(plan, user_input)

    async def _run_plan_turn_normal(self, user_input: str) -> AgentResponse:
        """Plan 模式非流式：执行对话并返回 AgentResponse（供解析）。"""
        with Status("[bold cyan]Thinking...", console=self.console):
            response = await self.agent.run_turn(
                user_input,
                confirm_callback=self._confirm_dangerous_action,
            )

        self.console.print()
        if response.thinking:
            if self._detail_enabled:
                self.console.print(f"[dim]💭 {response.thinking}[/dim]")
                self.console.print()
            else:
                self.console.print("[dim]💭 thinking...[/dim]")
                self.console.print()
        self.console.print(Markdown(response.content))
        self.console.print()
        return response

    async def _run_plan_turn_stream(self, user_input: str) -> AgentResponse:
        """Plan 模式流式：展示流式输出并返回 AgentResponse（供解析）。"""
        self.console.print()
        in_thinking = False
        thinking_buffer = ""
        first_chunk = True
        full_content = ""
        self.console.print("[dim]⚡ 等待响应...[/dim]", end="\r")

        async for event_type, content in self.agent.run_turn_stream(
            user_input, self._confirm_dangerous_action
        ):
            if first_chunk:
                first_chunk = False
                self.console.print(" " * 30, end="\r")

            if event_type == "thinking":
                if self._detail_enabled:
                    if not in_thinking:
                        self.console.print("[dim]💭 ", end="")
                        in_thinking = True
                    self.console.print(f"[dim]{content}[/dim]", end="")
                else:
                    thinking_buffer += content

            elif event_type == "content":
                full_content += content
                if self._detail_enabled and in_thinking:
                    self.console.print()
                    self.console.print()
                    in_thinking = False
                elif not self._detail_enabled and thinking_buffer:
                    self.console.print("[dim]💭 thinking...[/dim]")
                    self.console.print()
                    thinking_buffer = ""
                self.console.print(content, end="")

        if in_thinking:
            self.console.print()
        self.console.print()
        self.console.print()

        return AgentResponse(content=full_content)

    async def _review_plan(self, plan: Plan, user_input: str) -> None:
        """
        审阅计划：展示面板，用户选择 Accept / Modify / Cancel。

        Modify 流程：用户输入反馈 → LLM 修订 → 重新审阅（最多 3 轮）。
        """
        modify_rounds = 0
        max_modify_rounds = 3

        while True:
            # 展示计划审阅面板
            render_plan_review(plan, self.console)
            self.console.print()

            # 用户选择
            choice = await questionary.select(
                "请选择操作：",
                choices=["Accept", "Modify", "Cancel"],
            ).ask_async()

            if choice == "Accept":
                plan.phase = PlanPhase.EXECUTING
                await self._execute_plan(plan)
                return

            elif choice == "Modify":
                if modify_rounds >= max_modify_rounds:
                    self.console.print(
                        f"[yellow]已达到最大修改次数（{max_modify_rounds} 轮），"
                        f"请选择 Accept 或 Cancel。[/yellow]"
                    )
                    continue

                modify_rounds += 1
                # 获取用户反馈
                with patch_stdout():
                    feedback = await self.session.prompt_async(
                        HTML('<ansiyellow>请输入修改意见: </ansiyellow>')
                    )

                if not feedback.strip():
                    continue

                # 构造修订请求：原始计划 + 用户反馈
                revise_prompt = (
                    f"以下是之前的计划，用户提出了修改意见，请生成修订版计划。\n\n"
                    f"原始计划：\n{plan.raw_plan_text}\n\n"
                    f"用户修改意见：{feedback}\n\n"
                    f"请按照相同格式输出修订后的计划。"
                )

                # 发送给 LLM 生成修订版
                with Status("[bold cyan]修订计划中...", console=self.console):
                    response = await self.agent.run_turn(
                        revise_prompt,
                        confirm_callback=self._confirm_dangerous_action,
                    )

                self.console.print()
                self.console.print(Markdown(response.content))
                self.console.print()

                # 重新解析
                new_plan = parse_plan(response.content, user_goal=user_input)
                if new_plan is not None:
                    plan = new_plan
                else:
                    self.console.print(
                        "[yellow]未能解析修订后的计划，请重新选择。[/yellow]"
                    )

            elif choice == "Cancel":
                self.console.print("[dim]计划已取消。[/dim]")
                return
```

- [ ] **Step 4: 运行测试验证通过**

Run: `uv run pytest tests/test_plan_mode_lifecycle.py -v`
Expected: 所有测试 PASS

- [ ] **Step 5: 运行全量测试确保无破坏**

Run: `uv run pytest tests/ -q`
Expected: 所有测试 PASS

- [ ] **Step 6: Commit**

```bash
git add my_small_agent/cli.py tests/test_plan_mode_lifecycle.py
git commit -m "feat: add CLI plan turn and review flow with questionary"
```

---

### Task 7: CLI 执行流程与摘要

**Files:**
- Modify: `my_small_agent/cli.py` (新增 _execute_plan 方法)
- Modify: `tests/test_plan_mode_lifecycle.py` (追加执行测试)

**Interfaces:**
- Consumes: `Agent.run_turn`, `Agent.evaluate_step_success`, `render_plan_progress`, `render_plan_summary`, `questionary`
- Produces: `CLI._execute_plan(plan: Plan)`

- [ ] **Step 1: 编写执行流程失败测试**

在 `tests/test_plan_mode_lifecycle.py` 末尾追加：

```python
class TestExecutePlan:
    """_execute_plan 方法测试。"""

    @pytest.mark.asyncio
    async def test_execute_all_steps_success(self, cli_instance):
        """所有步骤成功执行时状态应为 DONE。"""
        cli = cli_instance
        plan = Plan(
            goal="Test",
            steps=[
                PlanStep(index=1, title="Step A", description="Do A"),
                PlanStep(index=2, title="Step B", description="Do B"),
            ],
            phase=PlanPhase.EXECUTING,
        )

        # mock Agent.run_turn 返回成功响应
        cli.agent.run_turn = AsyncMock(
            return_value=_make_agent_response("步骤执行完成。")
        )
        # mock evaluate_step_success 返回 True
        cli.agent.evaluate_step_success = AsyncMock(return_value=True)
        # mock Agent.toggle_plan_mode
        cli.agent.toggle_plan_mode = MagicMock(return_value="plan_off")
        cli.agent.plan_mode = True

        await cli._execute_plan(plan)

        assert plan.phase == PlanPhase.COMPLETED
        assert plan.steps[0].status == StepStatus.DONE
        assert plan.steps[1].status == StepStatus.DONE

    @pytest.mark.asyncio
    async def test_execute_step_failure_continue(self, cli_instance):
        """步骤失败且用户选择 Continue 时应跳过继续。"""
        cli = cli_instance
        plan = Plan(
            goal="Test",
            steps=[
                PlanStep(index=1, title="Step A", description="Do A"),
                PlanStep(index=2, title="Step B", description="Do B"),
                PlanStep(index=3, title="Step C", description="Do C"),
            ],
            phase=PlanPhase.EXECUTING,
        )

        # 第一步失败，后续成功
        cli.agent.run_turn = AsyncMock(
            return_value=_make_agent_response("执行结果。")
        )
        cli.agent.evaluate_step_success = AsyncMock(
            side_effect=[False, True, True]
        )
        cli.agent.toggle_plan_mode = MagicMock(return_value="plan_off")
        cli.agent.plan_mode = True

        # mock questionary 选择 Continue
        with patch("my_small_agent.cli.questionary") as mock_q:
            mock_q.select.return_value.ask_async = AsyncMock(return_value="Continue")

            await cli._execute_plan(plan)

        assert plan.steps[0].status == StepStatus.FAILED
        assert plan.steps[1].status == StepStatus.DONE
        assert plan.steps[2].status == StepStatus.DONE
        assert plan.phase == PlanPhase.COMPLETED

    @pytest.mark.asyncio
    async def test_execute_step_failure_stop(self, cli_instance):
        """步骤失败且用户选择 Stop 时剩余步骤标记 SKIPPED。"""
        cli = cli_instance
        plan = Plan(
            goal="Test",
            steps=[
                PlanStep(index=1, title="Step A", description="Do A"),
                PlanStep(index=2, title="Step B", description="Do B"),
                PlanStep(index=3, title="Step C", description="Do C"),
            ],
            phase=PlanPhase.EXECUTING,
        )

        cli.agent.run_turn = AsyncMock(
            return_value=_make_agent_response("执行结果。")
        )
        # 第一步失败
        cli.agent.evaluate_step_success = AsyncMock(return_value=False)
        cli.agent.toggle_plan_mode = MagicMock(return_value="plan_off")
        cli.agent.plan_mode = True

        with patch("my_small_agent.cli.questionary") as mock_q:
            mock_q.select.return_value.ask_async = AsyncMock(return_value="Stop")

            await cli._execute_plan(plan)

        assert plan.steps[0].status == StepStatus.FAILED
        assert plan.steps[1].status == StepStatus.SKIPPED
        assert plan.steps[2].status == StepStatus.SKIPPED
        assert plan.phase == PlanPhase.COMPLETED

    @pytest.mark.asyncio
    async def test_execute_exits_plan_mode_first(self, cli_instance):
        """执行计划前应先退出 Plan 模式。"""
        cli = cli_instance
        plan = Plan(
            goal="Test",
            steps=[
                PlanStep(index=1, title="A", description="d"),
                PlanStep(index=2, title="B", description="d"),
            ],
            phase=PlanPhase.EXECUTING,
        )

        cli.agent.run_turn = AsyncMock(
            return_value=_make_agent_response("Done.")
        )
        cli.agent.evaluate_step_success = AsyncMock(return_value=True)
        cli.agent.toggle_plan_mode = MagicMock(return_value="plan_off")
        cli.agent.plan_mode = True

        await cli._execute_plan(plan)

        # 验证 toggle_plan_mode 被调用（退出 Plan 模式）
        cli.agent.toggle_plan_mode.assert_called_once()
        assert cli.agent.plan_mode is False

    @pytest.mark.asyncio
    async def test_execute_step_prompt_contains_title_and_description(self, cli_instance):
        """步骤提示词应包含步骤标题和描述。"""
        cli = cli_instance
        plan = Plan(
            goal="Test",
            steps=[
                PlanStep(index=1, title="分析代码", description="读取 auth/ 目录"),
                PlanStep(index=2, title="修改代码", description="创建 handler.py"),
            ],
            phase=PlanPhase.EXECUTING,
        )

        cli.agent.run_turn = AsyncMock(
            return_value=_make_agent_response("Done.")
        )
        cli.agent.evaluate_step_success = AsyncMock(return_value=True)
        cli.agent.toggle_plan_mode = MagicMock(return_value="plan_off")
        cli.agent.plan_mode = True

        await cli._execute_plan(plan)

        # 验证第一次 run_turn 调用的 user_input 包含标题和描述
        first_call_args = cli.agent.run_turn.call_args_list[0]
        user_input = first_call_args.args[0] if first_call_args.args else first_call_args.kwargs.get("user_input", "")
        assert "分析代码" in user_input
        assert "读取 auth/ 目录" in user_input
```

- [ ] **Step 2: 运行测试验证失败**

Run: `uv run pytest tests/test_plan_mode_lifecycle.py::TestExecutePlan -v`
Expected: FAIL — "CLI has no attribute '_execute_plan'"

- [ ] **Step 3: 实现 _execute_plan 方法**

在 `my_small_agent/cli.py` 中，在 `_review_plan` 方法之后添加：

```python
    async def _execute_plan(self, plan: Plan) -> None:
        """
        执行计划：逐步执行每个步骤，实时展示进度。

        流程：
          1. 退出 Plan 模式（恢复全部工具）
          2. 逐步执行：
             - 构造步骤提示词
             - agent.run_turn() 实时展示执行过程
             - evaluate_step_success() LLM 自评
             - 更新步骤状态
             - 失败时用户选择 Continue / Stop
          3. 展示完成摘要
        """
        self._active_plan = plan

        # 1. 退出 Plan 模式
        if self.agent.plan_mode:
            self.agent.toggle_plan_mode()

        # 2. 逐步执行
        for i, step in enumerate(plan.steps):
            # 跳过已被标记为 SKIPPED 的步骤（前面 Stop 导致的）
            if step.status == StepStatus.SKIPPED:
                continue

            step.status = StepStatus.IN_PROGRESS
            render_plan_progress(plan, self.console)

            # 构造步骤提示词
            step_prompt = (
                f"执行计划步骤 {step.index}: {step.title}\n"
                f"{step.description}"
            )

            self.console.print(f"\n[cyan]▶ 执行步骤 {step.index}: {step.title}[/cyan]\n")

            # 执行步骤
            try:
                response = await self.agent.run_turn(
                    step_prompt,
                    confirm_callback=self._confirm_dangerous_action,
                )
            except Exception as e:
                response = AgentResponse(content=f"执行出错：{e}")

            # LLM 自评
            try:
                success = await self.agent.evaluate_step_success(step, response)
            except Exception:
                success = False  # 评估失败视为步骤失败

            step.status = StepStatus.DONE if success else StepStatus.FAILED
            render_plan_progress(plan, self.console)

            # 保存会话
            self._save_session()

            # 失败时询问用户
            if not success and i < len(plan.steps) - 1:
                choice = await questionary.select(
                    f"步骤 {step.index} 失败，如何继续？",
                    choices=["Continue（跳过继续）", "Stop（跳过所有剩余步骤）"],
                ).ask_async()

                if choice.startswith("Stop"):
                    # 标记剩余步骤为 SKIPPED
                    for remaining in plan.steps[i + 1:]:
                        remaining.status = StepStatus.SKIPPED
                    break

        # 3. 展示完成摘要
        plan.phase = PlanPhase.COMPLETED
        self.console.print()
        render_plan_summary(plan, self.console)
        self.console.print()
        self._active_plan = None
```

- [ ] **Step 4: 运行测试验证通过**

Run: `uv run pytest tests/test_plan_mode_lifecycle.py -v`
Expected: 所有测试 PASS

- [ ] **Step 5: 运行全量测试确保无破坏**

Run: `uv run pytest tests/ -q`
Expected: 所有测试 PASS

- [ ] **Step 6: Commit**

```bash
git add my_small_agent/cli.py tests/test_plan_mode_lifecycle.py
git commit -m "feat: add CLI plan execution with progress tracking and summary"
```

---

### Task 8: 更新 CLI 帮助文本与最终验证

**Files:**
- Modify: `my_small_agent/cli.py` (更新 _print_welcome, _print_help)

**Interfaces:**
- 无新增接口，仅更新展示文本

- [ ] **Step 1: 更新欢迎面板和帮助信息**

在 `my_small_agent/cli.py` 的 `_print_welcome` 方法中，更新 `/plan` 命令描述：

将：
```
"  /plan   - Toggle plan mode (read-only exploration)\n"
```
改为：
```
"  /plan   - Toggle plan mode (explore + plan + review + execute)\n"
```

在 `_print_help` 方法中，同样更新：
将：
```
"  [cyan]/plan[/cyan]   - Toggle plan mode (read-only exploration)\n"
```
改为：
```
"  [cyan]/plan[/cyan]   - Toggle plan mode (explore + plan + review + execute)\n"
```

- [ ] **Step 2: 运行全量测试**

Run: `uv run pytest tests/ -q`
Expected: 所有测试 PASS

- [ ] **Step 3: 运行 lint 检查**

Run: `uv run python -c "from my_small_agent.cli import CLI; from my_small_agent.plan import parse_plan, render_plan_review, render_plan_progress, render_plan_summary; print('All imports OK')"`
Expected: 打印 "All imports OK"

- [ ] **Step 4: Commit**

```bash
git add my_small_agent/cli.py
git commit -m "docs: update CLI help text for plan mode lifecycle"
```
