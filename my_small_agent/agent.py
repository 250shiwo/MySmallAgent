"""
Agent 核心模块 - 管理对话循环和工具调用的核心逻辑。

这是整个 Agent 的"大脑"，工作原理：
  1. 用户发送消息 → Agent 将消息追加到对话历史
  2. 调用 LLM（携带所有工具定义）→ 模型决定是回复文本还是调用工具
  3. 如果模型要调用工具：
     - 安全工具（safe）→ 自动执行
     - 危险工具（dangerous）→ 弹出确认框，用户同意才执行
     - 将工具执行结果追加到历史 → 再次调用 LLM（让模型看到结果）
  4. 重复步骤 2-3，直到模型返回纯文本回复或达到最大迭代次数
"""

import json
from typing import Any, Callable, Coroutine

from my_small_agent.config import Settings
from my_small_agent.llm import LLMClient
from my_small_agent.tools import ToolRegistry

# 确认回调函数的类型签名：
# 参数：(工具名称, 工具描述, 参数字典) → 返回：bool（是否允许执行）
ConfirmCallback = Callable[[str, str, dict], Coroutine[Any, Any, bool]]

# System Prompt：告诉模型它的身份和能力
SYSTEM_PROMPT = """You are a helpful assistant with access to tools for file operations and shell commands. Use the available tools when needed to help the user accomplish their tasks."""


class Agent:
    """
    Agent 核心类 - 驱动对话循环和工具执行。

    核心属性：
      llm:             LLM 客户端，负责调用模型
      registry:        工具注册表，存储所有可用工具
      max_iterations:  单次对话最大迭代次数（防止无限循环）
      messages:        对话历史列表（内存中维护）
    """

    def __init__(
        self,
        llm: LLMClient,
        registry: ToolRegistry,
        settings: Settings,
    ) -> None:
        self.llm = llm
        self.registry = registry
        self.max_iterations = settings.max_iterations

        # 初始化对话历史，第一条始终是 system prompt
        self.messages: list[dict] = [
            {"role": "system", "content": SYSTEM_PROMPT}
        ]

    async def run_turn(
        self,
        user_input: str,
        confirm_callback: ConfirmCallback,
    ) -> str:
        """
        执行一轮完整的对话（可能包含多次工具调用）。

        参数：
          user_input:       用户输入的文本
          confirm_callback: 危险操作确认回调，签名 (tool_name, desc, args) → bool

        返回：
          模型的最终文本回复
        """
        # 将用户消息追加到历史
        self.messages.append({"role": "user", "content": user_input})

        # 获取所有工具定义（OpenAI 格式）
        tools = self.registry.get_openai_tools()
        iteration = 0

        # 核心循环：不断调用 LLM 直到得到文本回复或达到上限
        while iteration < self.max_iterations:
            iteration += 1

            # 调用 LLM，传入完整对话历史和工具定义
            response = await self.llm.chat(
                messages=self.messages,
                tools=tools if tools else None,
            )

            # 取第一条响应（通常只有一条）
            message = response.choices[0].message

            # === 情况1：模型直接回复文本（没有工具调用）===
            # 对话结束，返回文本
            if not message.tool_calls:
                content = message.content or ""
                self.messages.append({"role": "assistant", "content": content})
                return content

            # === 情况2：模型请求调用工具 ===

            # 先将模型的 tool_calls 请求记录到历史中
            self.messages.append(message.model_dump())

            # 遍历所有工具调用请求（模型可能一次请求多个工具）
            for tool_call in message.tool_calls:
                tool_name = tool_call.function.name
                # 解析模型传来的 JSON 参数
                arguments = json.loads(tool_call.function.arguments)

                # 从注册表查找工具
                tool = self.registry.get(tool_name)
                if tool is None:
                    result = f"Error: Unknown tool '{tool_name}'"
                else:
                    # 根据安全级别决定是否确认
                    if tool.danger_level == "dangerous":
                        # 危险工具：弹出确认框让用户决定
                        confirmed = await confirm_callback(
                            tool_name, tool.description, arguments
                        )
                        if not confirmed:
                            result = "User rejected this tool execution."
                        else:
                            result = await self._execute_tool(tool, arguments)
                    else:
                        # 安全工具：直接执行，不询问用户
                        result = await self._execute_tool(tool, arguments)

                # 将工具执行结果作为 tool message 追加到历史
                # 这样下一轮 LLM 调用就能看到工具的结果了
                self.messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": tool_call.id,
                        "content": result,
                    }
                )

        # 达到最大迭代次数，返回提示
        return "Reached maximum iteration limit. Please try a simpler request."

    async def _execute_tool(self, tool: Any, arguments: dict) -> str:
        """
        安全地执行工具。如果工具内部抛出异常，捕获并返回错误信息，
        而不是让整个对话循环崩溃。
        """
        try:
            return await tool.execute(**arguments)
        except Exception as e:
            return f"Error executing {tool.name}: {e}"

    def clear_history(self) -> None:
        """
        清空对话历史，但保留第一条 system prompt。
        相当于"重新开始对话"。
        """
        self.messages = [self.messages[0]]
