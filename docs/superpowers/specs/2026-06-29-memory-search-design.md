# 长期记忆与会话搜索功能设计

**日期：** 2026-06-29  
**状态：** 已确认  
**影响文件：** `memory.py`（新增）、`tools/memory_save.py`（新增）、`tools/session_search.py`（新增）、`tools/__init__.py`、`agent.py`、`__main__.py`

---

## 背景

MySmallAgent 已支持会话持久化，但每次启动都是"失忆"状态——不记得用户偏好、环境约定等跨会话知识。本功能为 Agent 添加长期记忆层，让 LLM 自主决定何时保存重要信息，并能搜索历史对话。

---

## 目标

1. 新增 `memory_save` 工具：LLM 自主调用，将用户偏好/约定等写入持久化记忆文件
2. 新增 `session_search` 工具：LLM 通过关键词搜索历史会话消息
3. 记忆注入：新会话启动时将长期记忆作为第二条 system 消息注入，始终开启，无需配置
4. 设计理由：让 LLM 自己决定何时记忆，比每轮强制提取更精准、更节省 token

---

## 架构设计

### 模块边界

```
my_small_agent/
├── memory.py                  ← 新增：MemoryManager（加载/保存/格式化注入文本）
├── tools/
│   ├── memory_save.py         ← 新增：memory_save 工具（safe，调用 MemoryManager）
│   └── session_search.py      ← 新增：session_search 工具（safe，扫描会话文件）
├── tools/__init__.py          ← 改动：注册两个新工具
├── agent.py                   ← 微改：接受可选 MemoryManager，注入第二条 system 消息
└── __main__.py                ← 微改：初始化 MemoryManager，传入 Agent 和工具

.genesis/
└── memory/
    └── memory.json
```

### 数据流

```
启动
  └─ main() 创建 MemoryManager(".genesis/memory")
       └─ 传入 Agent.__init__(memory_manager=...)
            └─ 调用 load_memory_text() → 若非空则插入第二条 system 消息
       └─ 传入 MemorySaveTool(memory_manager=...)
       └─ SessionSearchTool(sessions_dir=...) 传入 registry

LLM 调用 memory_save(content="...")
  └─ MemorySaveTool.execute() → MemoryManager.save_entry() → 原子写 memory.json
  └─ 当前会话 system 消息不变，新记忆下次启动生效

LLM 调用 session_search(query="Python")
  └─ SessionSearchTool.execute() → 扫描 .genesis/sessions/*.json
       └─ 对每条消息 content 做大小写不敏感关键词匹配
       └─ 返回最多 max_results 条匹配摘要
```

---

## 数据结构

### 记忆文件（`.genesis/memory/memory.json`）

```json
{
  "entries": [
    {
      "id": "mem_a3f8b2c1",
      "content": "User prefers Python over JavaScript for scripting",
      "created_at": "2026-06-29T14:35:00+00:00"
    }
  ]
}
```

- `id`：`"mem_"` + 8 位随机十六进制字符串
- `created_at`：UTC ISO 8601，与 SessionManager 保持一致
- 无 `updated_at`（`memory_save` 只创建新条目，不更新现有条目）

---

## memory.py 接口设计

```python
class MemoryManager:
    def __init__(self, memory_dir: Path) -> None: ...

    def save_entry(self, content: str) -> str:
        # 生成 ID，原子写（.tmp → os.replace()）
        # 文件不存在时自动创建（{"entries": []}）
        # 返回生成的 id 字符串

    def load_memory_text(self) -> str:
        # 读取 memory.json，格式化所有条目为注入文本
        # 文件不存在或 JSON 损坏时返回 ""
        # 无条目时返回 ""
```

**注入文本格式（`load_memory_text()` 输出）：**
```
• User prefers Python over JavaScript for scripting
• 项目使用 uv 管理依赖，运行命令是 uv run pytest
```

（每条一行，以 `•` 开头，无额外包装——包装由 Agent 注入时添加）

---

## tools/memory_save.py 接口设计

```python
class MemorySaveTool(Tool):
    name = "memory_save"
    description = "Save important information to long-term memory for future sessions. ..."
    parameters = {
        "type": "object",
        "properties": {
            "content": {
                "type": "string",
                "description": "The information to remember persistently across sessions."
            }
        },
        "required": ["content"]
    }
    danger_level = "safe"

    def __init__(self, memory_manager: MemoryManager) -> None: ...

    async def execute(self, **kwargs) -> str:
        # 调用 self._memory_manager.save_entry(content)
        # 成功：返回 "Memory saved: mem_xxxxxxxx"
        # 失败：返回 "Error saving memory: <message>"
```

---

## tools/session_search.py 接口设计

```python
class SessionSearchTool(Tool):
    name = "session_search"
    description = "Search past conversation history by keyword. ..."
    parameters = {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "Keyword to search for in past conversations."
            },
            "max_results": {
                "type": "integer",
                "description": "Maximum number of results to return (default: 5)."
            }
        },
        "required": ["query"]
    }
    danger_level = "safe"

    def __init__(self, sessions_dir: Path) -> None: ...

    async def execute(self, **kwargs) -> str:
        # 遍历 sessions_dir/*.json
        # 对每条消息 content 做大小写不敏感关键词匹配
        # 返回格式（每条一行）：
        #   1. [abc12345 | 2026-06-28 14:30] user: 帮我写一个爬虫...
        # sessions_dir 不存在 → 返回 "No session history found."
        # 无匹配 → 返回 "No results found for: <query>"
```

**content 截断规则：** 展示前 100 字符，超出追加 `...`

---

## agent.py 改动

### `__init__` 新增参数

```python
def __init__(
    self,
    llm: LLMClient,
    registry: ToolRegistry,
    settings: Settings,
    memory_manager: MemoryManager | None = None,
) -> None:
```

### 记忆注入（在 messages 初始化后立即执行）

```python
self.messages: list[dict] = [
    {"role": "system", "content": SYSTEM_PROMPT}
]

# 注入长期记忆（仅在启动时执行一次，保障 prompt 缓存命中）
if memory_manager is not None:
    memory_text = memory_manager.load_memory_text()
    if memory_text:
        self.messages.append({
            "role": "system",
            "content": (
                "[长期记忆 - 请参考以下用户偏好和约定]\n\n"
                f"{memory_text}\n\n"
                "[本会话中新保存的记忆将在下次会话生效]"
            )
        })
```

**关键约束：** 记忆 system 消息在会话期间不再改变（`reset_session()` 不影响它，它在第二位置固定）。

### reset_session() 调整

`reset_session()` 需保留记忆 system 消息。修改逻辑：

```python
def reset_session(...):
    # 当前：保留 messages[0]（system prompt）
    # 修改后：保留所有 role=system 的消息（包括记忆注入消息）
    system_msgs = [m for m in self.messages if m.get("role") == "system"]
    self.messages = system_msgs
    if messages:
        self.messages.extend(messages)
    ...
```

---

## SYSTEM_PROMPT 增补

在现有 `SYSTEM_PROMPT` 末尾追加：

```
长期记忆工具使用原则：
- 使用 memory_save 保存：用户偏好、环境细节、工具特性、稳定约定
- 不保存：任务进度、会话结果、临时状态（临时信息用 session_search 回忆）
- 优先保存能减少未来用户纠正/提醒的信息
- 使用 session_search 搜索过去的对话内容
```

---

## __main__.py 改动

```python
from my_small_agent.memory import MemoryManager

memory_manager = MemoryManager(Path(".genesis") / "memory")

# 修改工具注册表创建（需将 memory_manager 和 sessions_dir 传入）
registry = create_default_registry(settings, memory_manager, Path(".genesis") / "sessions")

# 修改 Agent 初始化
agent = Agent(llm_client, registry, settings, memory_manager=memory_manager)
```

`create_default_registry` 签名扩展：

```python
def create_default_registry(
    settings: Settings,
    memory_manager: MemoryManager,
    sessions_dir: Path,
) -> ToolRegistry:
```

---

## 错误处理矩阵

| 场景 | 行为 |
|------|------|
| `memory.json` 不存在 | `load_memory_text()` 返回 `""`，不注入 system 消息 |
| `memory.json` JSON 损坏 | 同上，不崩溃 |
| `memory.json` 父目录不存在 | `save_entry()` 自动 `mkdir(parents=True)` |
| `save_entry()` 写入失败 | 返回 `"Error saving memory: <message>"`，不崩溃 |
| `session_search` sessions_dir 不存在 | 返回 `"No session history found."` |
| 会话文件 JSON 损坏 | 跳过该文件，继续搜索 |
| `max_results` 未传 | 默认 5 |

---

## 测试覆盖要求

新增测试文件：`tests/test_memory.py`

| 测试场景 |
|----------|
| `save_entry()` 创建文件并写入正确内容 |
| `save_entry()` 原子写后无 .tmp 残留 |
| `save_entry()` 自动创建目录 |
| `save_entry()` 第二次追加到已有 entries |
| `save_entry()` 返回的 id 以 `mem_` 开头，长度为 12 |
| `load_memory_text()` 文件不存在返回 `""` |
| `load_memory_text()` JSON 损坏返回 `""` |
| `load_memory_text()` 有条目时返回格式化文本（每行 `• content`）|
| `load_memory_text()` entries 为空返回 `""` |

新增测试文件：`tests/test_tools_memory_search.py`

| 测试场景 |
|----------|
| `memory_save.execute()` 调用 MemoryManager 并返回成功消息 |
| `session_search.execute()` 无会话目录返回提示 |
| `session_search.execute()` 关键词匹配返回正确格式 |
| `session_search.execute()` 大小写不敏感匹配 |
| `session_search.execute()` 无匹配返回无结果提示 |
| `session_search.execute()` max_results 限制结果数量 |

**现有测试：** `test_agent.py` 中需为 `reset_session()` 的系统消息保留逻辑补充测试。

> **向后兼容说明：** 现有测试在创建 Agent 时不传 `memory_manager`，消息列表中只有 1 条 system 消息，`reset_session()` 保留后仍为 1 条，现有 `len(agent.messages) == 1` 断言不受影响。

---

## 不在本次范围内

- 记忆条目的更新和删除
- 语义搜索（仅关键词匹配）
- 记忆条目数量上限
- 记忆内容的加密
- `session_search` 的正则表达式支持
