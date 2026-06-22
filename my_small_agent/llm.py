"""OpenAI-compatible LLM client wrapper."""

from openai import AsyncOpenAI
from openai.types.chat import ChatCompletion

from my_small_agent.config import Settings


class LLMClient:
    """Async wrapper around OpenAI chat completions API."""

    def __init__(self, settings: Settings) -> None:
        self.client = AsyncOpenAI(
            api_key=settings.openai_api_key,
            base_url=settings.openai_base_url,
        )
        self.model = settings.openai_model

    async def chat(
        self,
        messages: list[dict],
        tools: list[dict] | None = None,
    ) -> ChatCompletion:
        """Send messages to the LLM and get a response.

        Args:
            messages: Conversation history in OpenAI message format.
            tools: Optional list of tool definitions in OpenAI format.

        Returns:
            The complete chat response.
        """
        kwargs: dict = {
            "model": self.model,
            "messages": messages,
        }
        if tools:
            kwargs["tools"] = tools

        return await self.client.chat.completions.create(**kwargs)
