"""向量检索：用 sqlite-vec + embedding API 实现"找相似历史事件"。

核心能力：
- 对 episodic_events 生成 embedding 并存储
- 语义搜索："半导体暴跌" → 返回历史上类似的事件

技术栈：
- sqlite-vec（SQLite 原生向量扩展，零外部依赖）
- OpenAI / DeepSeek embedding API（text-embedding-3-small 或 DeepSeek embedding）

设计：
- VectorSearch 不拥有 db_path，而是接收 EpisodicMemory 的 engine
- embedding 维度由模型决定（text-embedding-3-small = 1536 维）
- 向量表用 sqlite-vec 虚拟表，通过 raw_connection load extension
"""

from __future__ import annotations

import logging
import struct
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from mommy_chaogu.agent.episodic_memory import EpisodicMemory

_log = logging.getLogger(__name__)

# embedding 维度（text-embedding-3-small = 1536）
_DEFAULT_DIM = 1536

# sqlite-vec 虚拟表名
_VEC_TABLE = "episodic_vec"
_META_TABLE = "episodic_embeddings"


def _pack_vector(vec: list[float]) -> bytes:
    """float list → struct.pack（sqlite-vec 要求的格式）。"""
    return struct.pack(f"{len(vec)}f", *vec)


def _unpack_vector(data: bytes, dim: int) -> list[float]:
    """struct.pack → float list。"""
    return list(struct.unpack(f"{dim}f", data))


class VectorSearch:
    """向量检索：语义搜索历史事件。

    用法::

        vs = VectorSearch(episodic, client, model="text-embedding-3-small")
        vs.embed_pending()  # 为未生成 embedding 的事件生成
        results = vs.search_similar("半导体暴跌", top_k=5)
    """

    def __init__(
        self,
        episodic: EpisodicMemory,
        client: Any,
        model: str = "text-embedding-3-small",
        dim: int = _DEFAULT_DIM,
    ) -> None:
        self._episodic = episodic
        self._client = client
        self._model = model
        self._dim = dim
        self._engine = episodic.engine

        # 初始化向量表
        self._init_tables()

    def _init_tables(self) -> None:
        """创建元数据表 + sqlite-vec 虚拟表。"""
        from sqlalchemy import text

        # 元数据表
        with self._engine.begin() as conn:
            conn.execute(
                text(f"""
                CREATE TABLE IF NOT EXISTS {_META_TABLE} (
                    event_id INTEGER PRIMARY KEY,
                    embedding BLOB,
                    model TEXT NOT NULL,
                    created_at TEXT NOT NULL
                )
            """)
            )

        # sqlite-vec 虚拟表（需要 raw connection load extension）
        try:
            import sqlite_vec

            with self._engine.raw_connection() as raw_conn:
                raw_conn.enable_load_extension(True)
                sqlite_vec.load(raw_conn)
                raw_conn.execute(
                    f"CREATE VIRTUAL TABLE IF NOT EXISTS {_VEC_TABLE} "
                    f"USING vec0(embedding float[{self._dim}])"
                )
                raw_conn.commit()
        except Exception as e:
            _log.warning("vector_search: failed to init vec table: %s", e)

    def _ensure_vec_extension(self) -> Any:
        """获取一个已 load extension 的 raw connection。"""
        import sqlite_vec

        raw_conn = self._engine.raw_connection()
        raw_conn.enable_load_extension(True)
        sqlite_vec.load(raw_conn)
        return raw_conn

    def generate_embedding(self, text: str) -> list[float] | None:
        """调用 embedding API 生成向量。失败返回 None。"""
        try:
            response = self._client.embeddings.create(
                model=self._model,
                input=text[:2000],  # 截断，避免超 token
            )
            return response.data[0].embedding
        except Exception as e:
            _log.warning("vector_search: embedding API failed: %s", e)
            return None

    def embed_event(self, event_id: int, text_content: str) -> bool:
        """为单个事件生成 embedding 并存储。

        Args:
            event_id: episodic_events.id
            text_content: 用于生成 embedding 的文本（通常是 summary + data 的拼接）

        Returns:
            True if success, False if failed
        """
        vec = self.generate_embedding(text_content)
        if vec is None:
            return False

        return self.store_embedding(event_id, vec)

    def store_embedding(self, event_id: int, vec: list[float]) -> bool:
        """存储 embedding 到元数据表 + 向量表。"""
        from sqlalchemy import text

        packed = _pack_vector(vec)
        now = datetime.now(UTC).isoformat()

        try:
            # 元数据表
            with self._engine.begin() as conn:
                conn.execute(
                    text(
                        f"INSERT OR REPLACE INTO {_META_TABLE} "
                        f"(event_id, embedding, model, created_at) "
                        f"VALUES (:eid, :emb, :model, :ts)"
                    ),
                    {"eid": event_id, "emb": packed, "model": self._model, "ts": now},
                )

            # sqlite-vec 虚拟表
            raw_conn = self._ensure_vec_extension()
            try:
                raw_conn.execute(
                    f"DELETE FROM {_VEC_TABLE} WHERE rowid = ?",
                    (event_id,),
                )
                raw_conn.execute(
                    f"INSERT INTO {_VEC_TABLE} (rowid, embedding) VALUES (?, ?)",
                    (event_id, packed),
                )
                raw_conn.commit()
            finally:
                raw_conn.close()

            return True
        except Exception as e:
            _log.warning("vector_search: store_embedding failed for event %d: %s", event_id, e)
            return False

    def embed_pending(self, batch_size: int = 20) -> dict[str, int]:
        """为所有没有 embedding 的事件生成 embedding。

        Returns:
            {"embedded": N, "failed": M, "skipped": K}
        """
        from sqlalchemy import text

        # 找没有 embedding 的事件
        with self._engine.begin() as conn:
            rows = conn.execute(
                text(
                    f"SELECT e.id, e.summary, e.data FROM episodic_events e "
                    f"LEFT JOIN {_META_TABLE} m ON e.id = m.event_id "
                    f"WHERE m.event_id IS NULL "
                    f"ORDER BY e.id DESC LIMIT :limit"
                ),
                {"limit": batch_size},
            ).all()

        results = {"embedded": 0, "failed": 0, "skipped": 0}

        import json

        for row in rows:
            event_id = row[0]
            summary = row[1] or ""
            data_str = ""
            try:
                data = json.loads(row[2]) if row[2] else {}
                data_str = " ".join(str(v) for v in data.values()) if data else ""
            except (json.JSONDecodeError, TypeError):
                pass

            text_content = f"{summary} {data_str}".strip()
            if not text_content:
                results["skipped"] += 1
                continue

            if self.embed_event(event_id, text_content):
                results["embedded"] += 1
            else:
                results["failed"] += 1

        _log.info("embed_pending: %s", results)
        return results

    def search_similar(
        self,
        query_text: str,
        scope: str | None = None,
        top_k: int = 5,
        days_back: int = 90,
    ) -> list[dict[str, Any]]:
        """语义搜索：找与当前情况相似的历史事件。

        Args:
            query_text: 搜索文本（如"半导体暴跌，主力大幅流出"）
            scope: 可选 scope 过滤
            top_k: 返回条数
            days_back: 回溯天数

        Returns:
            [{"id", "summary", "timestamp", "scope", "distance", ...}, ...]
            按 distance 升序（越近越相似）
        """
        # 生成查询向量
        query_vec = self.generate_embedding(query_text)
        if query_vec is None:
            return []

        packed = _pack_vector(query_vec)

        try:
            raw_conn = self._ensure_vec_extension()
            try:
                cursor = raw_conn.execute(
                    f"SELECT rowid, distance FROM {_VEC_TABLE} "
                    f"WHERE embedding MATCH ? "
                    f"ORDER BY distance "
                    f"LIMIT ?",
                    (packed, top_k * 3),  # 多取一些用于 scope/date 过滤
                )
                vec_results = cursor.fetchall()
            finally:
                raw_conn.close()
        except Exception as e:
            _log.warning("vector_search: vec query failed: %s", e)
            return []

        if not vec_results:
            return []

        # 取事件详情并过滤
        from datetime import timedelta

        from sqlalchemy import text

        cutoff = (datetime.now(UTC) - timedelta(days=days_back)).strftime("%Y-%m-%d")

        event_ids = [r[0] for r in vec_results]
        placeholders = ",".join(str(eid) for eid in event_ids)
        distance_map = {r[0]: r[1] for r in vec_results}

        with self._engine.begin() as conn:
            query = (
                f"SELECT id, timestamp, event_type, scope, code, name, summary, data "
                f"FROM episodic_events "
                f"WHERE id IN ({placeholders}) "
                f"AND timestamp >= :cutoff"
            )
            params: dict[str, Any] = {"cutoff": cutoff}
            if scope:
                query += " AND scope LIKE :scope"
                params["scope"] = f"{scope}%"

            rows = conn.execute(text(query), params).all()

        # 组装结果
        results: list[dict[str, Any]] = []
        for row in rows:
            eid = row[0]
            results.append(
                {
                    "id": eid,
                    "timestamp": row[1],
                    "event_type": row[2],
                    "scope": row[3],
                    "code": row[4],
                    "name": row[5],
                    "summary": row[6],
                    "distance": distance_map.get(eid, 999.0),
                }
            )

        # 按 distance 排序，截取 top_k
        results.sort(key=lambda x: x["distance"])
        return results[:top_k]

    def stats(self) -> dict[str, Any]:
        """统计 embedding 覆盖情况。"""
        from sqlalchemy import text

        with self._engine.begin() as conn:
            total_events = conn.execute(text("SELECT COUNT(*) FROM episodic_events")).scalar() or 0
            total_embedded = conn.execute(text(f"SELECT COUNT(*) FROM {_META_TABLE}")).scalar() or 0

        return {
            "total_events": total_events,
            "embedded": total_embedded,
            "coverage": total_embedded / total_events if total_events else 0.0,
            "model": self._model,
            "dim": self._dim,
        }
