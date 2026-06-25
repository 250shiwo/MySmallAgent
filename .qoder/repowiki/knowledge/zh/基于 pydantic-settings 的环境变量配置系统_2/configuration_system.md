## 1. 核心系统与工具
MySmallAgent 采用 **pydantic-settings** 作为其配置管理的核心框架。该系统利用 Pydantic 的数据验证能力，结合环境变量（Environment Variables）和 `.env` 文件，实现类型安全、自动加载且易于测试的配置管理方案。

## 2. 关键文件与职责
- `my_small_agent/config.py`: 定义 `Settings` 类，继承自 `BaseSettings`。这是配置系统的唯一入口，负责声明所有配置项及其默认值。
- `.env.example`: 提供环境变量的模板，列出了必需的配置项（如 `OPENAI_API_KEY`）和可选配置项。
- `pyproject.toml`: 声明了 `pydantic-settings>=2.0` 依赖，确保运行时环境具备配置加载能力。
- `tests/test_config.py`: 包含针对配置加载逻辑的单元测试，验证了从环境变量读取以及默认值回退的行为。

## 3. 架构设计与约定
### 3.1 集中化配置模型
所有应用配置被封装在单一的 `Settings` 类中：
```python
class Settings(BaseSettings):
    openai_api_key: str
    openai_base_url: str = "https://api.openai.com/v1"
    openai_model: str = "gpt-4o"
    max_iterations: int = 10

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
    )
```
这种设计确保了配置项的类型安全（例如 `max_iterations` 必须是整数），并提供了清晰的文档化默认值。

### 3.2 优先级策略
配置加载遵循标准的优先级顺序：
1. **环境变量**：直接在操作系统或 shell 中设置的变量（如 `export OPENAI_MODEL=gpt-4o-mini`）具有最高优先级。
2. **.env 文件**：项目根目录下的 `.env` 文件作为次级来源。
3. **代码默认值**：在 `Settings` 类中定义的默认值作为最后兜底。

### 3.3 启动时初始化
在应用入口 `my_small_agent/__main__.py` 中，`Settings()` 实例在异步主循环启动前被同步实例化。如果缺少必需的配置项（如 `OPENAI_API_KEY`），`pydantic-settings` 会在启动阶段立即抛出 `ValidationError`，从而实现“快速失败”（Fail-fast）原则。

## 4. 开发者规范
- **新增配置项**：必须在 `my_small_agent/config.py` 的 `Settings` 类中添加字段。如果是敏感信息（如 API Key），不应设置默认值以强制要求用户显式配置。
- **环境变量命名**：遵循全大写、下划线分隔的命名规范（SNAKE_CASE），例如 `OPENAI_BASE_URL`。
- **本地开发**：复制 `.env.example` 为 `.env` 并填入实际值。`.env` 文件已被 `.gitignore` 排除，严禁提交到版本控制系统。
- **测试隔离**：在编写单元测试时，应使用 `_env_file=None` 参数实例化 `Settings` 并配合 `patch.dict(os.environ, ...)` 来模拟不同的配置环境，避免依赖本地的 `.env` 文件。