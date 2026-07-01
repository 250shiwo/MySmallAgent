# 技能系统（Skill System）设计规格

> 版本: v0.4 | 日期: 2026-07-01 | 状态: 待实施

## 概述

为 MySmallAgent 引入技能系统，让 Agent 具备"角色切换"能力——不同任务激活不同专业技能，每个技能自带专属指令和领域知识。

**四大能力：**
1. Skill 自动发现与注册
2. PromptManager 动态提示词管理
3. LLM 自主激活技能 + CLI 手动激活
4. 组合工具（research_topic）

---

## 文件结构

```
my_small_agent/
├── skills/
│   ├── __init__.py              # discover_skills() + build_skills_index() + skill_registry 单例
│   ├── registry.py              # SkillInfo 数据类 + SkillRegistry 类 + SKILL.md 解析
│   ├── research/
│   │   └── SKILL.md             # 搜索研究专家技能
│   └── code_assistant/
│       └── SKILL.md             # 代码助手技能
├── tools/
│   └── research_topic.py        # 组合工具（新增）
├── prompt.py                    # PromptManager 类（新增）
├── system_prompt.md             # 基础 system prompt（从 agent.py 提取）
└── ...（现有文件修改）
```

**修改的现有文件：**
- `agent.py` — 集成 PromptManager、注册 skill 回调、activate_skill/deactivate_skill 方法
- `cli.py` — 新增 /skills、/skill、/unskill 命令，/status 增加 Active Skill
- `__main__.py` — 启动时调用 skill 发现流程、初始化 PromptManager
- `tools/__init__.py` — ToolRegistry 新增 dispatch() 方法、注册组合工具

---

## 一、Skill 自动发现与注册

### SKILL.md 标准格式

每个 Skill 是 `my_small_agent/skills/` 目录下的一个子文件夹，包含一个 `SKILL.md` 文件。采用 YAML frontmatter 格式：

```markdown
---
name: research
description: "搜索研究专家，擅长网络搜索、信息提取和综合分析。"
user_invocable: true
---

You are now operating in Research Mode...
（详细指令内容）
```

**frontmatter 字段：**
- `name`（必需）：技能标识符
- `description`（必需）：技能描述，写入 system prompt 供 LLM 判断是否激活
- `user_invocable`（可选，默认 true）：用户是否可通过 /skill 手动激活

**frontmatter 之后的内容**是技能的详细指令（Markdown 格式），在技能激活时作为 tool result 返回给 LLM。

### SkillInfo 数据类

```python
# my_small_agent/skills/registry.py
@dataclass
class SkillInfo:
    name: str                      # 技能标识符
    description: str               # 技能描述
    prompt_text: str               # SKILL.md 中 frontmatter 之后的完整内容
    user_invocable: bool = True    # 用户是否可直接调用
    skill_dir: Path | None = None  # 技能目录路径
```

### SkillRegistry 注册表

遵循项目已有的 ToolRegistry 对称模式：

```python
class SkillRegistry:
    _skills: dict[str, SkillInfo]
    _active_skill: str | None
    _on_activate: Callable | None

    def register(self, skill_info: SkillInfo) -> None
    def activate(self, name: str) -> str         # 返回 JSON（含 prompt_text）
    def deactivate(self) -> str                  # 返回确认消息
    def get_active(self) -> SkillInfo | None     # 获取当前激活的 skill
    def get_all_names(self) -> list[str]         # 所有已注册 skill 名称
    def get_skill(self, name: str) -> SkillInfo | None  # 按名称查询
    def set_on_activate(self, callback: Callable) -> None  # 注册状态变更回调
```

全局单例 `skill_registry`。

### discover_skills 发现流程

```python
def discover_skills(skills_dir: Path | None = None) -> list[str]:
    skills_path = skills_dir or Path(__file__).resolve().parent
    for item in sorted(skills_path.iterdir()):
        if not item.is_dir():
            continue
        if item.name.startswith(("_", ".")):
            continue
        skill_md = item / "SKILL.md"
        if not skill_md.exists():
            continue
        info = _parse_skill_md(skill_md)  # 解析 frontmatter + 内容
        skill_registry.register(info)
```

**frontmatter 解析：** 使用正则 `^---\s*\n(.*?)\n---\s*\n` 提取 YAML 区块，逐行解析 `key: value` 对。支持引号包裹和布尔值，无需 `pyyaml` 依赖。

### build_skills_index 索引构建

```python
def build_skills_index() -> str:
    # 输出格式：
    # ## Available Skills
    # When a task matches a skill below, call activate_skill(name)...
    #
    # - research: 搜索研究专家...
    # - code_assistant: 代码助手专家...
```

在启动时调用一次，拼接到 system prompt 末尾。

---

## 二、PromptManager

### 职责

从文件加载基础系统提示词，拼接 skills index，提供统一的 `get_system_prompt()` 接口。

### 接口设计

```python
# my_small_agent/prompt.py
class PromptManager:
    def __init__(self, base_prompt_path: Path | None = None):
        # 默认从 my_small_agent/system_prompt.md 加载
        self._base_prompt = self._load_base_prompt(base_prompt_path)
        self._skills_index = ""

    def update_skills_index(self, skills_index: str) -> None:
        """启动时调用一次，设置 skills 列表文本。"""
        self._skills_index = skills_index

    def get_system_prompt(self) -> str:
        """返回完整 system prompt = base + skills index。"""
        if self._skills_index:
            return self._base_prompt + "\n\n" + self._skills_index
        return self._base_prompt
```

### system_prompt.md

从 `agent.py` 中的 `SYSTEM_PROMPT` 变量原封不动提取到 `my_small_agent/system_prompt.md`。

### 缓存友好设计

**关键原则：system prompt 前缀在整个会话中保持不变。**

```
system prompt（稳定前缀，不随 skill 切换而变化）:
┌─────────────────────────────┐
│ base prompt                 │ ← system_prompt.md
│ + skills index（名称+描述） │ ← 启动时加载
├─────────────────────────────┤ ← 缓存边界
│ memory system message       │ ← 已有（长期记忆）
│ + conversation history      │ ← 动态增长
│ + skill tool results        │ ← 技能指令通过这里进入
└─────────────────────────────┘
```

1. **启动时**：base prompt + skills index 拼接完成 → 前缀固定
2. **激活技能时**：技能详细指令作为 activate_skill 的 tool result 返回，进入对话历史
3. **system prompt 不变** → 提示词前缀缓存始终命中

---

## 三、LLM 自主激活技能

### activate_skill 工具

```python
name = "activate_skill"
description = "Activate a skill by name. Returns the skill's detailed instructions."
parameters = {
    "type": "object",
    "properties": {
        "skill_name": {"type": "string", "description": "技能名称"}
    },
    "required": ["skill_name"]
}
danger_level = "safe"
```

**handler 逻辑：**
1. 从 skill_registry 查找技能
2. 调用 skill_registry.activate(name) 设置激活状态
3. 返回技能的完整 prompt_text 作为字符串（成为 tool result）
4. 如果技能不存在 → 返回错误提示

### deactivate_skill 工具

```python
name = "deactivate_skill"
description = "Deactivate the currently active skill and return to base mode."
parameters = {"type": "object", "properties": {}, "required": []}
danger_level = "safe"
```

**handler 逻辑：** 调用 skill_registry.deactivate() → 返回确认消息

### 激活流程

```
用户: "帮我搜索 Python 最新版本"
→ system prompt 不变（包含 skills index）
→ LLM 看到 "research: 搜索研究专家..."
→ LLM 调用 activate_skill("research")
→ handler 返回 research/SKILL.md 完整内容作为 tool result
→ tool result 进入对话历史（system prompt 不变，缓存不破）
→ LLM 按照收到的 skill 指令调用 web_search 等工具
→ 最终回复用户
```

### CLI 手动激活

用户通过 `/skill research` 手动激活时，Agent 构造一对模拟消息注入 self.messages：

```python
# 模拟 assistant 发起 tool_call
self.messages.append({
    "role": "assistant",
    "content": None,
    "tool_calls": [{
        "id": f"manual_{uuid4().hex[:8]}",
        "type": "function",
        "function": {
            "name": "activate_skill",
            "arguments": json.dumps({"skill_name": name})
        }
    }]
})
# 模拟 tool result 返回技能指令
self.messages.append({
    "role": "tool",
    "tool_call_id": tool_call_id,
    "content": skill.prompt_text
})
```

效果与 LLM 自主调用 activate_skill 工具完全一致。

**user_invocable 限制：** `user_invocable: false` 的技能 CLI 拒绝手动激活，仅允许 LLM 自动激活。

### 回调机制

工具 handler 调用 `skill_registry._on_activate(name, prompt_text)`，Agent 注册此回调。当前实现中回调体为空（pass），为未来版本（如工具过滤）保留扩展点。

---

## 四、组合工具 research_topic

### 工具定义

```python
name = "research_topic"
description = "Deep research a topic: searches the web, fetches top results, and returns structured sources."
parameters = {
    "type": "object",
    "properties": {
        "query": {"type": "string", "description": "搜索查询"},
        "max_sources": {"type": "integer", "description": "最多获取的源数量", "default": 3}
    },
    "required": ["query"]
}
danger_level = "safe"
```

### handler 编排逻辑

```python
async def execute(self, query: str, max_sources: int = 3) -> str:
    # Step 1: 调用 web_search 工具
    search_result = await self.registry.dispatch("web_search", {"query": query})

    # Step 2: 对搜索结果中的前 N 个 URL 调用 fetch_url
    results = json.loads(search_result)
    fetched_contents = []
    for item in results.get("results", [])[:max_sources]:
        content = await self.registry.dispatch("fetch_url", {"url": item["href"]})
        fetched_contents.append({
            "url": item["href"],
            "title": item["title"],
            "content": content
        })

    # Step 3: 返回整合结果
    return json.dumps({"success": True, "query": query, "sources": fetched_contents})
```

### ToolRegistry 新增 dispatch 方法

```python
async def dispatch(self, name: str, args: dict) -> str:
    """内部调用：按名称查找工具并执行，用于组合工具编排。"""
    tool = self.get(name)
    if tool is None:
        return json.dumps({"error": f"Tool '{name}' not found"})
    return await tool.execute(**args)
```

---

## 五、CLI 新增命令

| 命令 | 说明 |
|------|------|
| `/skills` | 列出所有可用技能，标记当前激活的，`user_invocable: false` 显示为 `(auto-only)` |
| `/skill <name>` | 手动激活指定技能（拒绝 `user_invocable: false` 的技能） |
| `/unskill` | 取消当前技能，回到基础模式 |

**/status 增强：** 新增 `当前技能` 行显示当前激活的技能名称。

**错误处理：**
- `/skill` 无参数 → 提示用法
- `/skill unknown_name` → 提示技能不存在
- `/skill xxx`（`user_invocable: false`）→ 提示仅限自动激活
- `/unskill`（无激活技能时）→ 提示当前未激活任何技能

---

## 六、启动流程集成

```python
# __main__.py 中的新增逻辑（伪代码）

from my_small_agent.skills import discover_skills, skill_registry, build_skills_index
from my_small_agent.prompt import PromptManager
from my_small_agent.tools.research_topic import ResearchTopicTool

# 1. 加载配置（已有）
settings = Settings()

# 2. 创建 ToolRegistry（已有）
registry = create_default_registry(settings, memory_manager, sessions_dir)

# 3. 发现并注册所有技能（新增）
discover_skills()

# 4. 注册 activate/deactivate 工具到 ToolRegistry（新增）
#    skills/__init__.py 提供 register_skill_tools(registry) 函数
#    传入 registry 引用后注册 ActivateSkillTool 和 DeactivateSkillTool
register_skill_tools(registry)

# 5. 注册组合工具（新增）
registry.register(ResearchTopicTool(registry))

# 6. 初始化 PromptManager（新增）
prompt_manager = PromptManager()
prompt_manager.update_skills_index(build_skills_index())

# 7. 创建 Agent（修改：增加 prompt_manager 参数）
agent = Agent(llm, registry, settings, memory_manager, prompt_manager)
```

---

## 七、测试策略

| 测试文件 | 覆盖内容 |
|----------|----------|
| `test_skills_registry.py` | SkillRegistry 的 register/activate/deactivate/get |
| `test_skills_discover.py` | discover_skills 扫描与 SKILL.md frontmatter 解析 |
| `test_prompt_manager.py` | PromptManager 加载和拼接逻辑 |
| `test_tools_composite.py` | research_topic 组合工具（mock dispatch） |
| `test_cli_skills.py` | /skills、/skill、/unskill 命令 |
| 现有测试适配 | agent 测试更新初始化参数（添加 prompt_manager） |

---

## 八、不变的部分

- 工具安全分级机制不变（activate/deactivate 都是 safe 级别）
- 会话持久化和上下文压缩机制不变
- 长期记忆注入位置不变（system prompt 之后的第二条 system message）
- 现有所有工具的行为不变
- 版本号升至 0.4.0

---

## 九、文件变更清单

| 文件 | 操作 | 说明 |
|------|------|------|
| `my_small_agent/skills/__init__.py` | 新增 | 自动发现入口 + skill_registry 单例 + build_skills_index |
| `my_small_agent/skills/registry.py` | 新增 | SkillInfo + SkillRegistry + SKILL.md 解析 |
| `my_small_agent/skills/research/SKILL.md` | 新增 | 搜索研究技能 |
| `my_small_agent/skills/code_assistant/SKILL.md` | 新增 | 代码助手技能 |
| `my_small_agent/prompt.py` | 新增 | PromptManager 类 |
| `my_small_agent/system_prompt.md` | 新增 | 基础系统提示词（从 agent.py 提取） |
| `my_small_agent/tools/research_topic.py` | 新增 | 组合工具 |
| `my_small_agent/agent.py` | 修改 | 集成 PromptManager、activate_skill/deactivate_skill 方法 |
| `my_small_agent/cli.py` | 修改 | 新增 /skills /skill /unskill、/status 增强 |
| `my_small_agent/__main__.py` | 修改 | 启动时 skill 发现 + PromptManager 初始化 |
| `my_small_agent/tools/__init__.py` | 修改 | ToolRegistry 新增 dispatch()、注册组合工具 |
| `pyproject.toml` | 修改 | 版本号 0.4.0 |
