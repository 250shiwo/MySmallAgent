"""CLI interaction layer - handles user input/output and slash commands."""

from prompt_toolkit import PromptSession
from prompt_toolkit.patch_stdout import patch_stdout
from rich.console import Console
from rich.markdown import Markdown
from rich.panel import Panel
from rich.status import Status

from my_small_agent.agent import Agent


class CLI:
    """Terminal-based user interface for the agent."""

    def __init__(self, agent: Agent) -> None:
        self.agent = agent
        self.console = Console()
        self.session: PromptSession = PromptSession()
        self._running = True

    async def run(self) -> None:
        """Start the interactive REPL loop."""
        self._print_welcome()

        while self._running:
            try:
                with patch_stdout():
                    user_input = await self.session.prompt_async("You> ")

                user_input = user_input.strip()
                if not user_input:
                    continue

                # Check for slash commands
                if user_input.startswith("/"):
                    await self._handle_command(user_input)
                    continue

                # Run agent turn
                await self._run_agent_turn(user_input)

            except (KeyboardInterrupt, EOFError):
                self._running = False
                self.console.print("\n[dim]Goodbye![/dim]")

    async def _run_agent_turn(self, user_input: str) -> None:
        """Execute an agent turn with loading indicator."""
        with Status("[bold cyan]Thinking...", console=self.console):
            response = await self.agent.run_turn(
                user_input,
                confirm_callback=self._confirm_dangerous_action,
            )

        self.console.print()
        self.console.print(Markdown(response))
        self.console.print()

    async def _confirm_dangerous_action(
        self, tool_name: str, description: str, arguments: dict
    ) -> bool:
        """Ask user to confirm a dangerous tool execution."""
        args_display = ", ".join(f"{k}={repr(v)}" for k, v in arguments.items())
        self.console.print(
            Panel(
                f"[bold yellow]⚠️  Dangerous operation[/bold yellow]\n\n"
                f"Tool: [bold]{tool_name}[/bold]\n"
                f"Args: {args_display}",
                title="Confirmation Required",
                border_style="yellow",
            )
        )

        with patch_stdout():
            answer = await self.session.prompt_async("Allow execution? [y/N] ")

        return answer.strip().lower() in ("y", "yes")

    async def _handle_command(self, command: str) -> None:
        """Process slash commands."""
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
        """Print welcome message on startup."""
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
        """Print help information."""
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
