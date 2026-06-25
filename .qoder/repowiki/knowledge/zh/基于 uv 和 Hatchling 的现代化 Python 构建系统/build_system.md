该项目采用现代化的 Python 开发生态，主要依赖 `uv` 进行依赖管理和环境锁定，使用 `hatchling` 作为构建后端。

### 1. 核心工具链
- **包管理器**: `uv`。通过 `uv.lock` 文件实现确定性的依赖解析和环境复现。它替代了传统的 `pip` + `requirements.txt` 或 `poetry` 流程，提供更快的安装速度和更严格的版本控制。
- **构建后端**: `hatchling`。在 `pyproject.toml` 中配置为 `[build-system]`，负责将项目打包为 wheel 或 sdist 格式。
- **测试框架**: `pytest` 配合 `pytest-asyncio`。由于项目包含大量异步逻辑（LLM 调用、CLI 交互），测试配置中启用了 `asyncio_mode = "auto"` 以简化异步测试编写。

### 2. 项目结构与入口
- **元数据定义**: 所有项目元数据（名称、版本、依赖、脚本入口）均集中在 `pyproject.toml` 中，符合 PEP 621 标准。
- **命令行入口**: 定义了 `agent` 命令，指向 `my_small_agent.__main__:main_entry`。这允许用户在全局或虚拟环境中直接运行 `agent` 启动智能体。
- **模块化执行**: 支持通过 `python -m my_small_agent` 方式运行，入口逻辑位于 `__main__.py`。

### 3. 开发与部署约定
- **环境隔离**: 项目根目录存在 `.venv`，表明推荐使用本地虚拟环境进行开发。
- **配置管理**: 使用 `.env.example` 提供环境变量模板，结合 `pydantic-settings` 在运行时加载配置，避免了硬编码敏感信息。
- **无 CI/CD 配置文件**: 当前仓库根目录未检测到 `.github/workflows` 或其他 CI 配置文件，表明目前可能依赖本地手动构建和测试，或 CI 配置尚未提交至主分支。

### 4. 开发者指南
- **依赖安装**: 应使用 `uv sync` 或 `uv pip install -e .` 来安装项目及其依赖，以确保 `uv.lock` 的一致性。
- **运行测试**: 使用 `pytest` 命令即可自动发现并运行 `tests/` 目录下的所有测试用例。
- **打包发布**: 若需发布，可使用 `uv build` 或 `python -m build` 生成分发文件。