"""
读取文件工具 - 读取指定路径文件的内容并返回。

安全级别：safe（只读操作，自动执行）
"""

from my_small_agent.tools.base import Tool


class ReadFileTool(Tool):
    """读取指定路径的文件内容。"""

    # --- 工具元数据（OpenAI 通过这些信息决定是否调用此工具）---
    name = "read_file"
    description = "Read the contents of a file at the specified path."

    # JSON Schema 格式的参数定义：告诉 LLM 调用时需要传什么参数
    parameters = {
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "The absolute or relative path to the file to read.",
            },
        },
        "required": ["path"],
    }

    # 安全级别：safe 表示只读操作，无需用户确认即可自动执行
    danger_level = "safe"

    async def execute(self, **kwargs) -> str:
        """读取文件内容并返回。出错时返回友好的错误信息而不是抛异常。"""
        path = kwargs["path"]
        try:
            with open(path, "r", encoding="utf-8") as f:
                return f.read()
        except FileNotFoundError:
            return f"Error: File not found: {path}"
        except PermissionError:
            return f"Error: Permission denied: {path}"
        except Exception as e:
            return f"Error reading file: {e}"
