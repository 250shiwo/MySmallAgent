# 会话持久化与恢复功能设计

**日期：** 2026-06-29  
**状态：** 已确认  
**影响文件：** `session.py`（新增）、`agent.py`、`cli.py`、`__main__.py`

---

## 背景

MySmallAgent 当前每次启动均创建全新会话，进程退出后对话历史完全丢失。
本功能为 Agent 添加持久化层，支持跨进程恢复历史对话。

---

## 目标

1. 每次创建 Agent 实例自动生成唯一 Session ID（UUID4）
2. 每轮对话结束后将会话写入 `.genesis/sessions/{session_id}.json`
3. 写入使用"先写临时文件再 rename"原子策略，防止崩溃导致数据损坏
4. CLI 新增三条命令：`/sessions`、`/resume`、`/new`

---

## 架构设计

### 模块边界

```
my_small_agent/
├── session.py          ← 新增：持久化模块（SessionData + SessionManager）
├── agent.py            ← 微改：新增 session_id / session_title / created_at 字段 + reset_session()
├── cli.py              ← 改动：新增命令处理 + 自动保存逻辑
└── __main__.py         ← 微改：初始化 SessionManager 并传入 CLI

.genesis/
└── sessions/
    └── {session_id}.json
```

### 数据流

```
启动
  └─ main() 创建 SessionManager(".genesis/sessions")
       └─ 传入 CLI.__init__()

每轮对话
  └─ _run_agent_turn() 完成
       └─ session_manager.save(agent) → 原子写文件

/sessions
  └─ session_manager.list_sessions() → 按 updated_at 倒序展示

/resume abc123
  └─ session_manager.find_by_prefix("abc123")
       └─ agent.reset_session(messages=..., session_id=..., title=..., created_at=...)

/new
  └─ agent.reset_session() → 新 UUID，清空消息
```

---

## 数据结构

### 会话文件（JSON）

路径：`.genesis/sessions/{session_id}.json`

```json
{
  "session_id": "550e8400-e29b-41d4-a716-446655440000",
  "created_at": "2026-06-29T14:30:00+08:00",
  "updated_at": "2026-06-29T14:35:22+08:00",
  "title": "帮我写一个 Python 爬虫",
  "messages": [
    {"role": "user", "content": "帮我写一个 Python 爬虫"},
    {"role": "assistant", "content": "好的，以下是示例代码..."}
  ]
}
```

**规则：**
- `messages` 不包含 system prompt（加载时重新插入）
- `title` 取第一条 `role=user` 消息，截取前 50 字符；无 user 消息时为 `"New Session"`
- 时间戳使用 ISO 8601 格式，含时区（与现有 `timezone` 配置对齐）
- `tool_calls`、`reasoning_content` 等字段原样序列化保存

### SessionData dataclass

```python
@dataclass
class SessionData:
    session_id: str
    created_at: str   # ISO 8601
    updated_at: str   # ISO 8601
    title: str
    messages: list[dict]
```

---

## session.py 接口设计

```python
class SessionManager:
    def __init__(self, sessions_dir: Path) -> None: ...

    def save(
        self,
        session_id: str,
        title: str,
        created_at: str,
        messages: list[dict],   # 不含 system prompt
    ) -> None:
        # 1. 确保目录存在（mkdir parents）
        # 2. 写入临时文件（同目录，.tmp 后缀）
        # 3. os.replace(tmp, target) 原子重命名
        # 4. 异常时删除临时文件，向上抛出（CLI 捕获并打印警告）

    def load(self, session_id: str) -> SessionData | None:
        # 读取 JSON，解析失败返回 None

    def list_sessions(self) -> list[SessionData]:
        # 扫描目录下所有 .json，跳过损坏文件，按 updated_at 倒序

    def find_by_prefix(self, prefix: str) -> SessionData | None:
        # 找 session_id.startswith(prefix) 的会话
        # 无匹配 → None；多匹配 → raise AmbiguousPrefixError
```

---

## agent.py 改动

### 新增字段（`__init__`）

```python
from uuid import uuid4
from datetime import datetime, timezone

self.session_id: str = str(uuid4())
self.session_title: str = ""
self.created_at: str = datetime.now(timezone.utc).isoformat()
```

### 新增方法 `reset_session()`

```python
def reset_session(
    self,
    messages: list[dict] | None = None,
    session_id: str | None = None,
    title: str = "",
    created_at: str | None = None,
) -> None:
    """重置会话状态。用于 /new 和 /resume 命令。"""
    self.messages = [self.messages[0]]   # 保留 system prompt
    if messages:
        self.messages.extend(messages)
    self.session_id = session_id or str(uuid4())
    self.session_title = title
    self.created_at = created_at or datetime.now(timezone.utc).isoformat()
```

**不变：** `clear_history()` 仍保留（向后兼容），内部调用 `reset_session()`。

---

## cli.py 改动

### `__init__` 新增 SessionManager

```python
def __init__(self, agent: Agent, session_manager: SessionManager) -> None:
    self.agent = agent
    self.session_manager = session_manager
    ...
```

### 自动保存（`_run_agent_turn` 末尾）

```python
# 取 title：已有则用，否则从消息列表中提取
title = self.agent.session_title
if not title:
    for msg in self.agent.messages:
        if msg["role"] == "user":
            title = msg["content"][:50]
            self.agent.session_title = title
            break

try:
    self.session_manager.save(
        session_id=self.agent.session_id,
        title=title or "New Session",
        created_at=self.agent.created_at,
        messages=[m for m in self.agent.messages if m["role"] != "system"],
    )
except Exception as e:
    self.console.print(f"[yellow]⚠ 会话保存失败：{e}[/yellow]")
```

### 新命令处理

**`/sessions`**
- 调用 `session_manager.list_sessions()`
- 用 Rich Panel 展示列表，每项显示：ID 前 8 位、title、updated_at（格式化为 `YYYY-MM-DD HH:mm`）
- 当前会话用 `[cyan]▶[/cyan]` 标注
- 无历史会话时显示提示

**`/resume <prefix>`**
- 解析命令参数，取 prefix
- 缺少参数 → 打印用法提示
- `find_by_prefix()` 返回 None → 红色提示"未找到匹配会话"
- 前缀模糊（多匹配）→ 黄色提示"前缀不唯一，请补充更多字符"
- 成功 → `agent.reset_session(...)` 加载历史，打印绿色成功提示和会话标题

**`/new`**
- 调用 `agent.reset_session()`（不保存当前会话，避免空会话写入）
- 打印绿色提示"已创建新会话"

**`/clear` 行为调整**
- 原为仅清空消息；现在同时调用 `agent.reset_session()` 生成新 session_id
- 保证 `/clear` 后的对话不会覆盖之前的会话文件

### 命令注册（`_handle_command`）

在现有 if-elif 链中新增：
```python
elif cmd == "/sessions":
    self._print_sessions()
elif cmd == "/resume":
    await self._resume_session(command)
elif cmd == "/new":
    self._new_session()
```

### `_print_status` 补充会话信息

在 Panel 中新增：
```
  当前会话: [dim]{session_id[:8]}[/dim]  {title}
```

---

## __main__.py 改动

```python
from pathlib import Path
from my_small_agent.session import SessionManager

sessions_dir = Path(".genesis") / "sessions"
session_manager = SessionManager(sessions_dir)

cli = CLI(agent, session_manager)
```

---

## 错误处理矩阵

| 场景 | 行为 |
|------|------|
| `.genesis/sessions/` 不存在 | `save()` 自动 `mkdir(parents=True, exist_ok=True)` |
| JSON 文件损坏 | `list_sessions()` 跳过该文件，`load()` 返回 None |
| `os.replace()` 失败 | 删除 `.tmp` 文件，打印 `[yellow]⚠ 会话保存失败[/yellow]`，不中断对话 |
| `/resume` 无匹配前缀 | 打印红色提示，不中断 REPL 循环 |
| `/resume` 前缀多匹配 | 打印黄色提示，列出所有匹配的 ID 前缀 |
| `/resume` 无参数 | 打印用法：`/resume <session_id_prefix>` |
| 恢复的消息含非 JSON 序列化字段 | 不处理（保存时已用 `json.dump`，读取即可） |

---

## 测试覆盖要求

新增测试文件：`tests/test_session.py`

| 测试场景 |
|----------|
| `save()` 原子写：临时文件不残留，目标文件内容正确 |
| `load()` 正常读取 |
| `load()` 文件不存在 → 返回 None |
| `load()` JSON 损坏 → 返回 None |
| `list_sessions()` 按 updated_at 倒序 |
| `list_sessions()` 目录为空 → 返回空列表 |
| `find_by_prefix()` 唯一匹配 |
| `find_by_prefix()` 无匹配 → None |
| `find_by_prefix()` 多匹配 → 抛出 AmbiguousPrefixError |
| `agent.reset_session()` 保留 system prompt，替换其余消息 |

现有测试：`test_agent.py`、`test_agent_stream.py` 需在 Agent 构造函数签名不变的前提下通过，`session_id` 等字段是新增属性不影响现有逻辑。

---

## 不在本次范围内

- 会话数量上限（无限保留）
- 会话加密存储
- 多进程并发写入保护
- 会话搜索/过滤功能
- 手动命名会话
