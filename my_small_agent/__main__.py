"""Entry point for python -m my_small_agent."""

import asyncio
import sys

from rich.console import Console


async def main() -> None:
    """Initialize and run the agent CLI."""
    console = Console()

    try:
        from my_small_agent.config import Settings
        from my_small_agent.llm import LLMClient
        from my_small_agent.tools import create_default_registry
        from my_small_agent.agent import Agent
        from my_small_agent.cli import CLI

        settings = Settings()
        llm_client = LLMClient(settings)
        registry = create_default_registry()
        agent = Agent(llm_client, registry, settings)
        cli = CLI(agent)
        await cli.run()

    except KeyboardInterrupt:
        console.print("\n[dim]Goodbye![/dim]")
    except Exception as e:
        console.print(f"[red]Failed to start: {e}[/red]")
        console.print("[dim]Make sure your .env file is configured correctly.[/dim]")
        sys.exit(1)


def main_entry() -> None:
    """Sync entry point for pyproject.toml scripts."""
    asyncio.run(main())


if __name__ == "__main__":
    main_entry()
"""Entry point for python -m my_small_agent."""

import asyncio


async def main() -> None:
    print("MySmallAgent is starting...")


def main_entry() -> None:
    """Sync entry point for pyproject.toml scripts."""
    asyncio.run(main())


if __name__ == "__main__":
    main_entry()
