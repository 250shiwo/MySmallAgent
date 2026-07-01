## 1. 系统与工具
MySmallAgent 采用 **pydantic-settings** 作为核心配置管理框架，结合 Python 原生的环境变量机制实现运行时配置的加载。该系统支持从 `.env` 文件自动读取配置，并允许通过系统环境变量进行覆盖，确保了配置管理的类型安全（Type Safety）和灵活性。

## 2. 关键文件与逻辑
- **`my_small_agent/config.py`**: 配置系统的核心实现。定义了 `Settings` 类，继承自 `pydantic_settings.BaseSettings`。该类声明了所有应用级配置项，并通过 `SettingsConfigDict` 指定配置文件路径。
- **`.env.example`**: 配置模板文件，列出了所有必需和可选的环境变量及其默认值示例，供开发者复制为 `.env` 使用。
- **`.gitignore`**: 明确排除了 `.env` 文件，防止敏感信息（如 API Key）泄露到版本控制系统中。
- **`docs/superpowers/specs/2026-06-22-agent-core-design.md`**: 详细记录了配置模块的设计规范，包括字段定义、默认值策略以及与其他模块（如 LLM 客户端）的集成方式。

## 3. 架构与约定
- **配置项定义**：
  - `OPENAI_API_KEY` (str): 必填项，用于身份验证。
  - `OPENAI_BASE_URL` (str): 选填项，默认为 `https://api.openai.com/v1`，支持自定义 API 端点。
  - `OPENAI_MODEL` (str): 选填项，默认为 `gpt-4o`。
  - `MAX_ITERATIONS` (int): 选填项，默认为 `10`，用于限制 Agent 的单次对话循环次数。
- **加载优先级**：遵循 `pydantic-settings` 的标准行为，即 **环境变量 > .env 文件 > 代码默认值**。这种分层设计使得在容器化部署或 CI/CD 环境中可以通过注入环境变量轻松覆盖本地开发配置。
- **初始化模式**：在应用入口（`__main__.py`）处实例化 `Settings()`，并将其作为依赖注入到 `LLMClient` 和 `Agent` 等核心组件中，确保全局配置的一致性。

## 4. 开发者规则
- **敏感信息管理**：严禁将真实的 `OPENAI_API_KEY` 提交到 Git 仓库。必须使用 `.env.example` 作为模板，并在本地创建 `.env` 文件存储真实密钥。
- **新增配置项**：若需添加新配置，必须在 `config.py` 的 `Settings` 类中定义字段，并同步更新 `.env.example` 以提供示例。对于非必填项，应提供合理的默认值以保证应用在最小配置下仍可运行。
- **类型约束**：所有配置项必须利用 Pydantic 的类型系统进行严格定义（如 `int`, `str`），避免在运行时出现类型转换错误。
- **测试隔离**：在编写单元测试时，应通过 `patch.dict(os.environ)` 或传递 `_env_file=None` 来隔离环境干扰，确保测试的可重复性。