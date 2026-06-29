## 1. 系统概述
该仓库**未集成**传统的结构化日志系统（如 Python 标准库 `logging`、`loguru` 或 `structlog`）。应用程序的运行状态、错误信息和用户交互反馈完全通过 **Rich** 库直接输出到标准控制台（stdout/stderr）。

这种设计使得应用表现为一个纯粹的交互式 CLI 工具，其“日志”即为用户可见的终端界面内容，缺乏后台静默记录、日志分级过滤或持久化存储能力。

## 2. 核心实现方式
- **UI/反馈框架**：使用 `rich.console.Console` 进行所有文本输出。
- **错误处理**：在入口点 (`__main__.py`) 和工具执行层 (`agent.py`, `tools/*.py`) 使用 `try-except` 捕获异常，并通过 `console.print` 以红色标记输出错误摘要。
- **调试/追踪**：缺乏专门的调试日志。开发者若需追踪内部逻辑（如 LLM 请求参数、工具调用细节），目前只能依赖代码中的断点或临时添加 `print` 语句。

## 3. 关键文件与模式
- **`my_small_agent/__main__.py`**：全局异常捕获入口。启动失败时输出 `[red]Failed to start: {e}[/red]`。
- **`my_small_agent/cli.py`**：交互层。使用 `rich.panel.Panel` 和 `rich.status.Status` 展示加载状态、警告确认和帮助信息。
- **`my_small_agent/agent.py`**：核心逻辑。工具执行出错时返回字符串形式的错误信息（如 `"Error executing {tool.name}: {e}"`），而非抛出异常或记录日志。
- **`my_small_agent/tools/shell_exec.py`**：工具层。命令超时或执行失败时，将错误信息作为工具输出的一部分返回给 LLM。

## 4. 开发者规范与建议
- **当前约定**：
  - 禁止使用 `print()`，统一使用 `self.console.print()` 以确保格式一致。
  - 错误信息应简洁明了，直接面向最终用户，而非面向开发者调试。
- **潜在改进**：
  - 若需增加可观测性，建议引入 `logging` 模块并配置 `RichHandler`，以便在保留美观终端输出的同时，支持按级别（DEBUG/INFO/ERROR）过滤和文件持久化。
  - 敏感信息（如 API Key）严禁通过任何形式输出到控制台或日志中。