"""
配置管理模块 - 从环境变量和 .env 文件加载应用配置。

工作原理：
  - 使用 pydantic-settings 库，自动从 .env 文件或系统环境变量读取配置
  - 必填项（如 openai_api_key）如果不提供会启动报错
  - 可选项都有合理的默认值
"""

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """
    Agent 的配置项集合。

    配置项说明：
      - openai_api_key:   API 密钥，必填，从 .env 或环境变量读取
      - openai_base_url:  API 地址，默认 OpenAI 官方地址（可改为 DeepSeek 等兼容 API）
      - openai_model:     使用的模型名称，默认 gpt-4o
      - max_iterations:   Agent 单次对话最多调用工具的次数，防止无限循环
    """

    openai_api_key: str                              # API 密钥（必填）
    openai_base_url: str = "https://api.openai.com/v1"  # API 地址（支持所有 OpenAI 兼容服务）
    openai_model: str = "gpt-4o"                     # 模型名称
    max_iterations: int = 10                         # 工具调用最大迭代次数

    # 告诉 pydantic-settings 从项目根目录的 .env 文件读取配置
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
    )
"""Application configuration loaded from environment variables and .env file."""

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Agent configuration settings."""

    openai_api_key: str
    openai_base_url: str = "https://api.openai.com/v1"
    openai_model: str = "gpt-4o"
    max_iterations: int = 10

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
    )
