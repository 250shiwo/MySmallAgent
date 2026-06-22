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
      - 解析斜杠命令（/help, /clear, /exit）
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
        """
        执行一轮 Agent 对话，并显示加载动画。

        流程：显示 "Thinking..." → 调用 Agent → 用 Markdown 渲染回复
        """
        # Status: rich 的加载动画，在等待 LLM 时显示旋转图标
        with Status("[bold cyan]Thinking...", console=self.console):
            response = await self.agent.run_turn(
                user_input,
                confirm_callback=self._confirm_dangerous_action,
            )

        # 用 rich 的 Markdown 渲染模型回复（支持代码高亮、列表等）
        self.console.print()
        self.console.print(Markdown(response))
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
          /help  → 显示帮助信息
          /clear → 清空对话历史
          /exit  → 退出程序
        """
        # 取命令的第一部分（忽略参数）并转小写
        cmd = command.lower().split()[0]

        if cmd == "/help":
            self._print_help()
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

    def _print_welcome(self) -> None:
        """启动时显示欢迎面板，介绍可用命令。"""
        self.console.print(
            Panel(
                "[bold]MySmallAgent[/bold] - Your CLI assistant\n\n"
                "Type your message to chat, or use commands:\n"
                "  /help  - Show help\n"
                "  /clear - Clear history\n"
                "  /exit  - Exit",
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
                "  [cyan]/clear[/cyan]  - Clear conversation history\n"
                "  [cyan]/exit[/cyan]   - Exit the program\n\n"
                "[bold]Tips:[/bold]\n"
                "  • Press Ctrl+C or Ctrl+D to exit\n"
                "  • The agent can read/write files, list directories, and run shell commands",
                title="Help",
                border_style="green",
            )
        )
