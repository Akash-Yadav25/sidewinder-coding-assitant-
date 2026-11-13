"""SQLite-backed session persistence and project memory."""

from __future__ import annotations

import json
import logging
import sqlite3
import time
from pathlib import Path
from typing import Any

from coder_agent.storage.models import (
    CheckpointRecord,
    MessageRecord,
    ProjectMemoryRecord,
    SessionRecord,
    ToolCallRecord,
)
from coder_agent.types import ToolCall, ToolResult

logger = logging.getLogger("coder_agent.storage")


class SessionStore:
    """Manages SQLite storage for sessions, messages, and project memory."""

    def __init__(self, project_dir: str | Path):
        self.project_dir = Path(project_dir).resolve()
        self.store_dir = self.project_dir / ".coder-agent"
        self.db_path = self.store_dir / "sessions.db"
        self._init_db()
        self._ensure_gitignore()

    def _get_connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row
        return conn

    def _ensure_gitignore(self) -> None:
        """Ensure .coder-agent is added to .gitignore if present."""
        gitignore = self.project_dir / ".gitignore"
        try:
            if gitignore.is_file():
                content = gitignore.read_text(encoding="utf-8")
                if ".coder-agent" not in content:
                    with open(gitignore, "a", encoding="utf-8") as f:
                        f.write("\n# Coder Agent session cache\n.coder-agent/\n")
        except Exception:
            pass

    def _init_db(self) -> None:
        """Create database tables if they do not exist."""
        self.store_dir.mkdir(parents=True, exist_ok=True)
        with self._get_connection() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS sessions (
                    id TEXT PRIMARY KEY,
                    created_at REAL,
                    updated_at REAL,
                    project_dir TEXT,
                    provider TEXT,
                    model TEXT,
                    status TEXT
                );

                CREATE TABLE IF NOT EXISTS messages (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id TEXT,
                    role TEXT,
                    content TEXT,
                    tool_calls_json TEXT,
                    results_json TEXT,
                    created_at REAL,
                    FOREIGN KEY (session_id) REFERENCES sessions(id)
                );

                CREATE TABLE IF NOT EXISTS checkpoints (
                    id TEXT PRIMARY KEY,
                    session_id TEXT,
                    description TEXT,
                    created_at REAL,
                    FOREIGN KEY (session_id) REFERENCES sessions(id)
                );

                CREATE TABLE IF NOT EXISTS project_memory (
                    key TEXT PRIMARY KEY,
                    value TEXT,
                    updated_at REAL
                );
                """
            )
            conn.commit()

    def create_session(
        self,
        session_id: str | None = None,
        provider: str = "",
        model: str = "",
    ) -> str:
        """Register a new session or return existing."""
        sid = session_id or f"sess_{int(time.time())}_{sqlite3.connect(':memory:').total_changes}"
        now = time.time()
        with self._get_connection() as conn:
            conn.execute(
                """
                INSERT OR IGNORE INTO sessions (id, created_at, updated_at, project_dir, provider, model, status)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (sid, now, now, str(self.project_dir), str(provider), str(model), "active"),
            )
            conn.commit()
        return sid

    def save_message(
        self,
        session_id: str,
        role: str,
        content: str = "",
        tool_calls: list[ToolCall] | None = None,
        results: list[ToolResult] | None = None,
    ) -> None:
        """Persist a conversation message turn into SQLite."""
        tc_json = ""
        if tool_calls:
            tc_dicts = [{"id": tc.id, "name": tc.name, "input": tc.input} for tc in tool_calls]
            tc_json = json.dumps(tc_dicts)

        res_json = ""
        if results:
            res_dicts = [
                {"tool_use_id": r.tool_use_id, "content": r.content, "is_error": r.is_error}
                for r in results
            ]
            res_json = json.dumps(res_dicts)

        now = time.time()
        with self._get_connection() as conn:
            conn.execute(
                """
                INSERT INTO messages (session_id, role, content, tool_calls_json, results_json, created_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (session_id, role, content, tc_json, res_json, now),
            )
            conn.execute("UPDATE sessions SET updated_at = ? WHERE id = ?", (now, session_id))
            conn.commit()

    def get_session_messages(self, session_id: str) -> list[dict[str, Any]]:
        """Retrieve full conversation history for a session."""
        messages: list[dict[str, Any]] = []
        with self._get_connection() as conn:
            cursor = conn.execute(
                "SELECT role, content, tool_calls_json, results_json FROM messages WHERE session_id = ? ORDER BY id ASC",
                (session_id,),
            )
            for row in cursor.fetchall():
                role = row["role"]
                content = row["content"]
                tc_json = row["tool_calls_json"]
                res_json = row["results_json"]

                msg: dict[str, Any] = {"role": role, "content": content}
                if tc_json:
                    try:
                        raw_tcs = json.loads(tc_json)
                        msg["tool_calls"] = [
                            ToolCall(id=t["id"], name=t["name"], input=t.get("input", {}))
                            for t in raw_tcs
                        ]
                    except Exception:
                        pass
                if res_json:
                    try:
                        raw_res = json.loads(res_json)
                        msg["results"] = [
                            ToolResult(
                                tool_use_id=r["tool_use_id"],
                                content=r["content"],
                                is_error=r.get("is_error", False),
                            )
                            for r in raw_res
                        ]
                    except Exception:
                        pass

                messages.append(msg)
        return messages

    def list_sessions(self) -> list[dict[str, Any]]:
        """List past sessions ordered by most recent."""
        with self._get_connection() as conn:
            cursor = conn.execute("SELECT * FROM sessions ORDER BY updated_at DESC LIMIT 20")
            return [dict(row) for row in cursor.fetchall()]

    def get_latest_session_id(self) -> str | None:
        """Get the ID of the most recently updated session."""
        with self._get_connection() as conn:
            cursor = conn.execute("SELECT id FROM sessions ORDER BY updated_at DESC LIMIT 1")
            row = cursor.fetchone()
            return row["id"] if row else None

    def set_memory(self, key: str, value: str) -> None:
        """Store persistent project memory."""
        now = time.time()
        with self._get_connection() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO project_memory (key, value, updated_at) VALUES (?, ?, ?)",
                (key, value, now),
            )
            conn.commit()

    def get_memory(self, key: str) -> str | None:
        """Retrieve persistent project memory value."""
        with self._get_connection() as conn:
            cursor = conn.execute("SELECT value FROM project_memory WHERE key = ?", (key,))
            row = cursor.fetchone()
            return row["value"] if row else None

    def get_session_record(self, session_id: str) -> SessionRecord | None:
        """Retrieve structured SessionRecord for a session ID."""
        with self._get_connection() as conn:
            cursor = conn.execute(
                "SELECT id, project_dir, provider, model, created_at, updated_at, status FROM sessions WHERE id = ?",
                (session_id,),
            )
            row = cursor.fetchone()
            if not row:
                return None
            return SessionRecord(
                id=row["id"],
                project_dir=row["project_dir"],
                provider=row["provider"],
                model=row["model"],
                created_at=row["created_at"],
                updated_at=row["updated_at"],
                status=row["status"],
            )

    def list_sessions(self, limit: int = 20) -> list[SessionRecord]:
        """List recent sessions as structured SessionRecords."""
        records: list[SessionRecord] = []
        with self._get_connection() as conn:
            cursor = conn.execute(
                "SELECT id, project_dir, provider, model, created_at, updated_at, status FROM sessions ORDER BY updated_at DESC LIMIT ?",
                (limit,),
            )
            for row in cursor.fetchall():
                records.append(
                    SessionRecord(
                        id=row["id"],
                        project_dir=row["project_dir"],
                        provider=row["provider"],
                        model=row["model"],
                        created_at=row["created_at"],
                        updated_at=row["updated_at"],
                        status=row["status"],
                    )
                )
        return records
