"""
QQ 机器人前端 - 通过 QQ 开放平台官方 API 接入私聊对话。

这是与 cli.py 平级的另一种 Agent 前端（常驻后台的消息桥接进程，无用户界面）：
  - 用户在 QQ 客户端内与机器人私聊，本进程负责 QQ 服务器 ↔ Agent 的消息搬运
  - 收消息：botpy WebSocket Gateway（出站长连接，无需公网 IP）
  - 发消息：官方 REST API v2 被动回复（必须携带原消息 msg_id）
  - 单会话架构：单个常驻 Agent 实例，记忆/压缩/技能全部生效
  - 危险工具自动批准（confirm_callback 恒 True，仅机器人创建者本人使用）
"""

import asyncio
import sys
from pathlib import Path

import botpy
from botpy import logger

from my_small_agent.agent import Agent
from my_small_agent.config import Settings
from my_small_agent.session import SessionManager

# 占位反馈文本（LLM + 工具调用耗时较长时让用户感知处理中）
PLACEHOLDER_TEXT = "🤔 思考中..."
# LLM 返回空文本时的兜底提示
EMPTY_REPLY_TEXT = "(无文本回复)"
# 分段发送参数：QQ 单条 C2C 文本上限约 2000 字，预留余量取 1800
SEGMENT_LEN = 1800
# 单条事件消息被动回复次数有限（占位 1 次 + 正文最多 3 段 = 4 次）
MAX_SEGMENTS = 3
# 超出 MAX_SEGMENTS 时的截断提示
TRUNCATED_SUFFIX = "\n…(回复过长已截断)"


async def _auto_approve(tool_name: str, description: str, arguments: dict) -> bool:
    """危险工具确认回调：QQ 场景仅创建者本人使用，一律自动批准。"""
    return True


def _split_segments(content: str) -> list[str]:
    """
    将长回复切分为 ≤SEGMENT_LEN 的分段，最多 MAX_SEGMENTS 段。

    切分优先在换行处断开；找不到换行则硬切。
    超出 MAX_SEGMENTS 的内容截断，末段附加截断提示。
    空内容返回固定兜底提示。
    """
    if not content:
        return [EMPTY_REPLY_TEXT]
    segments: list[str] = []
    remaining = content
    truncated = False
    while remaining:
        if len(segments) >= MAX_SEGMENTS:
            truncated = True
            break
        if len(remaining) <= SEGMENT_LEN:
            segments.append(remaining)
            break
        cut = remaining.rfind("\n", 0, SEGMENT_LEN)
        if cut <= 0:
            cut = SEGMENT_LEN
        segments.append(remaining[:cut])
        remaining = remaining[cut:].lstrip("\n")
    if truncated:
        segments[-1] = segments[-1][: SEGMENT_LEN - len(TRUNCATED_SUFFIX)] + TRUNCATED_SUFFIX
    return segments


def validate_qq_settings(settings: Settings) -> str | None:
    """校验 QQ 配置完整性。返回错误描述；配置完整返回 None。"""
    if not settings.qq_appid:
        return "缺少 QQ_APPID 配置"
    if not settings.qq_appsecret:
        return "缺少 QQ_APPSECRET 配置"
    return None


def _restore_latest_session(agent: Agent, session_manager: SessionManager) -> str | None:
    """
    恢复最近一次会话（机器人重启后对话不断片）。

    成功返回会话标题；无历史或恢复失败返回 None（以新会话启动）。
    """
    sessions = session_manager.list_sessions()
    if not sessions:
        return None
    latest = sessions[0]
    try:
        agent.reset_session(
            messages=latest.messages,
            session_id=latest.session_id,
            title=latest.title,
            created_at=latest.created_at,
        )
    except Exception as e:
        logger.warning(f"会话恢复失败，以新会话启动：{e}")
        return None
    return latest.title


class QQBotClient(botpy.Client):
    """
    QQ 私聊前端。继承 botpy.Client，持有 Agent 实例。

    消息处理模型：
      - asyncio.Lock 串行化：用户连发多条消息时逐条排队，不交错、不丢弃
      - 每条消息先回占位（思考中...），再回正式回复
    """

    def __init__(self, agent: Agent, session_manager: SessionManager, settings: Settings) -> None:
        intents = botpy.Intents(public_guild_messages=True)
        # ext_handlers=False：关闭 botpy 默认的文件日志 handler，仅保留控制台输出
        super().__init__(intents=intents, ext_handlers=False)
        self.agent = agent
        self.session_manager = session_manager
        self.settings = settings
        self._lock = asyncio.Lock()
        # openid 白名单（空集合 = 不限制）
        self._allowed_users: set[str] = {
            u.strip() for u in settings.qq_allowed_users.split(",") if u.strip()
        }

    async def on_ready(self) -> None:
        """WebSocket 连接建立后触发。"""
        logger.info(f"QQ 机器人已就绪：{self.robot.name}")
        if not self._allowed_users:
            logger.warning("未配置 QQ_ALLOWED_USERS 白名单，任何用户均可与机器人对话")

    async def on_c2c_message_create(self, message) -> None:
        """
        C2C 私聊消息入口。过滤顺序：白名单 → 空文本/附件 → 锁内处理。

        message 关键属性（duck typing）：
          id                    消息 ID（被动回复必须携带）
          content               文本内容
          author.union_openid   发送者 openid
          attachments           附件列表（图片等，可能不存在）
        """
        openid = message.author.union_openid
        logger.info(f"收到 C2C 消息：openid={openid}")
        content = (message.content or "").strip()

        # 白名单检查：非白名单用户拒绝
        if self._allowed_users and openid not in self._allowed_users:
            await self.api.post_c2c_message(
                openid=openid, msg_type=0, msg_id=message.id,
                content="抱歉，本机器人仅对指定用户开放。",
            )
            return

        # 空文本处理：附件消息给提示；纯空白文本直接忽略（不消耗被动回复次数）
        if not content:
            if getattr(message, "attachments", None):
                await self.api.post_c2c_message(
                    openid=openid, msg_type=0, msg_id=message.id,
                    content="暂只支持文字消息。",
                )
            return

        async with self._lock:
            await self._handle_message(message, openid, content)

    async def _handle_message(self, message, openid: str, content: str) -> None:
        """锁内处理一条消息：占位 → 对话 → 回复。"""
        # 1. 占位反馈（失败不阻塞主流程）
        try:
            await self.api.post_c2c_message(
                openid=openid, msg_type=0, msg_id=message.id, content=PLACEHOLDER_TEXT
            )
        except Exception as e:
            logger.warning(f"占位消息发送失败：{e}")

        # 2. 执行对话（thinking 内容不回传 QQ，仅使用 content）
        try:
            response = await self.agent.run_turn(content, confirm_callback=_auto_approve)
        except Exception as e:
            logger.error(f"run_turn 处理异常：{e}")
            await self._reply(message, openid, f"处理出错：{e}")
            return

        # 3. 发送正式回复（失败仅记日志，继续保存会话，保持历史连续）
        try:
            await self._reply(message, openid, response.content)
        except Exception as e:
            logger.error(f"回复发送失败：{e}")

        # 4. 持久化 + 自动压缩（压缩提示仅记日志，不占被动回复额度）
        self._save_session()
        if await self._auto_compact_if_needed():
            logger.info("上下文已自动压缩")

    async def _reply(self, message, openid: str, content: str) -> None:
        """分段发送回复，每段均携带原消息 msg_id（被动回复）。"""
        for segment in _split_segments(content):
            await self.api.post_c2c_message(
                openid=openid, msg_type=0, msg_id=message.id, content=segment
            )

    def _save_session(self) -> None:
        """保存当前会话到文件。失败时记录警告，不中断对话。"""
        # title 为空时，从消息列表取第一条 user 消息的前 50 字符
        if not self.agent.session_title:
            for msg in self.agent.messages:
                if msg.get("role") == "user":
                    self.agent.session_title = msg["content"][:50]
                    break
        title = self.agent.session_title or "New Session"
        # 过滤掉 system prompt，只保存对话消息
        messages = [m for m in self.agent.messages if m.get("role") != "system"]
        try:
            self.session_manager.save(
                session_id=self.agent.session_id,
                title=title,
                created_at=self.agent.created_at,
                messages=messages,
            )
        except Exception as e:
            logger.warning(f"会话保存失败：{e}")

    async def _auto_compact_if_needed(self) -> bool:
        """token 估算超过阈值时自动压缩（判定逻辑与 cli.py 一致）。返回是否执行了压缩。"""
        tokens = self.agent.estimate_tokens()
        threshold = int(
            self.agent.settings.max_context_tokens * self.agent.settings.compression_threshold
        )
        min_required = self.agent.settings.head_keep + self.agent.settings.tail_keep
        if tokens >= threshold and len(self.agent.messages) > min_required:
            logger.info(f"Token 用量（{tokens:,}）达到阈值（{threshold:,}），自动压缩中...")
            try:
                before, after = await self.agent.compact_context()
                logger.info(f"自动压缩完成：{before} 条 → {after} 条")
            except Exception as e:
                logger.warning(f"自动压缩失败：{e}")
                return False
            return True
        return False


def main() -> None:
    """
    主函数 - 初始化所有组件并启动 QQ 机器人。

    组装链与 __main__.py 一致（QQBotClient 替代 CLI）：
      Settings → LLMClient → MemoryManager → ToolRegistry → Agent → QQBotClient
    全程同步：client.run() 内部自行创建事件循环（asyncio.run）。
    """
    try:
        from my_small_agent.llm import LLMClient
        from my_small_agent.tools import create_default_registry
        from my_small_agent.memory import MemoryManager
        from my_small_agent.skills import (
            discover_skills,
            skill_registry,
            build_skills_index,
            register_skill_tools,
        )
        from my_small_agent.prompt import PromptManager
        from my_small_agent.tools.research_topic import ResearchTopicTool

        # 1. 加载配置并校验 QQ 凭证（缺失时打印指引并退出，不抛堆栈）
        settings = Settings()
        if error := validate_qq_settings(settings):
            print(f"错误：{error}")
            print(
                "请先在 https://q.qq.com/qqbot/openclaw/ 创建机器人，"
                "并将 AppID/AppSecret 填入 .env（参考 .env.example）"
            )
            sys.exit(1)

        # 2. 组装组件（与 __main__.py 相同）
        llm_client = LLMClient(settings)
        memory_manager = MemoryManager(Path(".genesis") / "memory")
        registry = create_default_registry(
            settings,
            memory_manager=memory_manager,
            sessions_dir=Path(".genesis") / "sessions",
        )
        discover_skills()
        register_skill_tools(registry, skill_registry)
        registry.register(ResearchTopicTool(registry))
        prompt_manager = PromptManager()
        prompt_manager.update_skills_index(build_skills_index())

        agent = Agent(
            llm_client, registry, settings,
            memory_manager=memory_manager, prompt_manager=prompt_manager,
        )
        agent._skill_registry = skill_registry

        session_manager = SessionManager(Path(".genesis") / "sessions")

        # 3. 恢复最近一次会话（存在则恢复，失败则新会话）
        title = _restore_latest_session(agent, session_manager)
        if title:
            print(f"已恢复最近会话：{title}")

        # 4. 启动机器人（阻塞；WebSocket 长连接，断线由 botpy 自动重连）
        client = QQBotClient(agent=agent, session_manager=session_manager, settings=settings)
        client.run(appid=settings.qq_appid, secret=settings.qq_appsecret)
    except KeyboardInterrupt:
        print("\nGoodbye!")
    except SystemExit:
        raise
    except Exception as e:
        print(f"Failed to start: {e}")
        print("Make sure your .env file is configured correctly.")
        sys.exit(1)


def main_entry() -> None:
    """同步入口点 - 供 pyproject.toml 的 agent-qq 命令使用。"""
    main()


if __name__ == "__main__":
    main_entry()
