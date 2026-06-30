该项目采用 **uv** 作为核心的 Python 包管理与环境工具，取代了传统的 `pip` + `venv` 或 `poetry` 工作流。

### 1. 核心系统与工具
- **包管理器**: `uv`。它负责依赖解析、安装以及虚拟环境管理。
- **构建后端**: `hatchling`。在 `pyproject.toml` 中声明，用于项目的打包与分发。
- **锁文件机制**: 使用 `uv.lock` 记录精确的依赖树（包括哈希值和平台特定的 wheel 信息），确保在不同环境中依赖的一致性。

### 2. 关键配置文件
- **`pyproject.toml`**: 
  - 定义了项目元数据（名称、版本、描述）。
  - **生产依赖**: `openai`, `pydantic-settings`, `prompt-toolkit`, `rich`。
  - **开发依赖组**: 在 `[dependency-groups]` 下定义了 `dev` 组，包含 `pytest` 和 `pytest-asyncio`。
  - **入口点**: 配置了 `agent` 命令行脚本指向 `my_small_agent.__main__:main_entry`。
- **`uv.lock`**: 自动生成的锁定文件，包含了所有直接和间接依赖的完整解析结果。
- **`.gitignore`**: 明确排除了 `.venv/` 目录，但根据注释建议，`uv.lock` 通常应纳入版本控制以保证可复现性（尽管当前仓库中已存在该文件）。

### 3. 架构与约定
- **依赖分组**: 严格区分生产环境依赖与开发环境依赖，通过 `dependency-groups` 进行管理，便于在 CI/CD 或生产部署时仅安装必要组件。
- **Python 版本约束**: 要求 Python `>=3.11`，确保了类型提示和异步特性的现代化支持。
- **无 Vendor 策略**: 项目直接从 PyPI (`https://pypi.org/simple`) 获取依赖，未采用 vendoring（将第三方代码拷贝至源码树）策略。

### 4. 开发者规范
- **添加依赖**: 应使用 `uv add <package>` 命令，而非 `pip install`，以确保 `uv.lock` 同步更新。
- **环境同步**: 在新克隆仓库后，运行 `uv sync` 即可根据 `uv.lock` 重建完全一致的开发环境。
- **运行测试**: 利用 `uv run pytest` 可以在隔离的环境中执行测试，避免全局环境污染。