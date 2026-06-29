# Token估算/上下文压缩/六工具 Design Spec

## 概述

为 MySmallAgent 新增三组能力：
1. **Token 估算与进度展示** — 让用户随时掌握上下文消耗情况
2. **上下文压缩** — 在接近 context 上限时自动/手动压缩历史，延长可用对话轮次
3. **六个实用工具** — 补齐文件操作、目录搜索、网页抓取、系统信息等高频能力

---

## 功能一：Token 估算与进度展示

### 需求

- 估算算法：`chars / 4`，遍历所有 `messages` 的每个字段值：
  - 字符串值直接计字符数
  - 列表/字典值序列化为 JSON 后计字符数
  - 合计后整除 4
- `/status` 命令面板新增一行：
  ```
  Token 用量: ~3,200 / 200,000 (1%)
  ```

### 实现位置

| 位置 | 变更 |
|------|------|
| `my_small_agent/agent.py` | 新增 `estimate_tokens() -> int` 方法 |
| `my_small_agent/cli.py` | `_print_status()` 中调用并展示 |
| `my_small_agent/config.py` | 新增 `max_context_tokens: int = 200000` |

---

## 功能二：上下文压缩

### 配置项（新增至 config.py）

| 字段 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `max_context_tokens` | `int` | `200000` | 上下文最大 token 估算上限 |
| `head_keep` | `int` | `3` | 压缩时保留的开头消息条数 |
| `tail_keep` | `int` | `20` | 压缩时保留的末尾消息条数 |
| `compression_threshold` | `float` | `0.8` | 自动触发压缩的 token 用量比例 |

### 压缩算法

```
保留：messages[:head_keep] + [摘要消息] + messages[-tail_keep:]
摘要：调用 LLM（非流式，thinking=False）生成结构化摘要
```

摘要消息格式：
```json
{"role": "assistant", "content": "[压缩历史摘要]\n\n<LLM生成内容>"}
```

### LLM 摘要 Prompt 模板

```
请将以下对话历史压缩为简洁摘要，严格使用以下格式：

## Goal           — 用户目标（1-2 句）
## Key Actions    — 已执行的操作列表
## Current State  — 当前进展
## Decisions      — 重要技术决策
## Technical Details — 需要精确保留的值
## User Preferences — 用户表达的偏好

对话内容：
<middle_messages_text>
```

### 触发方式

**自动触发：** 每轮对话结束后检查：
```python
if estimate_tokens() >= max_context_tokens * compression_threshold \
   and len(messages) > head_keep + tail_keep:
    # 触发压缩，显示 "⚡ 自动压缩中..."
```

**手动触发：** 新增 `/compact` 命令

### /compact 命令行为

1. 检查 `len(messages) > head_keep + tail_keep`（默认 > 23）
2. 不满足：拒绝并提示"消息总数不足，无需压缩"
3. 满足：执行压缩，展示对比：
   ```
   ✓ 上下文已压缩：47 条 → 24 条消息（节省 23 条）
   ```

### 实现位置

| 位置 | 变更 |
|------|------|
| `my_small_agent/agent.py` | 新增 `compact_context() -> tuple[int, int]` 方法；`__init__` 中存储 `self.settings = settings` |
| `my_small_agent/cli.py` | 新增 `_compact_context()` 方法；`_handle_command` 注册 `/compact`；`_run_agent_turn` 末尾调用 `_auto_compact_if_needed()` |

---

## 功能三：六个实用工具

### 工具列表

| 工具名 | 类 | 安全级别 | 依赖 | 说明 |
|--------|-----|----------|------|------|
| `grep_search` | `GrepSearchTool` | safe | 标准库 `re`, `pathlib` | 按关键词/正则递归搜索文件内容，返回匹配行（含文件路径和行号） |
| `fetch_url` | `FetchUrlTool` | safe | `httpx`（新增） | 获取 URL 内容，提取纯文本（去除 HTML 标签，截断至 8000 字符） |
| `tree` | `TreeTool` | safe | 标准库 `pathlib` | 递归展示目录树，支持 max_depth 和 show_hidden |
| `find_file` | `FindFileTool` | safe | 标准库 `pathlib` | 按 glob 模式递归搜索文件名 |
| `file_delete` | `DeleteFileTool` | **dangerous** | 标准库 `pathlib` | 删除文件（不支持目录），执行前需用户确认 |
| `system_info` | `SystemInfoTool` | safe | 标准库 `platform`, `sys`, `os` | 返回 OS、Python 版本、CWD、Home、Shell 信息 |

### 参数规格

**grep_search**
- `pattern`（必填）：关键词或正则表达式
- `path`（可选，默认 `.`）：搜索根目录
- `file_pattern`（可选，默认 `*`）：文件名 glob 过滤
- `ignore_case`（可选，默认 `false`）：大小写不敏感
- `max_results`（可选，默认 `50`）：最大返回条数

**fetch_url**
- `url`（必填）：目标 URL
- `timeout`（可选，默认 `15`）：超时秒数

**tree**
- `path`（可选，默认 `.`）：根目录
- `max_depth`（可选，默认 `3`）：最大深度
- `show_hidden`（可选，默认 `false`）：显示隐藏文件

**find_file**
- `pattern`（必填）：文件名 glob（如 `*.py`）
- `path`（可选，默认 `.`）：搜索根目录
- `max_results`（可选，默认 `50`）：最大返回条数

**file_delete**
- `path`（必填）：要删除的文件路径

**system_info**
- 无参数

### 依赖变更

在 `pyproject.toml` 的 `dependencies` 中新增：
```toml
"httpx>=0.27",
```

（`openai` 已间接依赖 `httpx`，此处显式声明以确保版本锁定）

### 注册位置

在 `my_small_agent/tools/__init__.py` 的 `create_default_registry()` 函数中追加注册 6 个新工具。

---

## 文件变更汇总

### 新建文件

```
my_small_agent/tools/grep_search.py
my_small_agent/tools/fetch_url.py
my_small_agent/tools/tree.py
my_small_agent/tools/find_file.py
my_small_agent/tools/file_delete.py
my_small_agent/tools/system_info.py
tests/test_tools_utility.py
```

### 修改文件

```
my_small_agent/config.py       — 新增 4 个配置字段
my_small_agent/agent.py        — 新增 estimate_tokens / compact_context 方法
my_small_agent/cli.py          — 增强 /status，新增 /compact 命令及自动压缩
my_small_agent/tools/__init__.py — 导入并注册 6 个新工具
pyproject.toml                 — 新增 httpx 依赖
tests/test_config.py           — 新增压缩字段测试
tests/test_agent.py            — 新增 estimate_tokens / compact_context 测试
```

---

## 边界条件与错误处理

| 场景 | 处理方式 |
|------|----------|
| `grep_search` 正则语法错误 | 返回 `"Invalid regex pattern: ..."` |
| `fetch_url` 超时 | 返回 `"Error: Request timed out after N seconds"` |
| `fetch_url` HTTP 错误 | 返回 `"Error: HTTP 4xx/5xx for <url>"` |
| `tree` / `find_file` 路径不存在 | 返回 `"Error: Path '...' does not exist"` |
| `file_delete` 目标是目录 | 返回错误提示，建议使用 shell 命令 |
| `/compact` 消息数不足 | 拒绝并提示最小要求条数 |
| `compact_context` LLM 调用失败 | 返回 `"(摘要生成失败)"`，不中断压缩流程 |
| 自动压缩失败 | 打印警告 `[dim]⚠ 自动压缩失败：...[/dim]`，不中断对话 |
