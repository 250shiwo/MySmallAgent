"""
程序入口 - 运行 `python -m my_small_agent` 或 `agent` 命令时执行此文件。

启动流程：
  1. 加载 .env 配置
  2. 创建 LLM 客户端
  3. 注册所有内置工具
  4. 创建 Agent 实例
  5. 创建 CLI 交互层
  6. 启动 REPL 循环
"""

import asyncio
import sys

from rich.console import Console


async def main() -> None:
    """
    异步主函数 - 初始化所有组件并启动 CLI。

    组件初始化顺序（后者依赖前者）：
      Settings → LLMClient → ToolRegistry → Agent → CLI
    """
    console = Console()

    try:
        # 延迟导入：在函数内导入，避免启动前不必要的模块加载
        from my_small_agent.config import Settings         # 配置管理
        from my_small_agent.llm import LLMClient           # LLM 客户端
        from my_small_agent.tools import create_default_registry  # 工具注册表
        from my_small_agent.agent import Agent             # 对话循环
        from my_small_agent.cli import CLI                 # 终端交互

        # 1. 加载配置（从 .env 文件和环境变量）
        settings = Settings()

        # 2. 创建 LLM 客户端（连接 OpenAI API）
        llm_client = LLMClient(settings)

        # 3. 创建工具注册表（注册 read_file, write_file, list_directory, execute_shell, web_search, current_time）
        registry = create_default_registry(settings)

        # 4. 创建 Agent（组装 LLM + 工具 + 配置）
        agent = Agent(llm_client, registry, settings)

        # 5. 创建 CLI 并启动交互循环
        cli = CLI(agent)
        await cli.run()

    except KeyboardInterrupt:
        # 用户按 Ctrl+C 时优雅退出
        console.print("\n[dim]Goodbye![/dim]")
    except Exception as e:
        # 启动失败（通常是 .env 配置缺失）
        console.print(f"[red]Failed to start: {e}[/red]")
        console.print("[dim]Make sure your .env file is configured correctly.[/dim]")
        sys.exit(1)


def main_entry() -> None:
    """
    同步入口点 - 供 pyproject.toml 的 [project.scripts] 使用。

    在 pyproject.toml 中配置了：
      [project.scripts]
      agent = "my_small_agent.__main__:main_entry"

    所以安装后可以运行 `agent` 命令启动程序。
    asyncio.run() 将异步的 main() 包装为同步调用。
    """
    asyncio.run(main())


# 当直接运行 `python -m my_small_agent` 时执行
if __name__ == "__main__":
    main_entry()
