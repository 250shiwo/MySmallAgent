"""
执行 Shell 命令工具 - 在系统 shell 中执行命令并返回输出。

安全级别：dangerous（可能执行任意系统命令，需要用户确认后才能执行）

注意：
  - 命令有 30 秒超时限制，超时后自动终止
  - 同时捕获 stdout（标准输出）和 stderr（错误输出）
  - 在 Windows 上使用 cmd.exe，在 Linux/macOS 上使用 /bin/sh
"""

import asyncio

from my_small_agent.tools.base import Tool


class ExecuteShellTool(Tool):
    """执行 shell 命令并返回其标准输出和错误输出。"""

    # --- 工具元数据 ---
    name = "execute_shell"
    description = "Execute a shell command and return stdout and stderr."

    parameters = {
        "type": "object",
        "properties": {
            "command": {
                "type": "string",
                "description": "The shell command to execute.",
            },
        },
        "required": ["command"],
    }

    # 安全级别：dangerous（可执行任意系统命令，必须先询问用户）
    danger_level = "dangerous"
    category = "write"

    async def execute(self, **kwargs) -> str:
        """
        执行 shell 命令的流程：
          1. 创建子进程执行命令
          2. 等待最多 30 秒
          3. 拼接 stdout + stderr 返回
          4. 如果命令失败（returncode != 0），附加退出码信息
        """
        command = kwargs["command"]
        try:
            # 步骤1：创建异步子进程执行命令
            # stdout/stderr 用 PIPE 捕获，不直接打印到终端
            process = await asyncio.create_subprocess_shell(
                command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )

            # 步骤2：等待命令完成，最多等 30 秒
            stdout, stderr = await asyncio.wait_for(
                process.communicate(), timeout=30.0
            )

            # 步骤3：拼接输出结果
            output_parts = []
            if stdout:
                # decode 把字节转为字符串，errors='replace' 处理无法解码的字符
                output_parts.append(f"STDOUT:\n{stdout.decode('utf-8', errors='replace')}")
            if stderr:
                output_parts.append(f"STDERR:\n{stderr.decode('utf-8', errors='replace')}")

            # 步骤4：如果命令返回非零退出码，说明执行失败
            if process.returncode != 0:
                output_parts.append(f"Exit code: {process.returncode}")

            # 如果没有任何输出，返回提示；否则用换行拼接各部分
            return "\n".join(output_parts) if output_parts else "(no output)"

        except asyncio.TimeoutError:
            # 命令执行超过 30 秒，强制超时
            return "Error: Command timed out after 30 seconds"
        except Exception as e:
            return f"Error executing command: {e}"
