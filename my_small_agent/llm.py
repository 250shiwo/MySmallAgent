"""
LLM 客户端模块 - 封装 OpenAI 异步 API 调用。

工作原理：
  - 基于 openai 库的 AsyncOpenAI 客户端
  - 提供 chat() 方法，发送消息列表，返回模型响应
  - 提供 chat_stream() 方法，返回流式响应的异步迭代器
  - 支持可选 thinking 参数启用 DeepSeek 思维链
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
      - 提供统一的 chat() 和 chat_stream() 接口给 Agent 使用
      - 支持 thinking 参数透传（DeepSeek Reasoning）
    """

    def __init__(self, settings: Settings) -> None:
        # 创建异步 OpenAI 客户端，传入 API 密钥和自定义地址
        self.client = AsyncOpenAI(
            api_key=settings.openai_api_key,
            base_url=settings.openai_base_url,
        )
        self.model = settings.openai_model  # 保存模型名称

    def _build_kwargs(
        self,
        messages: list[dict],
        tools: list[dict] | None = None,
        thinking_enabled: bool = False,
        stream: bool = False,
    ) -> dict:
        """
        构造 API 调用参数（内部复用）。

        参数：
          messages:         对话历史列表
          tools:            可选，工具定义列表（OpenAI 格式）
          thinking_enabled: 是否启用思维链（DeepSeek Reasoning）
          stream:           是否启用流式响应

        返回：
          传给 OpenAI API 的参数字典
        """
        kwargs: dict = {
            "model": self.model,
            "messages": messages,
        }

        # 只有传入了工具定义时才添加 tools 参数
        if tools:
            kwargs["tools"] = tools

        # DeepSeek Thinking：通过 thinking 参数启用
        if thinking_enabled:
            kwargs["thinking"] = {"type": "enabled"}

        # 流式输出
        if stream:
            kwargs["stream"] = True

        return kwargs

    async def chat(
        self,
        messages: list[dict],
        tools: list[dict] | None = None,
        thinking_enabled: bool = False,
    ) -> ChatCompletion:
        """
        向 LLM 发送消息并获取完整响应（非流式）。

        参数：
          messages:         对话历史列表，每条消息格式为 {"role": "...", "content": "..."}
          tools:            可选，工具定义列表（OpenAI 格式），让模型知道能调用哪些工具
          thinking_enabled: 是否启用思维链（DeepSeek Reasoning）

        返回：
          ChatCompletion 对象，包含模型的完整响应（文本回复或工具调用请求）
        """
        kwargs = self._build_kwargs(messages, tools, thinking_enabled)
        return await self.client.chat.completions.create(**kwargs)

    async def chat_stream(
        self,
        messages: list[dict],
        tools: list[dict] | None = None,
        thinking_enabled: bool = False,
    ):
        """
        向 LLM 发送消息并获取流式响应。

        参数：
          messages:         对话历史列表
          tools:            可选，工具定义列表（OpenAI 格式）
          thinking_enabled: 是否启用思维链

        返回：
          AsyncStream[ChatCompletionChunk] 异步迭代器，逐块 yield chunk
        """
        kwargs = self._build_kwargs(messages, tools, thinking_enabled, stream=True)
        return await self.client.chat.completions.create(**kwargs)
