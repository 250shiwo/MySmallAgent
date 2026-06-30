# MySmallAgent

一个慢慢完善的 Agent，会随着市面上技术的更新随之更新，可当做 demo。

## 当前功能

- **LLM 对话** — 基于 OpenAI tool_calls 原生流程，兼容所有 OpenAI API 格式的服务（DeepSeek、本地模型等）
- **流式输出** — 实时逐字显示 LLM 回复，降低等待延迟
- **思维链模式** — 接入 DeepSeek Thinking 能力，提升推理质量，思维内容可折叠/展开
- **工具调用** — 中心化注册表，内置 12 个工具：
  - `read_file` — 读取文件内容
  - `write_file` — 写入文件
  - `list_directory` — 列出目录
  - `execute_shell` — 执行 shell 命令
  - `web_search` — DuckDuckGo 网页搜索
  - `current_time` — 查询当前时间（支持时区配置）
  - `grep_search` — 递归搜索文件内容（正则/关键词）
  - `fetch_url` — 获取网页内容并提取纯文本
  - `tree` — 递归展示目录树结构
  - `find_file` — 按 glob 模式递归搜索文件
  - `file_delete` — 删除文件（需确认）
  - `system_info` — 获取系统运行环境信息
- **安全分级** — 只读工具自动执行，写入/删除类工具需用户确认
- **Token 估算** — chars/4 算法实时估算上下文消耗，`/status` 展示用量进度
- **上下文压缩** — 接近上限时自动触发 LLM 摘要压缩，也可 `/compact` 手动触发
- **长期记忆** — `memory_save` 持久化用户偏好，`session_search` 搜索历史会话
- **会话持久化** — `/resume` 恢复历史会话，`/sessions` 列出所有会话
- **CLI 交互** — prompt_toolkit 输入 + rich 美化输出（Markdown 渲染、加载动画、流式打印）

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
ENABLE_STREAMING=true
ENABLE_THINKING=true
TIMEZONE=Asia/Shanghai
MAX_CONTEXT_TOKENS=2000000
HEAD_KEEP=3
TAIL_KEEP=20
COMPRESSION_THRESHOLD=0.8
```

如果使用 DeepSeek 等兼容 API，修改 `OPENAI_BASE_URL` 和 `OPENAI_MODEL` 即可。思维链功能需要 DeepSeek API 支持。

### 启动

```bash
uv run python -m my_small_agent
```

## CLI 命令

| 命令 | 说明 |
|------|------|
| `/help` | 显示帮助信息 |
| `/tools` | 列出所有已注册工具 |
| `/stream` | 切换流式输出开关 |
| `/think` | 切换思维链模式开关 |
| `/detail` | 切换思维链详情展示（默认折叠，输入一次展开） |
| `/status` | 显示当前设置（模型、流式、思维链、Token 用量） |
| `/sessions` | 列出所有历史会话 |
| `/resume` | 恢复指定会话（`/resume <id_prefix>`） |
| `/new` | 新建会话 |
| `/compact` | 手动压缩上下文（保留前3条+后20条） |
| `/clear` | 清空对话历史 |
| `/exit` | 退出程序 |

也可以按 `Ctrl+C` 或 `Ctrl+D` 退出。

## 项目结构

```
my_small_agent/
├── __main__.py       # 入口
├── config.py         # 配置管理（pydantic-settings）
├── agent.py          # 对话循环核心（含流式 + Token估算 + 上下文压缩）
├── llm.py            # OpenAI 异步客户端（chat + chat_stream）
├── cli.py            # CLI 交互层（斜杠命令 + 自动压缩触发）
├── memory.py         # 长期记忆管理（memory.json）
├── session.py        # 会话持久化（保存/恢复/搜索）
└── tools/
    ├── __init__.py       # 工具注册表（create_default_registry）
    ├── base.py           # 工具抽象基类
    ├── file_read.py      # 读取文件
    ├── file_write.py     # 写入文件
    ├── list_dir.py       # 列出目录
    ├── shell_exec.py     # 执行 shell 命令
    ├── web_search.py     # DuckDuckGo 网页搜索
    ├── current_time.py   # 当前时间查询
    ├── grep_search.py    # 递归搜索文件内容
    ├── fetch_url.py      # 获取网页纯文本
    ├── tree.py           # 目录树展示
    ├── find_file.py      # glob 模式查找文件
    ├── file_delete.py    # 删除文件
    ├── system_info.py    # 系统环境信息
    ├── memory_save.py    # 保存长期记忆
    └── session_search.py # 搜索历史会话
```

## 开发

```bash
# 运行测试
uv run pytest -v
```

## 技术栈

| 组件 | 选择 |
|------|------|
| LLM 调用 | `openai`（异步，支持流式 + extra_body 透传） |
| 对话范式 | OpenAI tool_calls 原生流程 |
| 思维链 | DeepSeek Thinking（extra_body 参数） |
| 网页搜索 | `ddgs`（DuckDuckGo，asyncio.to_thread 异步包装） |
| 网页抓取 | `httpx`（异步 HTTP 客户端，HTML 标签剥离） |
| 配置管理 | `pydantic-settings` |
| 终端输入 | `prompt_toolkit` |
| 终端输出 | `rich` |
| 时区 | `zoneinfo` + `tzdata`（Windows） |
| 依赖管理 | `uv` + `pyproject.toml` |

