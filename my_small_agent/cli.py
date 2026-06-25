"""
CLI 交互层 - 处理终端的用户输入输出和斜杠命令。

使用的库：
  - prompt_toolkit: 提供增强型终端输入（支持历史记录、多行输入）
  - rich:           美化输出（Markdown 渲染、颜色面板、加载动画）

交互流程：
  1. 显示欢迎面板
  2. 等待用户输入
  3. 以 "/" 开头 → 解析为命令（/help, /clear, /exit）
  4. 普通文本 → 传给 Agent 处理对话
  5. 重复步骤 2-4
"""

from prompt_toolkit import PromptSession
from prompt_toolkit.patch_stdout import patch_stdout
from rich.console import Console
from rich.markdown import Markdown
from rich.panel import Panel
from rich.status import Status

from my_small_agent.agent import Agent


class CLI:
    """
    终端用户界面 - 用户通过命令行与 Agent 交互。

    职责：
      - 读取用户输入（prompt_toolkit）
      - 解析斜杠命令（/help, /tools, /clear, /exit）
      - 将自然语言转发给 Agent
      - 美化显示 Agent 的回复（rich）
    """

    def __init__(self, agent: Agent) -> None:
        self.agent = agent
        self.console = Console()            # rich 的控制台，负责美化输出
        self.session: PromptSession = PromptSession()  # prompt_toolkit 的输入会话
        self._running = True                # REPL 循环的控制标志

    async def run(self) -> None:
        """
        启动 REPL（读取-求值-打印）主循环。

        循环直到用户输入 /exit 或按 Ctrl+C/Ctrl+D。
        """
        self._print_welcome()

        while self._running:
            try:
                # patch_stdout: 防止 rich 输出和 prompt 输入互相干扰
                with patch_stdout():
                    user_input = await self.session.prompt_async("You> ")

                user_input = user_input.strip()
                if not user_input:
                    continue

                # 以 "/" 开头 → 斜杠命令
                if user_input.startswith("/"):
                    await self._handle_command(user_input)
                    continue

                # 普通文本 → 交给 Agent 对话循环
                await self._run_agent_turn(user_input)

            except (KeyboardInterrupt, EOFError):
                # Ctrl+C 或 Ctrl+D 优雅退出
                self._running = False
                self.console.print("\n[dim]Goodbye![/dim]")

    async def _run_agent_turn(self, user_input: str) -> None:
        """根据 streaming 状态选择流式或非流式对话。"""
        if self.agent.streaming_enabled:
            await self._run_agent_turn_stream(user_input)
        else:
            await self._run_agent_turn_normal(user_input)

    async def _run_agent_turn_normal(self, user_input: str) -> None:
        """非流式模式：等待完整响应后渲染。"""
        # Status: rich 的加载动画，在等待 LLM 时显示旋转图标
        with Status("[bold cyan]Thinking...", console=self.console):
            response = await self.agent.run_turn(
                user_input,
                confirm_callback=self._confirm_dangerous_action,
            )

        self.console.print()
        # 如果有 thinking 内容，先展示
        if response.thinking:
            self.console.print(f"[dim]💭 {response.thinking}[/dim]")
            self.console.print()
        # 用 rich 的 Markdown 渲染模型回复（支持代码高亮、列表等）
        self.console.print(Markdown(response.content))
        self.console.print()

    async def _run_agent_turn_stream(self, user_input: str) -> None:
        """流式模式：逐 chunk 打印到终端。"""
        self.console.print()
        in_thinking = False

        async for event_type, content in self.agent.run_turn_stream(
            user_input, self._confirm_dangerous_action
        ):
            if event_type == "thinking":
                if not in_thinking:
                    self.console.print("[dim]💭 ", end="")
                    in_thinking = True
                self.console.print(f"[dim]{content}[/dim]", end="")

            elif event_type == "content":
                if in_thinking:
                    self.console.print()  # 结束 thinking 行
                    self.console.print()
                    in_thinking = False
                self.console.print(content, end="")

        # 结尾换行
        if in_thinking:
            self.console.print()
        self.console.print()
        self.console.print()

    async def _confirm_dangerous_action(
        self, tool_name: str, description: str, arguments: dict
    ) -> bool:
        """
        危险操作确认回调。

        当 Agent 要执行 danger_level="dangerous" 的工具时，
        CLI 会弹出黄色面板展示操作详情，等用户输入 y/N 确认。
        """
        # 格式化参数展示：command='rm -rf /tmp'
        args_display = ", ".join(f"{k}={repr(v)}" for k, v in arguments.items())

        # 用 rich 的 Panel 显示黄色警告面板
        self.console.print(
            Panel(
                f"[bold yellow]⚠️  Dangerous operation[/bold yellow]\n\n"
                f"Tool: [bold]{tool_name}[/bold]\n"
                f"Args: {args_display}",
                title="Confirmation Required",
                border_style="yellow",
            )
        )

        # 读取用户确认
        with patch_stdout():
            answer = await self.session.prompt_async("Allow execution? [y/N] ")

        # 只有输入 y 或 yes 才允许执行
        return answer.strip().lower() in ("y", "yes")

    async def _handle_command(self, command: str) -> None:
        """
        解析并执行斜杠命令。

        支持的命令：
          /help   → 显示帮助信息
          /tools  → 列出所有已注册工具
          /stream → 切换流式输出
          /think  → 切换思维链模式
          /status → 显示当前设置
          /clear  → 清空对话历史
          /exit   → 退出程序
        """
        # 取命令的第一部分（忽略参数）并转小写
        cmd = command.lower().split()[0]

        if cmd == "/help":
            self._print_help()
        elif cmd == "/tools":
            self._print_tools()
        elif cmd == "/stream":
            self._toggle_stream()
        elif cmd == "/think":
            self._toggle_think()
        elif cmd == "/status":
            self._print_status()
        elif cmd == "/clear":
            self.agent.clear_history()
            self.console.print("[green]Conversation history cleared.[/green]")
        elif cmd == "/exit":
            self._running = False
            self.console.print("[dim]Goodbye![/dim]")
        else:
            self.console.print(
                f"[red]Unknown command: {cmd}[/red]. Type /help for available commands."
            )

    def _toggle_stream(self) -> None:
        """切换流式输出开关。"""
        self.agent.streaming_enabled = not self.agent.streaming_enabled
        state = "开启" if self.agent.streaming_enabled else "关闭"
        self.console.print(f"[cyan]流式输出已{state}[/cyan]")

    def _toggle_think(self) -> None:
        """切换思维链模式开关。"""
        self.agent.thinking_enabled = not self.agent.thinking_enabled
        state = "开启" if self.agent.thinking_enabled else "关闭"
        if not self.agent.thinking_enabled:
            self.agent.strip_thinking_from_history()
        self.console.print(f"[cyan]思维链模式已{state}[/cyan]")

    def _print_status(self) -> None:
        """显示当前 Agent 状态。"""
        streaming = "[green]开启[/green]" if self.agent.streaming_enabled else "[red]关闭[/red]"
        thinking = "[green]开启[/green]" if self.agent.thinking_enabled else "[red]关闭[/red]"
        self.console.print(
            Panel(
                f"  模型:     [bold]{self.agent.llm.model}[/bold]\n"
                f"  流式输出: {streaming}\n"
                f"  思维链:   {thinking}",
                title="当前状态",
                border_style="cyan",
            )
        )

    def _print_welcome(self) -> None:
        """启动时显示欢迎面板，介绍可用命令。"""
        self.console.print(
            Panel(
                "[bold]MySmallAgent[/bold] - Your CLI assistant\n\n"
                "Type your message to chat, or use commands:\n"
                "  /help   - Show help\n"
                "  /tools  - List available tools\n"
                "  /stream - Toggle streaming output\n"
                "  /think  - Toggle thinking mode\n"
                "  /status - Show current settings\n"
                "  /clear  - Clear history\n"
                "  /exit   - Exit",
                title="Welcome",
                border_style="blue",
            )
        )
        self.console.print()

    def _print_help(self) -> None:
        """显示帮助信息面板。"""
        self.console.print(
            Panel(
                "[bold]Available Commands:[/bold]\n\n"
                "  [cyan]/help[/cyan]   - Show this help message\n"
                "  [cyan]/tools[/cyan]  - List all registered tools\n"
                "  [cyan]/stream[/cyan] - Toggle streaming output\n"
                "  [cyan]/think[/cyan]  - Toggle thinking mode\n"
                "  [cyan]/status[/cyan] - Show current settings\n"
                "  [cyan]/clear[/cyan]  - Clear conversation history\n"
                "  [cyan]/exit[/cyan]   - Exit the program\n\n"
                "[bold]Tips:[/bold]\n"
                "  • Press Ctrl+C or Ctrl+D to exit\n"
                "  • The agent can read/write files, search the web, and run shell commands",
                title="Help",
                border_style="green",
            )
        )

    def _print_tools(self) -> None:
        """列出所有已注册的工具，展示名称、描述和安全级别。"""
        tools = self.agent.registry.list_all()
        if not tools:
            self.console.print("[yellow]No tools registered.[/yellow]")
            return

        lines = []
        for tool in tools:
            # 安全级别用不同颜色标记：safe=绿色，dangerous=黄色
            level_color = "green" if tool.danger_level == "safe" else "yellow"
            level_label = "safe" if tool.danger_level == "safe" else "dangerous"
            lines.append(
                f"  [bold]{tool.name}[/bold]  "
                f"[{level_color}][{level_label}][/{level_color}]\n"
                f"    [dim]{tool.description}[/dim]"
            )

        self.console.print(
            Panel(
                "\n\n".join(lines),
                title=f"Registered Tools ({len(tools)})",
                border_style="cyan",
            )
        )
