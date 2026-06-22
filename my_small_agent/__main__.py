"""Entry point for python -m my_small_agent."""

import asyncio


async def main() -> None:
    print("MySmallAgent is starting...")


def main_entry() -> None:
    """Sync entry point for pyproject.toml scripts."""
    asyncio.run(main())


if __name__ == "__main__":
    main_entry()
