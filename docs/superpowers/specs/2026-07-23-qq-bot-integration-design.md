# QQ 机器人接入功能设计

**日期：** 2026-07-23  
**状态：** 待评审  
**影响文件：** `qq_bot.py`（新增）、`config.py`、`pyproject.toml`、`.env.example`、`tests/test_qq_bot.py`（新增）

---

## 背景

MySmallAgent 当前仅有 CLI 一种交互前端。本功能为 Agent 增加 QQ 私聊前端：
通过 QQ 开放平台的快捷创建通道（https://q.qq.com/qqbot/openclaw/）免审核创建机器人，
以官方 WebSocket Gateway 接收 C2C（私聊）消息、官方 REST API v2 回复消息，
使用户可以在手机/桌面 QQ 中与自己的 Agent 对话。

**使用场景约束（已与需求方确认）：**
- 仅与超级管理员（机器人创建者本人）私聊，无群聊、无多用户
- 工具安全不限制：危险工具（写文件/执行 shell 等）自动批准执行
- 单会话架构：单个常驻 Agent 实例，记忆/压缩/技能全部生效

---

## 目标

1. 新增 `qq_bot.py` 前端入口，与 `cli.py` 平级，Agent 核心零改动
2. QQ 私聊消息驱动 `agent.run_turn()`，回复通过 C2C 被动消息返回
3. 复用现有能力：LLM 流式关闭、长期记忆、上下文自动压缩、技能系统、会话持久化
4. 机器人重启后自动恢复最近一次会话（对话不断片）
5. 配置化：AppID/AppSecret 走 `.env`，与现有配置体系一致

---

## 前置准备（用户手动步骤，非代码）

1. PC 打开 https://q.qq.com/qqbot/openclaw/ ，手机 QQ 扫码登录
2. 点击"创建机器人"，在机器人设置页复制 **AppID** 和 **AppSecret**
   - ⚠️ AppSecret 不明文存储，离开页面后只能重新生成，须立即保存
3. 填入 `.env`（见配置设计）

---

## 技术机制（已核实官方文档与 botpy 仓库）

| 环节 | 机制 |
|------|------|
| SDK | `qq-botpy`（PyPI 包名，import 名 `botpy`），Python 3.8+，要求 ≥1.1.5（AppSecret 鉴权） |
| 鉴权 | `client.run(appid=..., secret=...)`，SDK 自动获取并刷新 access_token |
| 收消息 | WebSocket Gateway 事件 `C2C_MESSAGE_CREATE` → 回调 `on_c2c_message_create(message)` |
| 网络要求 | **无需公网 IP/域名**：WebSocket 为出站长连接（进程主动连腾讯服务器），NAT/家庭宽带可跑；不采用需要公网回调地址的 Webhook 模式 |
| 事件订阅 | `botpy.Intents(public_guild_messages=True)`（1<<30 公域消息域，覆盖 C2C 与群@） |
| 发消息 | `await self.api.post_c2c_message(openid=..., msg_type=0, content=..., msg_id=...)` |
| 用户标识 | `message.author.union_openid`（发送者 openid） |
| 被动回复约束 | 必须携带收到消息的 `msg_id`；单条事件消息可被动回复次数有限（约 4 次） |
| 消息长度 | 单条 C2C 文本约 2000 字上限 |
| 主动推送 | 每月限量（本设计不依赖主动推送） |
| Markdown | msg_type=2 需平台额外权限，首版仅用纯文本（msg_type=0） |

---

## 架构设计

### 模块边界

```
my_small_agent/
├── qq_bot.py           ← 新增：QQ 前端（botpy Client + 组装链 + 消息处理）
├── config.py           ← 微改：新增 3 个配置项
├── agent.py            ← 零改动
├── cli.py              ← 零改动
└── __main__.py         ← 零改动（CLI 入口不受影响）

pyproject.toml          ← 微改：新增依赖 qq-botpy + scripts 入口
.env / .env.example     ← 微改：新增 QQ_* 配置项
```

**定位说明：** `qq_bot.py` 不是用户界面，而是常驻后台的**消息桥接进程**——用户在 QQ 客户端内与机器人聊天，该进程负责 QQ 服务器 ↔ Agent 之间的消息搬运。它替代的是 CLI 终端窗口（CLI 从键盘读输入，它从腾讯服务器读输入）。

`qq_bot.py` 的组装链完全复用 `__main__.py` 的模式：

```
Settings → LLMClient → MemoryManager → ToolRegistry(+技能+组合工具) → PromptManager → Agent
                                                                       ↓
                                              QQBotClient(botpy.Client) ← 持有 Agent 引用
```

### 数据流

```
启动
  └─ main() 组装组件（同 __main__.py）
       └─ SessionManager.list_sessions() 取最近会话 → agent.reset_session(...)（存在则恢复）
            └─ QQBotClient.run(appid, secret) → WebSocket 长连接建立

收到 QQ 私聊消息
  └─ on_c2c_message_create(message)
       ├─ 白名单检查（配置 qq_allowed_users 时）
       ├─ 忽略空文本
       ├─ asyncio.Lock 排队（防并发交错）
       ├─ post_c2c_message("🤔 思考中...")      ← 占位反馈
       ├─ agent.run_turn(content, confirm_callback=auto_approve)
       ├─ post_c2c_message(回复, msg_id=...)     ← 分段发送
       ├─ _save_session()                        ← 持久化
       └─ _auto_compact_if_needed()              ← 自动压缩（复用 CLI 逻辑）

启动时打印
  └─ 机器人就绪日志（含自身 openid 提示，便于配置白名单）
```

---

## qq_bot.py 接口设计

```python
class QQBotClient(botpy.Client):
    """QQ 私聊前端。继承 botpy.Client，持有 Agent 实例。"""

    def __init__(self, agent: Agent, session_manager: SessionManager,
                 settings: Settings) -> None:
        intents = botpy.Intents(public_guild_messages=True)
        super().__init__(intents=intents)
        self.agent = agent
        self.session_manager = session_manager
        self.settings = settings
        self._lock = asyncio.Lock()            # 消息处理串行化
        self._allowed_users: set[str] = ...     # 从 settings 解析

    async def on_ready(self) -> None:
        """连接建立后打印就绪日志（含 robot 信息）。"""

    async def on_c2c_message_create(self, message) -> None:
        """C2C 私聊消息入口。整个消息处理主流程。"""

    async def _handle_message(self, message) -> None:
        """锁内处理：占位 → run_turn → 分段回复 → 保存 → 压缩检查。"""

    async def _reply(self, message, content: str) -> None:
        """分段发送回复。每段 ≤1800 字符，最多 3 段，优先换行处断开。"""

    async def _auto_compact_if_needed(self) -> bool:
        """复用 CLI 的自动压缩判定逻辑（阈值 + 最少消息数）。返回是否执行了压缩。"""

    def _save_session(self) -> None:
        """与 CLI._save_session 相同的持久化逻辑。"""

async def _auto_approve(tool_name: str, description: str, arguments: dict) -> bool:
    """confirm_callback：QQ 场景不限制工具，一律批准。"""
    return True

async def main() -> None:
    """组装所有组件并启动机器人。失败时打印配置提示。"""

def main_entry() -> None:
    """同步入口，供 pyproject scripts 使用。"""
```

### 组装逻辑（`main()`）

逐一复用 `__main__.py` 的步骤：Settings → LLMClient → MemoryManager →
`create_default_registry` → `discover_skills` → `register_skill_tools` →
`ResearchTopicTool` → `PromptManager` → Agent → SessionManager →
恢复最近会话 → `QQBotClient(...).run(appid=settings.qq_appid, secret=settings.qq_appsecret)`。

**差异点：**
- 不创建 CLI，创建 `QQBotClient`
- 启动时尝试恢复最近会话：`list_sessions()` 第一个（updated_at 最新）→ `load()` → `agent.reset_session(messages=..., session_id=..., title=..., created_at=...)`；无历史或加载失败则全新会话

---

## 消息处理算法

### 主流程（`on_c2c_message_create`）

```
1. 提取 openid = message.author.union_openid，文本 = message.content.strip()
2. 白名单检查：_allowed_users 非空且 openid 不在其中 → 回复提示并 return
3. 文本为空（纯图片/语音/附件）→ 回复"暂只支持文字消息"并 return
4. async with self._lock:  → _handle_message()
```

### 锁内处理（`_handle_message`）

```
1. 发送占位消息 "🤔 思考中..."（消耗 1 次被动回复）
2. response = await agent.run_turn(content, confirm_callback=_auto_approve)
   - 异常捕获 → 回复"处理出错：{e}"并 return
3. await _reply(message, response.content)
4. _save_session()
5. _auto_compact_if_needed() → 若执行了压缩，仅记录日志，不发送 QQ 消息（原因：占位 1 + 正文最多 3 段已用满单条事件消息 4 次被动回复额度）
```

### 分段发送算法（`_reply`）

- 每段上限 `SEGMENT_LEN = 1800` 字符（预留 200 字余量）
- 切分时在段尾向前寻找最后一个 `\n`，在换行处断开；找不到则硬切
- 最多 `MAX_SEGMENTS = 3` 段（占位 1 + 正文 3 = 4 次被动回复，顶格官方约束）
- 超出部分截断，末段追加 `"\n…(回复过长已截断)"`
- 空回复（content 为空字符串）→ 发送固定提示"(无文本回复)"

### 自动压缩触发（`_auto_compact_if_needed`）

判定条件与 `cli.py` 完全一致：

```
tokens = agent.estimate_tokens()
threshold = max_context_tokens * compression_threshold
min_required = head_keep + tail_keep
触发: tokens >= threshold 且 len(agent.messages) > min_required
动作: await agent.compact_context()；失败仅打日志不中断
```

---

## config.py 改动

```python
# QQ 机器人配置（qq_bot.py 前端使用；CLI 模式可留空）
qq_appid: str = ""                 # QQ 机器人 AppID
qq_appsecret: str = ""             # QQ 机器人 AppSecret
qq_allowed_users: str = ""         # 可选：允许的 openid 白名单，逗号分隔；空 = 不限制
```

**启动校验：** `qq_bot.py` 的 `main()` 中 `qq_appid` / `qq_appsecret` 为空时
打印明确错误提示并退出（不抛堆栈），提示用户完成"前置准备"。

`.env.example` 追加：

```env
# QQ 机器人（可选，仅 QQ 前端需要）
QQ_APPID=
QQ_APPSECRET=
QQ_ALLOWED_USERS=
```

---

## pyproject.toml 改动

```toml
dependencies = [
    ...,
    "qq-botpy>=1.1.5",
]

[project.scripts]
agent = "my_small_agent.__main__:main_entry"
agent-qq = "my_small_agent.qq_bot:main_entry"   # 新增
```

---

## 安全设计

| 维度 | 决策 | 理由 |
|------|------|------|
| 危险工具确认 | `confirm_callback` 一律返回 `True` | 需求方明确"不限制"；仅本人使用 |
| 凭证管理 | AppID/Secret 仅存 `.env`（已在 .gitignore），代码不落盘 | 与 openai_api_key 同级 |
| 访问控制 | 可选 `qq_allowed_users` 白名单 | 防其他 QQ 用户搜到机器人后滥用；机器人启动和收到首条消息时打印 openid 便于配置 |
| 被动回复 | 始终携带 `msg_id`，不做主动推送 | 规避官方主动消息限额；合规 |
| Plan 模式 | QQ 前端不提供 `/plan` 等斜杠命令，Plan 模式固定关闭 | 私聊助手定位；工具调用不受只读约束 |
| thinking 内容 | `AgentResponse.thinking` 不发送到 QQ | 思维链是内部推理，不回传给 IM；回复仅 `content` |

---

## 边界条件与错误处理矩阵

| 场景 | 行为 |
|------|------|
| `qq_appid`/`qq_appsecret` 未配置 | 启动时打印"请在 .env 配置 QQ_APPID/QQ_APPSECRET"并退出码 1 |
| AppSecret 错误 | botpy 抛鉴权异常 → 捕获并打印"鉴权失败，请检查 AppSecret" |
| 用户连发多条消息 | `asyncio.Lock` 排队逐条处理，不丢消息不交错 |
| 纯图片/语音/文件消息 | 回复"暂只支持文字消息" |
| 空白文本（空格/换行） | 直接忽略，不回复（避免消耗被动回复次数） |
| `run_turn` 抛异常 | 回复"处理出错：{e}"，会话历史可能已追加 user 消息，不影响后续轮次 |
| LLM 回复 >5400 字 | 截断至 3 段，末段附截断提示 |
| 占位消息发送失败 | 打日志，继续处理（不阻塞主流程） |
| 回复发送失败（网络） | 打日志并保存会话（历史已更新，下次对话连续） |
| 自动压缩失败 | 打日志，不中断对话（与 CLI 一致） |
| 会话恢复失败（JSON 损坏） | 打日志，以全新会话启动 |
| WebSocket 断连 | botpy 内置自动重连，无需处理 |
| QQ 官方限频 | 被动回复次数耗尽时 post_c2c_message 抛错 → 打日志 |

---

## 测试覆盖要求

新增测试文件：`tests/test_qq_bot.py`。botpy 的 `Client.__init__` 与网络层全部 mock，
不连接真实 QQ 服务器。

| 测试场景 |
|----------|
| 收到 C2C 文本消息 → 调用 `agent.run_turn` 且内容正确 |
| `run_turn` 返回后 → `post_c2c_message` 被调用，携带原 `msg_id` |
| `confirm_callback`（`_auto_approve`）→ 恒返回 True |
| 超长回复 → 分 3 段发送，每段 ≤1800 字符 |
| 超长回复优先在换行处断开 |
| 空文本消息 → 忽略，不调用 run_turn |
| 白名单命中/未命中 → 放行/拒绝回复 |
| 占位消息先于正式回复发送 |
| 两条消息并发到达 → 串行处理（第二条在第一条完成后才开始 run_turn） |
| `run_turn` 抛异常 → 回复错误提示，不崩溃 |
| token 超阈值 → 触发 `compact_context` |
| 未配置 appid/secret 启动 → 优雅退出 |

现有测试：全部不受影响（`config.py` 仅新增带默认值字段，`pyproject.toml` 新增依赖不影响已安装环境逻辑）。

---

## 不在本次范围内

- 群聊消息（GROUP_AT_MESSAGE_CREATE）与频道消息
- 图片/语音/文件等多媒体消息收发
- QQ 官方 C2C `stream_messages` 原生流式回复（二期增强）
- Markdown 消息类型（msg_type=2，需平台权限申请）
- QQ 侧斜杠命令（/status、/sessions 等 CLI 命令的 QQ 版）
- 多机器人账户
- 主动推送消息
