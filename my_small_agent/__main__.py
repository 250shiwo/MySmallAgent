"""
程序入口 - 运行 `python -m my_small_agent` 或 `agent` 命令时执行此文件。

启动流程：
  1. 加载 .env 配置
  2. 创建 LLM 客户端
  3. 创建长期记忆管理器
  4. 注册所有内置工具
  5. 创建 Agent 实例
  6. 创建 CLI 交互层
  7. 启动 REPL 循环
"""

import asyncio
import sys

from rich.console import Console


async def main() -> None:
    """
    异步主函数 - 初始化所有组件并启动 CLI。

    组件初始化顺序（后者依赖前者）：
      Settings → LLMClient → MemoryManager → ToolRegistry → Agent → CLI
    """
    console = Console()

    try:
        # 延迟导入：在函数内导入，避免启动前不必要的模块加载
        from pathlib import Path
        from my_small_agent.config import Settings         # 配置管理
        from my_small_agent.llm import LLMClient           # LLM 客户端
        from my_small_agent.tools import create_default_registry  # 工具注册表
        from my_small_agent.agent import Agent             # 对话循环
        from my_small_agent.session import SessionManager   # 会话持久化
        from my_small_agent.memory import MemoryManager        # 长期记忆
        from my_small_agent.cli import CLI                 # 终端交互
        from my_small_agent.skills import discover_skills, skill_registry, build_skills_index, register_skill_tools
        from my_small_agent.prompt import PromptManager
        from my_small_agent.tools.research_topic import ResearchTopicTool

        # 1. 加载配置（从 .env 文件和环境变量）
        settings = Settings()

        # 2. 创建 LLM 客户端（连接 OpenAI API）
        llm_client = LLMClient(settings)

        # 3. 创建长期记忆管理器（加载 .genesis/memory/memory.json）
        memory_manager = MemoryManager(Path(".genesis") / "memory")

        # 4. 创建工具注册表（含 memory_save 和 session_search）
        registry = create_default_registry(
            settings,
            memory_manager=memory_manager,
            sessions_dir=Path(".genesis") / "sessions",
        )

        # 4.5 发现并注册所有技能
        discover_skills()

        # 4.6 注册 skill 工具 + 组合工具到 ToolRegistry
        register_skill_tools(registry, skill_registry)
        registry.register(ResearchTopicTool(registry))

        # 4.7 初始化 PromptManager（加载基础提示词 + 拼接技能索引）
        prompt_manager = PromptManager()
        prompt_manager.update_skills_index(build_skills_index())

        # 5. 创建 Agent（组装 LLM + 工具 + 配置 + 长期记忆 + 提示词管理）
        agent = Agent(llm_client, registry, settings, memory_manager=memory_manager, prompt_manager=prompt_manager)
        agent._skill_registry = skill_registry

        # 6. 创建会话管理器（保存到 .genesis/sessions/）
        session_manager = SessionManager(Path(".genesis") / "sessions")

        # 7. 创建 CLI 并启动交互循环
        cli = CLI(agent, session_manager)
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
