"""Plan 解析器测试 - 数据结构和 LLM 输出解析。"""

import re
from io import StringIO
from rich.console import Console

from my_small_agent.plan import (
    PlanPhase, StepStatus, PlanStep, Plan, parse_plan,
    render_plan_review, render_plan_progress, render_plan_summary,
)


def _capture_render(render_fn, plan) -> str:
    """用 Rich Console 捕获渲染输出为字符串。"""
    console = Console(file=StringIO(), width=80, force_terminal=False)
    render_fn(plan, console)
    return console.file.getvalue()


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

    def test_review_panel_title(self):
        """审阅面板应包含 Plan Mode 标题。"""
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
