MySmallAgent 采用**分层防御（Layered Defense）**的错误处理架构，核心原则是“上游失败、下游感知”与“内部捕获、降级返回”。系统未定义全局自定义异常类，而是依赖 Python 原生异常体系结合业务逻辑中的字符串化错误反馈，确保对话循环的稳定性。

### 1. 核心策略与架构
- **入口层兜底（Entry Point）**：在 `__main__.py` 中通过 `try-except` 捕获所有未处理的 `Exception`。配置加载（如 `.env` 缺失）或初始化失败会导致应用立即终止并输出红色错误提示，防止进入半初始化状态。
- **工具层内聚（Tool Layer）**：所有内置工具（如 `read_file`, `execute_shell`）在 `execute` 方法内部自行捕获异常（如 `FileNotFoundError`, `TimeoutError`），并将错误信息格式化为字符串返回。这种设计确保了工具执行失败不会中断 Agent 的核心对话循环。
- **Agent 层流程控制（Core Loop）**：
  - **未知工具处理**：当 LLM 请求不存在的工具时，Agent 返回 `"Error: Unknown tool..."` 字符串。
  - **最大迭代限制**：通过 `max_iterations` 防止模型陷入无限工具调用循环，达到上限时返回明确的限制提示。
  - **统一异常包装**：`_execute_tool` 方法对工具执行进行二次保护，捕获任何漏网之鱼并返回 `"Error executing {tool.name}: {e}"`。
- **交互层用户体验（CLI Layer）**：
  - **优雅退出**：捕获 `KeyboardInterrupt` 和 `EOFError`，确保用户通过 Ctrl+C/D 退出时显示友好的告别信息。
  - **危险操作确认**：针对 `dangerous` 级别的工具（如 Shell 执行），在执行前通过 `_confirm_dangerous_action` 拦截并请求用户显式确认，若用户拒绝则返回 `"User rejected this tool execution."`。

### 2. 关键文件与职责
| 文件路径 | 职责描述 |
| :--- | :--- |
| `my_small_agent/__main__.py` | 全局异常兜底，处理启动阶段的配置错误与运行时崩溃。 |
| `my_small_agent/agent.py` | 对话循环管理，处理未知工具、迭代超限及工具执行的二次异常捕获。 |
| `my_small_agent/cli.py` | 处理用户输入异常（EOF/中断），提供危险操作的交互式确认面板。 |
| `my_small_agent/tools/*.py` | 各工具内部实现具体的业务异常捕获（如文件权限、命令超时）。 |
| `my_small_agent/config.py` | 利用 `pydantic-settings` 在启动期进行严格的配置校验，缺失必填项直接抛出异常。 |

### 3. 开发者规范
- **禁止在工具中抛出未捕获异常**：所有 `Tool` 子类的 `execute` 方法必须包含 `try-except` 块，确保返回值为字符串而非抛出异常。
- **错误信息语义化**：返回给 LLM 的错误字符串应清晰描述原因（如 `"File not found"` 而非 generic error），以便模型能根据错误调整后续行为。
- **危险工具标记**：新开发的工具若涉及文件系统写入或系统命令执行，必须在类属性中设置 `danger_level = "dangerous"` 以触发 CLI 层的确认机制。
- **异步超时控制**：涉及 I/O 或子进程调用的工具（如 `shell_exec`）必须设置合理的 `asyncio.wait_for` 超时时间，防止资源死锁。