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

import botpy
from botpy import logger

from my_small_agent.agent import Agent
from my_small_agent.config import Settings
from my_small_agent.session import SessionManager

# 占位反馈文本（LLM + 工具调用耗时较长时让用户感知处理中）
PLACEHOLDER_TEXT = "🤔 思考中..."
# LLM 返回空文本时的兜底提示
EMPTY_REPLY_TEXT = "(无文本回复)"


async def _auto_approve(tool_name: str, description: str, arguments: dict) -> bool:
    """危险工具确认回调：QQ 场景仅创建者本人使用，一律自动批准。"""
    return True


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

    async def _reply(self, message, openid: str, content: str) -> None:
        """发送回复，始终携带原消息 msg_id（被动回复）。"""
        await self.api.post_c2c_message(
            openid=openid, msg_type=0, msg_id=message.id,
            content=content or EMPTY_REPLY_TEXT,
        )
