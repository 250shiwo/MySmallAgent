# MySmallAgent

一个慢慢完善的 Agent，会随着市面上技术的更新随之更新，可当做 demo。

## 当前功能

- **LLM 对话** — 基于 OpenAI tool_calls 原生流程，兼容所有 OpenAI API 格式的服务（DeepSeek、本地模型等）
- **工具调用** — 中心化注册表，内置 4 个工具：
  - `read_file` — 读取文件内容
  - `write_file` — 写入文件
  - `list_directory` — 列出目录
  - `execute_shell` — 执行 shell 命令
- **安全分级** — 只读工具自动执行，写入/命令类工具需用户确认
- **CLI 交互** — prompt_toolkit 输入 + rich 美化输出（Markdown 渲染、加载动画）

## 快速开始

### 环境要求

- Python >= 3.11
- [uv](https://docs.astral.sh/uv/)（推荐的包管理器）

### 安装

```bash
# 克隆项目
git clone <repo-url>
cd MySmallAgent

# 安装依赖
uv sync
```

### 配置

复制 `.env.example` 并填入你的 API 密钥：

```bash
cp .env.example .env
```

编辑 `.env`：

```env
OPENAI_API_KEY=sk-your-key-here
OPENAI_BASE_URL=https://api.openai.com/v1
OPENAI_MODEL=gpt-4o
MAX_ITERATIONS=10
```

如果使用 DeepSeek 等兼容 API，修改 `OPENAI_BASE_URL` 和 `OPENAI_MODEL` 即可。

### 启动

```bash
uv run python -m my_small_agent
```

## CLI 命令

| 命令 | 说明 |
|------|------|
| `/help` | 显示帮助信息 |
| `/tools` | 列出所有已注册工具 |
| `/clear` | 清空对话历史 |
| `/exit` | 退出程序 |

也可以按 `Ctrl+C` 或 `Ctrl+D` 退出。

## 项目结构

```
my_small_agent/
├── __main__.py     # 入口
├── config.py       # 配置管理（pydantic-settings）
├── agent.py        # 对话循环核心
├── llm.py          # OpenAI 异步客户端
├── cli.py          # CLI 交互层
└── tools/
    ├── __init__.py # 工具注册表
    ├── base.py     # 工具基类
    ├── file_read.py
    ├── file_write.py
    ├── list_dir.py
    └── shell_exec.py
```

## 开发

```bash
# 运行测试
uv run pytest -v
```

## 技术栈

| 组件 | 选择 |
|------|------|
| LLM 调用 | `openai`（异步） |
| 对话范式 | OpenAI tool_calls 原生流程 |
| 配置管理 | `pydantic-settings` |
| 终端输入 | `prompt_toolkit` |
| 终端输出 | `rich` |
| 依赖管理 | `uv` + `pyproject.toml` |

