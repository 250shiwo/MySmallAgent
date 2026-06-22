# MySmallAgent 核心设计文档

> 本次迭代范围：对话循环 + 工具调用 + CLI 交互

## 概述

MySmallAgent 是一个基于 OpenAI tool_calls 原生流程的 CLI Agent。本次实现三个核心功能：
1. 与 LLM 对话（异步，OpenAI 兼容 API）
2. 工具调用（中心化注册表 + 4 个内置工具）
3. 终端交互（prompt_toolkit + rich 美化）

## 技术选型

| 维度 | 选择 | 理由 |
|------|------|------|
| LLM 调用 | `openai` 库（异步） | 原生支持 tool_calls，兼容所有 OpenAI API 格式的服务 |
| 对话范式 | OpenAI tool_calls 原生流程 | 比 prompt 级 ReAct 更稳定，模型原生支持 |
| 配置管理 | `pydantic-settings` | 类型安全，自动读取 .env |
| 终端输入 | `prompt_toolkit` | 多行输入、历史记录、快捷键 |
| 终端输出 | `rich` | Markdown 渲染、代码高亮、spinner |
| 依赖管理 | `pyproject.toml` + `uv` | 现代 Python 标准 |
| 异步模式 | asyncio | 为未来扩展打基础 |

## 项目结构

```
MySmallAgent/
├── pyproject.toml
├── .env                    # (git ignored) 存放密钥
├── .env.example            # 模板供参考
├── README.md
├── .gitignore
└── my_small_agent/
    ├── __init__.py
    ├── __main__.py         # python -m my_small_agent 入口
    ├── config.py           # 配置加载
    ├── agent.py            # 对话循环核心
    ├── llm.py              # OpenAI 异步客户端封装
    ├── cli.py              # CLI 交互层
    └── tools/
        ├── __init__.py     # ToolRegistry 中心化注册表
        ├── base.py         # Tool 抽象基类
        ├── file_read.py    # 读取文件工具
        ├── file_write.py   # 写入文件工具
        ├── list_dir.py     # 列出目录工具
        └── shell_exec.py   # 执行 shell 命令工具
```

## 模块设计

### 1. 配置管理 (`config.py`)

使用 `pydantic-settings` 的 `BaseSettings` 从 `.env` 加载配置：

```python
class Settings(BaseSettings):
    openai_api_key: str
    openai_base_url: str = "https://api.openai.com/v1"
    openai_model: str = "gpt-4o"
    max_iterations: int = 10

    model_config = SettingsConfigDict(env_file=".env")
```

### 2. LLM 客户端 (`llm.py`)

封装 `AsyncOpenAI` 客户端，提供统一调用接口：

```python
class LLMClient:
    def __init__(self, settings: Settings):
        self.client = AsyncOpenAI(
            api_key=settings.openai_api_key,
            base_url=settings.openai_base_url,
        )
        self.model = settings.openai_model

    async def chat(self, messages: list[dict], tools: list[dict] | None = None) -> ChatCompletion:
        """调用 LLM，返回完整响应"""
```

### 3. 工具系统 (`tools/`)

#### 基类 (`tools/base.py`)

```python
class Tool(ABC):
    name: str                # 工具唯一标识
    description: str         # LLM 可见的工具描述
    parameters: dict         # JSON Schema 格式参数定义
    danger_level: str        # "safe" | "dangerous"

    @abstractmethod
    async def execute(self, **kwargs) -> str:
        """执行工具逻辑，返回字符串结果"""
```

#### 注册表 (`tools/__init__.py`)

```python
class ToolRegistry:
    _tools: dict[str, Tool]

    def register(self, tool: Tool) -> None
    def get(self, name: str) -> Tool | None
    def get_openai_tools(self) -> list[dict]   # 转为 OpenAI tools 参数格式
    def list_all(self) -> list[Tool]
```

所有内置工具在模块加载时自动注册到全局 registry 实例。

#### 内置工具

| 工具名 | danger_level | 参数 | 行为 |
|--------|-------------|------|------|
| `read_file` | safe | `path: str` | 读取文件内容，返回文本 |
| `write_file` | dangerous | `path: str, content: str` | 将内容写入文件 |
| `list_directory` | safe | `path: str` | 列出目录中的文件和子目录 |
| `execute_shell` | dangerous | `command: str` | 执行 shell 命令，返回 stdout + stderr |

### 4. 对话循环 (`agent.py`)

核心循环流程：

```
1. 接收用户输入，追加为 user message
2. 调用 LLM（附带工具定义）
3. 检查响应:
   a. 纯文本回复 → 返回给 CLI 展示，循环结束
   b. tool_calls → 进入工具执行:
      - 遍历每个 tool_call
      - 检查 danger_level
        - safe → 直接执行
        - dangerous → 通过 CLI 询问用户确认
          - 确认 → 执行
          - 拒绝 → 返回 "用户拒绝执行" 作为工具结果
      - 执行结果作为 role=tool 消息追加到历史
      - 回到步骤 2
4. 迭代次数超过 max_iterations → 强制停止，提示用户
```

关键行为：
- 支持单轮多 tool_calls（模型可能同时请求调用多个工具）
- 异步执行，`await` 所有 I/O 操作
- 对话历史维护在内存 `list[dict]` 中
- `/clear` 命令清空历史时保留 system prompt

### 5. CLI 交互层 (`cli.py`)

#### 输入处理

```
用户输入
  ├─ 以 "/" 开头 → 解析为斜杠命令
  │   ├─ /help  → 打印帮助信息
  │   ├─ /clear → 清空对话历史
  │   └─ /exit  → 退出程序
  └─ 其他 → 传递给 agent 对话循环
```

#### 输出展示

- **模型回复**：使用 `rich` 渲染 Markdown
- **工具调用**：`[🔧 tool_name] param=value`
- **工具结果**：折叠/缩进展示
- **危险确认**：`⚠️ 即将执行: tool_name(params) [y/N]`
- **加载状态**：spinner 动画表示等待 LLM 响应

#### 退出方式

- `/exit` 命令
- `Ctrl+C` / `Ctrl+D` 均优雅退出

### 6. 入口 (`__main__.py`)

```python
async def main():
    settings = Settings()
    llm_client = LLMClient(settings)
    registry = create_default_registry()  # 注册所有内置工具
    agent = Agent(llm_client, registry, settings)
    cli = CLI(agent)
    await cli.run()

if __name__ == "__main__":
    asyncio.run(main())
```

## 配置文件

### `.env.example`

```env
OPENAI_API_KEY=sk-your-key-here
OPENAI_BASE_URL=https://api.openai.com/v1
OPENAI_MODEL=gpt-4o
MAX_ITERATIONS=10
```

### `pyproject.toml` 关键配置

```toml
[project]
name = "my-small-agent"
version = "0.1.0"
requires-python = ">=3.11"
dependencies = [
    "openai>=1.0",
    "pydantic-settings>=2.0",
    "prompt-toolkit>=3.0",
    "rich>=13.0",
]

[project.scripts]
agent = "my_small_agent.__main__:main_entry"
```

## 错误处理

- API 调用失败：捕获异常，向用户展示错误信息，不中断对话循环
- 工具执行失败：捕获异常，将错误信息作为工具结果返回给 LLM
- 配置缺失：启动时检查必需配置，缺失则提示并退出
- 文件/目录不存在：工具内部处理，返回友好错误信息

## 未来扩展方向（不在本次范围）

- FastAPI Web 接口
- 对话持久化
- 流式输出
- 更多工具（网络请求、代码执行沙箱等）
- System Prompt 自定义
- 多模型切换
