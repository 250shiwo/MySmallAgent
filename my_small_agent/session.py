"""
会话持久化模块 - 负责会话数据的读写和查询。

设计思路：
  - SessionData 是纯数据容器（dataclass），不含 IO 逻辑
  - SessionManager 封装所有文件操作，支持原子写、列表查询、前缀匹配
  - 原子写策略：先写 .tmp 临时文件，再 os.replace() 重命名，防止崩溃丢数据
  - messages 字段不包含 system prompt（加载时由 Agent 重新插入）
"""

import json
import os
import tempfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path


class AmbiguousPrefixError(Exception):
    """find_by_prefix() 匹配到多个会话时抛出此异常。"""


@dataclass
class SessionData:
    """会话的完整数据结构（对应 JSON 文件内容）。"""

    session_id: str
    created_at: str   # ISO 8601 含时区
    updated_at: str   # ISO 8601 含时区
    title: str
    messages: list[dict]


class SessionManager:
    """
    会话持久化管理器。

    职责：
      - save():            原子写会话文件
      - load():            读取单个会话
      - list_sessions():   列出所有会话（按 updated_at 倒序）
      - find_by_prefix():  按 session_id 前缀查找会话
    """

    def __init__(self, sessions_dir: Path) -> None:
        # 会话文件存储目录（可能尚未创建）
        self._dir = sessions_dir

    def save(
        self,
        session_id: str,
        title: str,
        created_at: str,
        messages: list[dict],
    ) -> None:
        """
        原子写会话文件。

        策略：先在目标目录写临时文件，再 os.replace() 重命名。
        失败时清理临时文件，向上抛出异常（调用方负责打印警告）。
        """
        self._dir.mkdir(parents=True, exist_ok=True)
        target = self._dir / f"{session_id}.json"
        data = {
            "session_id": session_id,
            "created_at": created_at,
            "updated_at": datetime.now(timezone.utc).isoformat(),
            "title": title,
            "messages": messages,
        }
        # 在目标目录创建临时文件（同分区，os.replace() 才是原子操作）
        fd, tmp_path = tempfile.mkstemp(dir=self._dir, suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            os.replace(tmp_path, target)
        except Exception:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
            raise

    def load(self, session_id: str) -> SessionData | None:
        """读取指定会话文件。文件不存在或 JSON 损坏时返回 None。"""
        path = self._dir / f"{session_id}.json"
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            return SessionData(
                session_id=data["session_id"],
                created_at=data["created_at"],
                updated_at=data["updated_at"],
                title=data["title"],
                messages=data["messages"],
            )
        except (FileNotFoundError, ValueError, KeyError):
            return None

    def list_sessions(self) -> list[SessionData]:
        """
        列出所有已保存的会话，按 updated_at 倒序排列。
        JSON 损坏的文件自动跳过。
        """
        if not self._dir.exists():
            return []
        sessions = []
        for path in self._dir.glob("*.json"):
            data = self.load(path.stem)
            if data is not None:
                sessions.append(data)
        # ISO 8601 字符串可直接按字典序比较
        sessions.sort(key=lambda s: s.updated_at, reverse=True)
        return sessions

    def find_by_prefix(self, prefix: str) -> SessionData | None:
        """
        按 session_id 前缀查找会话。

        - 无匹配 → 返回 None
        - 唯一匹配 → 返回 SessionData
        - 多个匹配 → 抛出 AmbiguousPrefixError
        """
        all_sessions = self.list_sessions()
        matches = [s for s in all_sessions if s.session_id.startswith(prefix)]
        if len(matches) == 0:
            return None
        if len(matches) > 1:
            ids = ", ".join(s.session_id for s in matches)
            raise AmbiguousPrefixError(
                f"前缀 '{prefix}' 匹配到多个会话：{ids}"
            )
        return matches[0]
