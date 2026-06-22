"""
LLM 客户端模块 - 封装 OpenAI 异步 API 调用。

工作原理：
  - 基于 openai 库的 AsyncOpenAI 客户端
  - 提供 chat() 方法，发送消息列表，返回模型响应
  - 支持可选传入工具定义，让模型知道可以调用哪些工具
  - 兼容所有 OpenAI API 格式的服务（DeepSeek、本地模型等）
"""

from openai import AsyncOpenAI
from openai.types.chat import ChatCompletion

from my_small_agent.config import Settings


class LLMClient:
    """
    OpenAI 异步聊天客户端的封装。

    职责：
      - 管理与 OpenAI API 的连接
      - 提供统一的 chat() 接口给 Agent 使用
    """

    def __init__(self, settings: Settings) -> None:
        # 创建异步 OpenAI 客户端，传入 API 密钥和自定义地址
        self.client = AsyncOpenAI(
            api_key=settings.openai_api_key,
            base_url=settings.openai_base_url,
        )
        self.model = settings.openai_model  # 保存模型名称

    async def chat(
        self,
        messages: list[dict],
        tools: list[dict] | None = None,
    ) -> ChatCompletion:
        """
        向 LLM 发送消息并获取响应。

        参数：
          messages: 对话历史列表，每条消息格式为 {"role": "...", "content": "..."}
          tools:    可选，工具定义列表（OpenAI 格式），让模型知道能调用哪些工具

        返回：
          ChatCompletion 对象，包含模型的完整响应（文本回复或工具调用请求）
        """
        # 构造 API 调用的参数
        kwargs: dict = {
            "model": self.model,
            "messages": messages,
        }

        # 只有传入了工具定义时才添加 tools 参数
        if tools:
            kwargs["tools"] = tools

        # 异步调用 OpenAI API，等待结果
        return await self.client.chat.completions.create(**kwargs)
