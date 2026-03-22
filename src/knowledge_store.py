"""本地知识库：JSONL 持久化 + 供模型使用的上下文块。"""

from __future__ import annotations

import json
import threading
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


@dataclass
class KnowledgeEntry:
    """单条知识记录（与 JSONL 中一行对应）。"""

    id: str
    title: str
    content: str
    source: str
    tags: list[str]
    stored_at: str

    def to_line(self) -> str:
        """序列化为 JSON 一行。"""
        return json.dumps(
            {
                "id": self.id,
                "title": self.title,
                "content": self.content,
                "source": self.source,
                "tags": self.tags,
                "stored_at": self.stored_at,
            },
            ensure_ascii=False,
        )

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> KnowledgeEntry | None:
        """从字典恢复，字段不全则返回 None。"""
        try:
            return cls(
                id=str(data["id"]),
                title=str(data.get("title", "")),
                content=str(data.get("content", "")),
                source=str(data.get("source", "")),
                tags=list(data.get("tags") or []),
                stored_at=str(data.get("stored_at", "")),
            )
        except (KeyError, TypeError, ValueError):
            return None


class KnowledgeStore:
    """
    线程安全的追加写 JSONL 文件，从新到旧读取用于拼 system 补充说明。

    文件格式：每行一个 JSON 对象，便于外部用脚本 tail/合并。
    """

    def __init__(self, file_path: str | Path) -> None:
        self._path = Path(file_path)
        self._lock = threading.Lock()

    @property
    def path(self) -> Path:
        return self._path

    def ensure_parent(self) -> None:
        """确保父目录存在。"""
        self._path.parent.mkdir(parents=True, exist_ok=True)

    def append(
        self,
        content: str,
        *,
        title: str = "",
        source: str = "",
        tags: list[str] | None = None,
    ) -> KnowledgeEntry:
        """
        追加一条知识。content 必填；其余可选，供检索与审计。

        Returns:
            写入后的 KnowledgeEntry（含 id 与时间戳）。
        """
        text = (content or "").strip()
        if not text:
            raise ValueError("content must be non-empty")

        entry = KnowledgeEntry(
            id=uuid.uuid4().hex,
            title=(title or "").strip(),
            content=text,
            source=(source or "").strip(),
            tags=[str(t).strip() for t in (tags or []) if str(t).strip()],
            stored_at=datetime.now(timezone.utc).isoformat(),
        )
        line = entry.to_line() + "\n"
        with self._lock:
            self.ensure_parent()
            with self._path.open("a", encoding="utf-8") as f:
                f.write(line)
        return entry

    def load_recent(self, max_entries: int = 200) -> list[KnowledgeEntry]:
        """从文件尾部读取最近若干条（从新到旧）。"""
        if max_entries <= 0 or not self._path.is_file():
            return []
        with self._lock:
            try:
                raw = self._path.read_text(encoding="utf-8")
            except OSError:
                return []
        lines = [ln.strip() for ln in raw.splitlines() if ln.strip()]
        selected = lines[-max_entries:]
        out: list[KnowledgeEntry] = []
        for ln in reversed(selected):
            try:
                data = json.loads(ln)
            except json.JSONDecodeError:
                continue
            e = KnowledgeEntry.from_dict(data)
            if e and e.content:
                out.append(e)
        return out

    def build_context_block(self, max_chars: int = 6000) -> str:
        """
        拼成可塞进 system prompt 的「知识库参考」文本；超长则从最新开始截断。

        说明：当前为全文摘录型上下文，非向量检索；后续可换向量库仅返回相关片段。
        """
        if max_chars <= 0:
            return ""
        parts: list[str] = []
        used = 0
        for entry in self.load_recent():
            header = f"[{entry.id[:8]}] {entry.title or '（无标题）'}"
            if entry.source:
                header += f" | 来源:{entry.source}"
            if entry.tags:
                header += f" | 标签:{','.join(entry.tags)}"
            block = f"{header}\n{entry.content}\n"
            if used + len(block) > max_chars:
                break
            parts.append(block)
            used += len(block)
        if not parts:
            return ""
        return (
            "\n--- 知识库（外部同步，按时间新到旧，回答时请结合下列事实） ---\n"
            + "\n".join(parts)
            + "\n--- 知识库结束 ---\n"
        )
