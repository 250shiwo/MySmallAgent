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
from dataclasses import dataclass
from datetime import datetime, timezone
from uuid import uuid4
from typing import Any, AsyncGenerator, Callable, Coroutine

from my_small_agent.config import Settings
from my_small_agent.llm import LLMClient
from my_small_agent.memory import MemoryManager
from my_small_agent.tools import ToolRegistry

# 确认回调函数的类型签名：
# 参数：(工具名称, 工具描述, 参数字典) → 返回：bool（是否允许执行）
ConfirmCallback = Callable[[str, str, dict], Coroutine[Any, Any, bool]]

# System Prompt：告诉模型它的身份和能力
SYSTEM_PROMPT = """你是一个运行在命令行终端中的通用任务助手（CLI Agent）。

你的能力：
- 文件读写和目录浏览
- 执行 Shell 命令
- 联网搜索获取实时信息
- 查询当前时间
- 搜索文件内容（grep_search）、获取网页内容（fetch_url）
- 展示目录树（tree）、按名称查找文件（find_file）
- 删除文件（file_delete）、获取系统信息（system_info）

工作原则：
- 高效完成用户任务，避免冗余解释
- 输出简洁清晰，适合终端阅读
- 避免使用复杂 Markdown（如表格、嵌套列表），终端渲染有限
- 代码块和简单列表可以使用
- 优先用中文回复，除非用户使用英文提问
- 搜索最多尝试 2 次，用已有结果回答；不要反复换关键词重试
- 如果搜索无结果或工具失败，直接告知用户并给出建议

长期记忆工具使用原则：
- 使用 memory_save 保存：用户偏好、环境细节、工具特性、稳定约定
- 不保存：任务进度、会话结果、临时状态（临时信息用 session_search 回忆）
- 优先保存能减少未来用户纠正/提醒的信息
- 使用 session_search 搜索过去的对话内容
"""


@dataclass
class AgentResponse:
    """Agent 单轮对话的返回结果。"""
    content: str           # 最终文本回复
    thinking: str = ""     # 思维链内容（thinking 关闭时为空）


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
        memory_manager: MemoryManager | None = None,
    ) -> None:
        self.llm = llm
        self.registry = registry
        self.max_iterations = settings.max_iterations
        self.settings = settings  # 保存完整 settings 供压缩功能使用

        # 运行时状态（可通过 CLI 命令动态切换）
        self.streaming_enabled: bool = getattr(settings, 'enable_streaming', True)
        self.thinking_enabled: bool = getattr(settings, 'enable_thinking', True)

        # 初始化对话历史，第一条始终是 system prompt
        self.messages: list[dict] = [
            {"role": "system", "content": SYSTEM_PROMPT}
        ]

        # 会话元数据（用于持久化）
        self.session_id: str = str(uuid4())
        self.session_title: str = ""
        self.created_at: str = datetime.now(timezone.utc).isoformat()

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
                    ),
                })

    async def run_turn(
        self,
        user_input: str,
        confirm_callback: ConfirmCallback,
    ) -> AgentResponse:
        """
        执行一轮完整的对话（非流式模式，可能包含多次工具调用）。

        参数：
          user_input:       用户输入的文本
          confirm_callback: 危险操作确认回调，签名 (tool_name, desc, args) → bool

        返回：
          AgentResponse，包含最终文本回复和可选的思维链内容
        """
        # 将用户消息追加到历史
        self.messages.append({"role": "user", "content": user_input})

        # 获取所有工具定义（OpenAI 格式）
        tools = self.registry.get_openai_tools()
        iteration = 0

        # 核心循环：不断调用 LLM 直到得到文本回复或达到上限
        while iteration < self.max_iterations:
            iteration += 1

            # 调用 LLM，传入完整对话历史和工具定义（透传 thinking 开关）
            response = await self.llm.chat(
                messages=self.messages,
                tools=tools if tools else None,
                thinking_enabled=self.thinking_enabled,
            )

            # 取第一条响应（通常只有一条）
            message = response.choices[0].message

            # === 情况1：模型直接回复文本（没有工具调用）===
            # 对话结束，返回文本（含思维链内容）
            if not message.tool_calls:
                content = message.content or ""
                thinking = getattr(message, 'reasoning_content', '') or ''
                # 保存到历史（含 thinking）
                msg_dict: dict = {"role": "assistant", "content": content}
                if thinking:
                    msg_dict["reasoning_content"] = thinking
                self.messages.append(msg_dict)
                return AgentResponse(content=content, thinking=thinking)

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
        return AgentResponse(
            content="Reached maximum iteration limit. Please try a simpler request."
        )

    async def run_turn_stream(
        self,
        user_input: str,
        confirm_callback: ConfirmCallback,
    ) -> AsyncGenerator[tuple[str, str], None]:
        """
        流式版本的对话循环。

        yield (event_type, content) 元组：
          - ("thinking", text): 思维链内容片段
          - ("content", text):  正文内容片段

        工具调用轮次仍然是“阻塞”的——stream 收完后才执行工具，
        然后开始下一轮 stream。
        """
        self.messages.append({"role": "user", "content": user_input})
        tools = self.registry.get_openai_tools()
        iteration = 0

        while iteration < self.max_iterations:
            iteration += 1

            stream = await self.llm.chat_stream(
                messages=self.messages,
                tools=tools if tools else None,
                thinking_enabled=self.thinking_enabled,
            )

            # 从 chunk 中累积完整响应
            full_content = ""
            full_thinking = ""
            tool_calls_data: list[dict] = []

            async for chunk in stream:
                delta = chunk.choices[0].delta

                # 思维内容
                reasoning = getattr(delta, 'reasoning_content', None)
                if reasoning:
                    full_thinking += reasoning
                    yield ("thinking", reasoning)

                # 正文内容
                if delta.content:
                    full_content += delta.content
                    yield ("content", delta.content)

                # 工具调用（需要拼接多个 chunk 的 delta）
                if delta.tool_calls:
                    for tc_delta in delta.tool_calls:
                        idx = tc_delta.index
                        # 扩展列表长度
                        while len(tool_calls_data) <= idx:
                            tool_calls_data.append(
                                {"id": "", "function": {"name": "", "arguments": ""}}
                            )
                        # 拼接各字段
                        if tc_delta.id:
                            tool_calls_data[idx]["id"] = tc_delta.id
                        if tc_delta.function:
                            if tc_delta.function.name:
                                tool_calls_data[idx]["function"]["name"] += tc_delta.function.name
                            if tc_delta.function.arguments:
                                tool_calls_data[idx]["function"]["arguments"] += tc_delta.function.arguments

            # 流结束：判断是否有工具调用
            if not tool_calls_data:
                # 纯文本回复 → 保存到历史，结束
                msg_dict: dict = {"role": "assistant", "content": full_content}
                if full_thinking:
                    msg_dict["reasoning_content"] = full_thinking
                self.messages.append(msg_dict)
                return

            # 有工具调用 → 保存 assistant 消息（含 tool_calls）
            assistant_msg: dict = {
                "role": "assistant",
                "content": full_content or None,
                "tool_calls": [
                    {
                        "id": tc["id"],
                        "type": "function",
                        "function": tc["function"],
                    }
                    for tc in tool_calls_data
                ],
            }
            if full_thinking:
                assistant_msg["reasoning_content"] = full_thinking
            self.messages.append(assistant_msg)

            # 执行每个工具调用
            for tc in tool_calls_data:
                tool_name = tc["function"]["name"]
                arguments = json.loads(tc["function"]["arguments"])

                tool = self.registry.get(tool_name)
                if tool is None:
                    result = f"Error: Unknown tool '{tool_name}'"
                else:
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

                self.messages.append(
                    {"role": "tool", "tool_call_id": tc["id"], "content": result}
                )

        # 达到最大迭代次数
        yield ("content", "\nReached maximum iteration limit.")

    async def _execute_tool(self, tool: Any, arguments: dict) -> str:
        """
        安全地执行工具。如果工具内部抛出异常，捕获并返回错误信息，
        而不是让整个对话循环崩溃。
        """
        try:
            return await tool.execute(**arguments)
        except Exception as e:
            return f"Error executing {tool.name}: {e}"

    def strip_thinking_from_history(self) -> None:
        """
        从历史中剔除 reasoning_content 字段，节省 token 开销。
        在用户关闭 thinking 模式时调用。
        """
        for msg in self.messages:
            if msg.get("role") == "assistant" and "reasoning_content" in msg:
                del msg["reasoning_content"]

    def reset_session(
        self,
        messages: list[dict] | None = None,
        session_id: str | None = None,
        title: str = "",
        created_at: str | None = None,
    ) -> None:
        """
        重置会话状态，用于 /new 和 /resume 命令。

        保留所有 role=system 的消息（包含 SYSTEM_PROMPT 和记忆注入消息）。
        不传 session_id 时自动生成新 UUID。
        """
        # 保留所有 system 消息（含记忆注入消息），清空其余
        system_msgs = [m for m in self.messages if m.get("role") == "system"]
        self.messages = system_msgs
        if messages:
            self.messages.extend(messages)
        self.session_id = session_id or str(uuid4())
        self.session_title = title
        self.created_at = created_at or datetime.now(timezone.utc).isoformat()

    def clear_history(self) -> None:
        """
        清空对话历史，保留 system prompt，并生成新的 session_id。
        相当于 /new 命令。
        """
        self.reset_session()

    def estimate_tokens(self) -> int:
        """
        估算当前对话历史的 token 用量（chars / 4 算法）。

        遍历所有 message 的每个字段：
          - 字符串值直接计长度
          - 列表/字典值序列化为 JSON 后计长度
        """
        total_chars = 0
        for msg in self.messages:
            for value in msg.values():
                if isinstance(value, str):
                    total_chars += len(value)
                elif isinstance(value, (dict, list)):
                    total_chars += len(json.dumps(value, ensure_ascii=False))
        return total_chars // 4

    async def compact_context(self) -> tuple[int, int]:
        """
        压缩对话历史，用 LLM 生成的摘要替换中间消息。

        算法：
          保留 messages[:head] + [摘要消息] + messages[tail_start:]
          head 和 tail_start 会自动调整以避免切断 tool_call 序列。

        返回：(压缩前消息数, 压缩后消息数)
        """
        total = len(self.messages)
        head = self.settings.head_keep
        tail = self.settings.tail_keep

        # 调整 head 边界：不以含 tool_calls 的 assistant 消息结尾
        # （否则对应的 tool 响应会在中间被压缩掉，导致 tool_calls 无响应）
        while head > 0 and self.messages[head - 1].get("tool_calls"):
            head -= 1

        # 调整 tail 边界：不以 tool 消息开头
        # （否则对应的 assistant(tool_calls) 在中间被压缩掉，导致 tool 消息孤立）
        tail_start = total - tail
        while tail_start < total and self.messages[tail_start].get("role") == "tool":
            tail_start += 1

        head_msgs = self.messages[:head]
        middle = self.messages[head:tail_start]
        tail_msgs = self.messages[tail_start:]

        # 将中间消息序列化为文本供 LLM 压缩
        middle_text = "\n\n".join(
            f"[{m.get('role', 'unknown')}]: "
            + (m.get("content") or json.dumps(m.get("tool_calls", ""), ensure_ascii=False))
            for m in middle
        )

        summary_prompt = (
            "请将以下对话历史压缩为简洁摘要，严格使用以下格式：\n\n"
            "## Goal           — 用户目标（1-2 句）\n"
            "## Key Actions    — 已执行的操作列表\n"
            "## Current State  — 当前进展\n"
            "## Decisions      — 重要技术决策\n"
            "## Technical Details — 需要精确保留的值\n"
            "## User Preferences — 用户表达的偏好\n\n"
            "对话内容：\n"
            f"{middle_text}"
        )

        response = await self.llm.chat(
            messages=[{"role": "user", "content": summary_prompt}],
            tools=None,
            thinking_enabled=False,
        )
        summary = response.choices[0].message.content or "(摘要生成失败)"

        before_count = total
        summary_msg = {
            "role": "assistant",
            "content": f"[压缩历史摘要]\n\n{summary}",
        }
        self.messages = head_msgs + [summary_msg] + tail_msgs
        after_count = len(self.messages)

        return before_count, after_count
