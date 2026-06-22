"""Tool for executing shell commands."""

import asyncio

from my_small_agent.tools.base import Tool


class ExecuteShellTool(Tool):
    """Execute a shell command and return its output."""

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
    danger_level = "dangerous"

    async def execute(self, **kwargs) -> str:
        command = kwargs["command"]
        try:
            process = await asyncio.create_subprocess_shell(
                command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await asyncio.wait_for(
                process.communicate(), timeout=30.0
            )
            output_parts = []
            if stdout:
                output_parts.append(f"STDOUT:\n{stdout.decode('utf-8', errors='replace')}")
            if stderr:
                output_parts.append(f"STDERR:\n{stderr.decode('utf-8', errors='replace')}")
            if process.returncode != 0:
                output_parts.append(f"Exit code: {process.returncode}")
            return "\n".join(output_parts) if output_parts else "(no output)"
        except asyncio.TimeoutError:
            return "Error: Command timed out after 30 seconds"
        except Exception as e:
            return f"Error executing command: {e}"
