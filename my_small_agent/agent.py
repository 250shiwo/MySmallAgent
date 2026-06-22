"""Agent core - manages the conversation loop with tool calling."""

import json
from typing import Any, Callable, Coroutine

from my_small_agent.config import Settings
from my_small_agent.llm import LLMClient
from my_small_agent.tools import ToolRegistry

# Type for the confirmation callback
ConfirmCallback = Callable[[str, str, dict], Coroutine[Any, Any, bool]]

SYSTEM_PROMPT = """You are a helpful assistant with access to tools for file operations and shell commands. Use the available tools when needed to help the user accomplish their tasks."""


class Agent:
    """Core agent that manages conversation loop and tool execution."""

    def __init__(
        self,
        llm: LLMClient,
        registry: ToolRegistry,
        settings: Settings,
    ) -> None:
        self.llm = llm
        self.registry = registry
        self.max_iterations = settings.max_iterations
        self.messages: list[dict] = [
            {"role": "system", "content": SYSTEM_PROMPT}
        ]

    async def run_turn(
        self,
        user_input: str,
        confirm_callback: ConfirmCallback,
    ) -> str:
        """Run a single conversation turn, potentially with multiple tool calls.

        Args:
            user_input: The user's message text.
            confirm_callback: Async function called for dangerous tools.
                Signature: (tool_name, description, arguments) -> bool

        Returns:
            The final text response from the LLM.
        """
        self.messages.append({"role": "user", "content": user_input})

        tools = self.registry.get_openai_tools()
        iteration = 0

        while iteration < self.max_iterations:
            iteration += 1

            response = await self.llm.chat(
                messages=self.messages,
                tools=tools if tools else None,
            )

            message = response.choices[0].message

            # If no tool calls, we have our final answer
            if not message.tool_calls:
                content = message.content or ""
                self.messages.append({"role": "assistant", "content": content})
                return content

            # Add assistant message with tool calls to history
            self.messages.append(message.model_dump())

            for tool_call in message.tool_calls:
                tool_name = tool_call.function.name
                arguments = json.loads(tool_call.function.arguments)

                tool = self.registry.get(tool_name)
                if tool is None:
                    result = f"Error: Unknown tool '{tool_name}'"
                else:
                    # Check danger level
                    if tool.danger_level == "dangerous":
                        confirmed = await confirm_callback(
                            tool_name, tool.description, arguments
                        )
                        if not confirmed:
                            result = "User rejected this tool execution."
                        else:
                            result = await self._execute_tool(tool, arguments)
                    else:
                        result = await self._execute_tool(tool, arguments)

                # Add tool result to history
                self.messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": tool_call.id,
                        "content": result,
                    }
                )

        return "Reached maximum iteration limit. Please try a simpler request."

    async def _execute_tool(self, tool: Any, arguments: dict) -> str:
        """Execute a tool and handle any exceptions."""
        try:
            return await tool.execute(**arguments)
        except Exception as e:
            return f"Error executing {tool.name}: {e}"

    def clear_history(self) -> None:
        """Clear conversation history, keeping only the system prompt."""
        self.messages = [self.messages[0]]
