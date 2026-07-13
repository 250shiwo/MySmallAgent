# Plan Mode 生命周期设计

## 概述

为现有基础 Plan 模式（工具过滤 + 提示词注入）新增完整的计划生命周期：结构化数据、LLM 输出解析、交互式审阅（Accept/Modify/Cancel）、逐步执行与进度跟踪、完成摘要统计。

### 现有基础

- `Agent.plan_mode` 开关 + `toggle_plan_mode()` 方法
- `PromptManager.get_plan_prompt()` 返回提示词，通过追加 system 消息注入
- 工具过滤（`readonly_only`）+ 执行层拒绝写工具
- CLI `/plan` 命令切换提示符样式（You> 绿 / Plan> 品红）
- `test_plan_mode.py` 覆盖 12 个测试场景

### 新增能力

1. Plan 数据结构（PlanPhase / StepStatus / PlanStep / Plan）
2. 计划解析器（`parse_plan()`）
3. 增强的 Plan 提示词（两阶段流程指令 + 固定输出格式）
4. 交互式审阅（questionary 方向键选择 Accept/Modify/Cancel）
5. 执行进度实时显示（Rich Panel + 状态图标）
6. LLM 自评步骤成功/失败
7. 完成摘要统计

## 设计决策

| 决策点 | 选择 | 理由 |
|--------|------|------|
| 提示词注入方式 | 保持当前（独立 system 消息） | 缓存友好，改动最小，已有测试可复用 |
| 审阅 UI | questionary 方向键导航 | 用户体验好 |
| 进度动画 | 简化 Rich 样式（黄色 In Progress） | 避免完整 Shimmer 的复杂度 |
| 执行输出 | 实时展示流式输出 | 用户能看到每步执行过程 |
| 失败判断 | LLM 自评 | 比异常捕获更准确 |
| 上下文管理 | 保留全部探索历史 | 上下文完整，不过度清理 |

## 模块结构

### 新增文件

```
my_small_agent/
├── plan.py              # Plan 数据结构 + 解析器 + 渲染函数
```

LLM 自评逻辑作为 `Agent.evaluate_step_success()` 方法实现，不单独建文件。

### 修改文件

```
my_small_agent/
├── prompt.py            # 增强 _PLAN_PROMPT 为两阶段流程指令
├── agent.py             # 新增 evaluate_step_success() 方法
├── cli.py               # 新增 Plan 生命周期编排（审阅、执行、摘要）
```

### 新增依赖

```
questionary  # 方向键导航选择菜单
```

## 数据结构

### `plan.py`

```python
from dataclasses import dataclass
from enum import Enum, auto
from typing import Optional

class PlanPhase(Enum):
    PLANNING    = auto()  # Agent 使用只读工具探索并生成计划
    REVIEWING   = auto()  # 用户审阅计划，可接受/修改/取消
    EXECUTING   = auto()  # 计划被接受，逐步执行中
    COMPLETED   = auto()  # 所有步骤完成（成功或失败）

class StepStatus(Enum):
    PENDING     = "pending"
    IN_PROGRESS = "in_progress"
    DONE        = "done"
    FAILED      = "failed"
    SKIPPED     = "skipped"

@dataclass
class PlanStep:
    index: int              # 1-based 步骤编号
    title: str              # 简短标题（一行）
    description: str        # 详细描述
    status: StepStatus = StepStatus.PENDING

@dataclass
class Plan:
    goal: str                               # 用户原始目标
    steps: list[PlanStep]                   # 步骤列表
    phase: PlanPhase = PlanPhase.PLANNING   # 当前阶段
    raw_plan_text: str = ""                 # LLM 原始输出
```

`Plan` 是可变对象——执行过程中直接更新 `step.status` 和 `plan.phase`。

## 计划解析器

### `parse_plan(llm_output: str, user_goal: str = "") -> Optional[Plan]`

#### 解析流程

1. **查找 `## Plan` 区块**：正则匹配 `## Plan` 或 `## Execution Plan` 标题，提取到下一个 `##` 标题或文末
2. **提取 Goal**：在区块内搜索 `**Goal**: <内容>` 模式
3. **提取 Steps**：匹配编号行，支持多种格式变体
4. **宽松回退**：如果未找到正式 `## Plan` 区块，在全文中搜索至少 2 个编号步骤

#### 步骤解析正则

```python
STEP_RE = re.compile(
    r"(?:^|\n)\s*(?:\d+[\.\)])\s+"      # 编号: 1. 或 1)
    r"(?:\*\*(.+?)\*\*|(.+?))"           # 标题: **bold** 或纯文本
    r"\s*(?:--|-|:|—|–)\s*"              # 分隔符: -- - : — –
    r"(.+?)(?=\n\s*\d+[\.\)]|\Z)",       # 描述: 到下一个编号或文末
    re.DOTALL
)
```

#### 宽松解析回退

```python
def _try_parse_loose(text: str, user_goal: str) -> Optional[Plan]:
    """全文搜索编号步骤，至少 2 个才算计划。"""
    matches = STEP_RE.findall(text)
    if len(matches) < 2:
        return None
    # 构建 Plan...
```

#### 边界情况

- LLM 输出不含计划格式 → 返回 `None`，CLI 回退为普通文本展示
- 步骤少于 2 个 → 返回 `None`
- Goal 未找到 → 使用 `user_goal` 参数回退

## 增强的 Plan 提示词

### 改动位置

修改 `prompt.py` 中的 `_PLAN_PROMPT` 内联字符串。保持注入方式不变（独立 system 消息追加/移除）。

### 新的 Plan Prompt 内容

```
[PLAN_MODE_ACTIVE]

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
```

### 关键变化

- 旧 prompt 只说"输出结构化计划"，没有固定格式
- 新 prompt 指定了 `## Plan` + `### Steps` + `**标题** -- 描述` 的精确格式
- 这确保 `parse_plan()` 能可靠解析

## 交互式审阅

### 审阅面板渲染

`render_plan_review(plan: Plan, console: Console)` 用 Rich Panel（品红色边框）展示计划：

```
┌─────────── Plan Mode ───────────┐
│ Goal: 重构认证模块               │
│                                  │
│ Proposed Steps:                  │
│   1. 分析现有认证代码结构        │
│      读取 auth/ 目录下的所有文件 │
│   2. 提取认证逻辑为独立模块      │
│      创建 auth/handler.py        │
│   ...                            │
└──────────────────────────────────┘
```

### 用户选择

用 `questionary.select` 实现方向键选择：
- **Accept** → 进入执行阶段
- **Modify** → 用户输入反馈 → LLM 修订 → 重新审阅
- **Cancel** → 取消计划

### 修改流程

1. 用 `prompt_toolkit` 获取用户反馈文本
2. 构造消息：原始计划 + 用户反馈 → 发送给 LLM 生成修订版
3. 重新 `parse_plan()` → 重新展示审阅面板
4. 最多 3 轮修改，超出后提示用户必须 Accept 或 Cancel

## 执行阶段

### 执行流程

用户 Accept 后：

1. **退出 Plan 模式**：`agent.toggle_plan_mode()` 恢复全部工具
2. **逐步执行**：

```python
for step in plan.steps:
    step.status = StepStatus.IN_PROGRESS
    self._render_progress(plan)
    
    # 构造步骤提示词
    step_prompt = f"执行计划步骤 {step.index}: {step.title}\n{step.description}"
    
    # 实时展示流式输出
    response = await self._run_step(step_prompt)
    
    # LLM 自评
    success = await self.agent.evaluate_step_success(step, response)
    
    step.status = StepStatus.DONE if success else StepStatus.FAILED
    
    if not success:
        choice = await self._ask_continue_or_stop()
        if choice == "stop":
            for s in plan.steps[step.index:]:
                s.status = StepStatus.SKIPPED
            break
    
    self._save_session()  # 每步执行后保存
```

3. **展示完成摘要**

### 进度面板

使用 Rich Panel 展示所有步骤的当前状态：

```
○  Step 1: Analyze project structure       Pending
●  Step 2: Review existing code            In Progress...
✓  Step 3: Implement changes               Done
```

状态图标：
- `○` Pending（dim 暗色）
- `●` In Progress（yellow 黄色）
- `✓` Done（green 绿色）
- `✗` Failed（red 红色）
- `—` Skipped（dim 暗色）

### 步骤失败处理

用户选择：
- **Continue** → 跳过当前步骤，继续下一步
- **Stop** → 跳过所有剩余步骤（标记为 SKIPPED）

## Agent 变更

### `evaluate_step_success()` 方法

```python
async def evaluate_step_success(self, step: PlanStep, response: AgentResponse) -> bool:
    """
    让 LLM 自评步骤是否成功执行。
    
    构造简短评估提示，包含步骤描述和 Agent 执行结果，
    让 LLM 判断是否完成了步骤目标。
    """
    eval_prompt = (
        f"请评估以下步骤是否已成功完成：\n\n"
        f"步骤目标：{step.title}\n"
        f"步骤描述：{step.description}\n\n"
        f"执行结果：\n{response.content[:2000]}\n\n"
        f"请只回答 'SUCCESS' 或 'FAILURE'，如果有任何未完成的部分则回答 FAILURE。"
    )
    
    result = await self.llm.chat(
        messages=[{"role": "user", "content": eval_prompt}],
        tools=None,
        thinking_enabled=False,
    )
    verdict = result.choices[0].message.content.strip().upper()
    return "SUCCESS" in verdict
```

### 设计要点

- 使用独立的 LLM 调用（不携带对话历史），避免上下文干扰
- 截断执行结果到 2000 字符，控制 token 开销
- 简单的 SUCCESS/FAILURE 判断，避免复杂解析

## CLI 编排

### 新增 CLI 属性

```python
class CLI:
    def __init__(self, ...):
        ...
        self._active_plan: Optional[Plan] = None  # 当前活跃计划
```

### `_run_agent_turn` 改动

```python
async def _run_agent_turn(self, user_input: str) -> None:
    if self.agent.plan_mode:
        await self._run_plan_turn(user_input)
    else:
        # 现有逻辑
        if self.agent.streaming_enabled:
            await self._run_agent_turn_stream(user_input)
        else:
            await self._run_agent_turn_normal(user_input)
    self._save_session()
    await self._auto_compact_if_needed()
```

### `_run_plan_turn` 方法

Plan 模式下的对话轮次需要捕获 Agent 的完整响应文本用于解析。现有 `_run_agent_turn_stream` / `_run_agent_turn_normal` 方法直接打印输出不返回内容，因此需要新增能返回 `AgentResponse` 的变体：

```python
async def _run_plan_turn(self, user_input: str) -> None:
    """Plan 模式下的对话轮次：Agent 探索并生成计划，然后进入审阅。"""
    # 1. 执行 Agent 对话（流式展示探索过程，同时捕获完整响应）
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
```

`_run_plan_turn_stream` 和 `_run_plan_turn_normal` 是现有流式/非流式方法的变体，区别在于：
- 仍然实时展示输出（thinking + content）
- 额外累积完整文本，返回 `AgentResponse` 供 `parse_plan()` 使用
- 实现方式：复用现有方法的展示逻辑，在内部累积 `full_content` 和 `full_thinking`，结束时构造 `AgentResponse` 返回

### `_review_plan` 方法

处理 Accept/Modify/Cancel 循环：
- Accept → 调用 `_execute_plan(plan)`
- Modify → 获取反馈 → LLM 修订 → 重新 parse → 重新 review（最多 3 轮）
- Cancel → 打印取消信息，返回

### `_execute_plan` 方法

执行阶段编排（见上文执行流程）。

### 关键设计

- Plan 执行不经过 `_run_agent_turn`：`_execute_plan` 直接调用 `agent.run_turn_stream`
- Plan 状态存储在 CLI：`self._active_plan`
- 每步执行后自动保存会话

## 完成摘要

`render_plan_summary(plan: Plan, console: Console)`：

```
┌────────── Plan Complete ──────────┐
│ 3 completed, 0 failed (of 3 total)│
└───────────────────────────────────┘
```

- 边框颜色：无失败为绿色，有失败为黄色
- 统计：completed / failed / skipped / total

## 完整生命周期

```
用户: /plan
  → Agent 进入 Plan Mode（现有逻辑）
  → PromptManager 注入增强版 plan prompt
  → 工具过滤：仅只读工具 + 执行层拒绝写工具

用户: "重构认证模块"
  → Agent 用只读工具探索代码库
  → LLM 生成结构化计划（## Plan + ### Steps 格式）
  → parse_plan() 解析为 Plan 对象
  → render_plan_review() 展示品红色计划面板
  → questionary 方向键选择:
     ├─ Accept → 进入执行阶段
     ├─ Modify → 用户输入反馈 → LLM 修订 → 重新审阅（最多 3 轮）
     └─ Cancel → 取消计划

Accept 后:
  → 切换到 Normal 模式（所有工具可用）
  → 逐步执行:
     → 构造 step_prompt
     → agent.run_turn_stream() 实时展示
     → evaluate_step_success() LLM 自评
     → 更新步骤状态 + 渲染进度面板
     → 失败时用户选择 Continue / Stop
  → render_plan_summary() 展示统计
  → plan.phase = COMPLETED
```

## 测试策略

### 新增 `tests/test_plan_parser.py`

纯函数测试，无需 mock：

| 测试类别 | 场景 |
|---------|------|
| 标准格式 | `## Plan` + `### Steps` + `**标题** -- 描述` |
| 格式变体 | `## Execution Plan`、`1)` 编号、`—` em dash、纯文本标题 |
| Goal 提取 | 有 Goal / 无 Goal 回退到 user_goal |
| 宽松回退 | 无 `## Plan` 区块但有编号步骤 |
| 边界情况 | <2 步骤返回 None / 无编号返回 None / 空字符串 |

### 新增 `tests/test_plan_mode_lifecycle.py`

Mock LLM 的 `chat` 方法：

| 测试类别 | 场景 |
|---------|------|
| 审阅流程 | Accept → 进入执行 / Cancel → 取消 / Modify → 修订 |
| 修改限制 | 3 轮修改上限 |
| 执行流程 | 步骤状态转换 PENDING → IN_PROGRESS → DONE |
| 失败处理 | LLM 自评返回 FAILURE → 用户选择 Continue/Stop |
| 跳过逻辑 | Stop → 剩余步骤标记 SKIPPED |
| 摘要统计 | completed/failed/skipped 计数正确 |

### 更新 `tests/test_plan_mode.py`

- 更新 `test_get_plan_prompt_contains_instructions`：断言新关键词
- 新增 `test_plan_prompt_contains_format_specification`：验证格式指令

### 测试要点

- 解析器测试完全基于字符串输入/输出，无 LLM mock
- 生命周期测试 mock LLM 的 `chat` 方法，模拟不同评估结果
- CLI 交互测试 mock `questionary.select` 返回值
- 不新增集成测试（避免真实 LLM 调用）
