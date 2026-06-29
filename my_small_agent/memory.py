"""
长期记忆持久化模块 - 负责跨会话记忆的读写。

设计思路：
  - 记忆只在会话启动时加载一次（保障 prompt 缓存命中）
  - 记忆保存使用原子写（.tmp → os.replace()），防止崩溃数据丢失
  - MemoryManager 与 SessionManager 保持相同的设计风格
"""

import json
import os
import secrets
import tempfile
from datetime import datetime, timezone
from pathlib import Path


class MemoryManager:
    """
    长期记忆管理器。

    职责：
      - save_entry():       原子写新记忆条目到 memory.json
      - load_memory_text(): 加载所有条目并格式化为注入文本
    """

    def __init__(self, memory_dir: Path) -> None:
        # 记忆文件存储目录
        self._dir = memory_dir
        self._file = memory_dir / "memory.json"

    def save_entry(self, content: str) -> str:
        """
        创建新记忆条目并原子写入 memory.json。

        返回生成的条目 ID（格式：'mem_' + 8 位十六进制）。
        """
        self._dir.mkdir(parents=True, exist_ok=True)

        # 加载现有数据（文件不存在或损坏时从空列表开始）
        try:
            data = json.loads(self._file.read_text(encoding="utf-8"))
        except (FileNotFoundError, ValueError):
            data = {"entries": []}

        # 生成唯一 ID：mem_ + 8 位随机十六进制（4 字节 = 8 hex chars）
        entry_id = "mem_" + secrets.token_hex(4)
        entry = {
            "id": entry_id,
            "content": content,
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        data["entries"].append(entry)

        # 原子写：先写临时文件，再 os.replace()
        fd, tmp_path = tempfile.mkstemp(dir=self._dir, suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            os.replace(tmp_path, self._file)
        except Exception:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
            raise

        return entry_id

    def load_memory_text(self) -> str:
        """
        加载所有记忆条目并格式化为注入文本。

        每条记忆占一行，格式：'• content'
        文件不存在、JSON 损坏、或无条目时返回空字符串。
        """
        try:
            data = json.loads(self._file.read_text(encoding="utf-8"))
            entries = data.get("entries", [])
        except (FileNotFoundError, ValueError):
            return ""

        if not entries:
            return ""

        lines = [f"• {e['content']}" for e in entries if e.get("content")]
        return "\n".join(lines)
