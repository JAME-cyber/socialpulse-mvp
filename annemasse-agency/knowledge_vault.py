"""
Knowledge Vault — Shared memory layer for agents.

Inspired by JustHireMe's triple-store architecture (SQLite + KuzuDB + LanceDB),
adapted for our 0€ constraint:
  - SQLite FTS5 for full-text search (replaces KuzuDB graph)
  - JSON-serialized embeddings for vector search (replaces LanceDB)
  - Graceful degradation: if embeddings unavailable, keyword search works alone

Architecture:
  ┌─────────────────────────────────────────────────────────┐
  │  KnowledgeVault                                          │
  │  ├── SQLite FTS5      → keyword search (always works)  │
  │  ├── Embedding index  → semantic search (optional)     │
  │  ├── WORM journal     → audit trail (from Cortex Leman)│
  │  └── Tool Contracts   → Pydantic validation (Skill #2) │
  └─────────────────────────────────────────────────────────┘

Usage:
  vault = KnowledgeVault("state/vault.db")
  vault.store("product", {"name": "Posture Corrector", "source": "aliexpress"})
  results = vault.search("posture correction device", limit=5)
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from pydantic import BaseModel, Field, field_validator

# ── Contracts ──────────────────────────────────────────────────

class VaultEntryContract(BaseModel):
    """Pydantic contract for a Knowledge Vault entry."""
    entry_type: str = Field(..., min_length=1, max_length=50, description="Type: product, lead, supplier, campaign, insight")
    data: dict[str, Any] = Field(..., description="The actual entry data")
    tags: list[str] = Field(default_factory=list, max_length=20)
    source: str = Field(default="unknown", max_length=100)
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)

    @field_validator("entry_type")
    @classmethod
    def validate_entry_type(cls, v: str) -> str:
        allowed = {"product", "lead", "supplier", "campaign", "insight", "feedback", "market", "creative"}
        v_lower = v.lower().strip()
        if v_lower not in allowed:
            raise ValueError(f"entry_type must be one of {allowed}, got '{v}'")
        return v_lower

    @field_validator("tags")
    @classmethod
    def normalize_tags(cls, v: list[str]) -> list[str]:
        return [t.lower().strip() for t in v if t.strip()]


class VaultSearchResult(BaseModel):
    """Contract for a search result from the vault."""
    id: str
    entry_type: str
    data: dict[str, Any]
    tags: list[str]
    source: str
    confidence: float
    rank: float = Field(default=0.0, ge=0.0, description="Search relevance score")
    created_at: str
    worm_hash: str


class VaultStats(BaseModel):
    """Contract for vault statistics."""
    total_entries: int
    by_type: dict[str, int]
    by_source: dict[str, int]
    db_size_bytes: int
    oldest_entry: Optional[str] = None
    newest_entry: Optional[str] = None


# ── WORM Journal ──────────────────────────────────────────────

@dataclass(frozen=True)
class WormEntry:
    """Immutable WORM journal entry — hash-chained audit trail."""
    sequence: int
    timestamp: str
    action: str  # store, search, delete, update
    entry_type: str
    entry_id: str
    details: str
    prev_hash: str
    hash: str


def _now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _hash_data(*parts: str) -> str:
    raw = "|".join(parts)
    return hashlib.sha256(raw.encode()).hexdigest()[:16]


# ── Embedding helpers (graceful degradation) ──────────────────

class NullEmbedder:
    """No-op embedder so the vault never fails when SentenceTransformer is unavailable."""
    def embed(self, text: str) -> list[float]:
        return []

    def similarity(self, vec_a: list[float], vec_b: list[float]) -> float:
        return 0.0


def _try_load_embedder() -> NullEmbedder:
    """Try to load a real embedder. Return NullEmbedder on failure."""
    try:
        from sentence_transformers import SentenceTransformer
        model = SentenceTransformer("all-MiniLM-L6-v2")

        class _RealEmbedder:
            def __init__(self, m):
                self._model = m

            def embed(self, text: str) -> list[float]:
                if not text.strip():
                    return []
                try:
                    vec = self._model.encode(text, normalize_embeddings=True)
                    return [float(x) for x in vec]
                except Exception:
                    return []

            def similarity(self, vec_a: list[float], vec_b: list[float]) -> float:
                if not vec_a or not vec_b:
                    return 0.0
                dot = sum(a * b for a, b in zip(vec_a, vec_b))
                return max(0.0, min(1.0, dot))

        return _RealEmbedder(model)
    except Exception:
        return NullEmbedder()


# ── Knowledge Vault ───────────────────────────────────────────

class KnowledgeVault:
    """
    Multi-modal knowledge store for agents.

    Combines:
    - SQLite FTS5 for full-text keyword search
    - Optional vector embeddings for semantic search
    - WORM journal for audit trail
    - Pydantic contracts for data validation

    Inspired by JustHireMe's triple-store but adapted for:
    - 0€ budget (SQLite instead of KuzuDB + LanceDB)
    - Offline operation (embeddings optional)
    - Agent-centric (entry_type = agent name)
    """

    def __init__(self, db_path: str = "state/vault.db", enable_embeddings: bool = True):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(self.db_path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._init_schema()
        self.embedder = _try_load_embedder() if enable_embeddings else NullEmbedder()
        self._worm_seq = self._last_worm_seq()

    def _init_schema(self):
        self._conn.executescript("""
            -- Main entries table
            CREATE TABLE IF NOT EXISTS vault_entries (
                id TEXT PRIMARY KEY,
                entry_type TEXT NOT NULL,
                data_json TEXT NOT NULL DEFAULT '{}',
                tags_json TEXT NOT NULL DEFAULT '[]',
                source TEXT NOT NULL DEFAULT 'unknown',
                confidence REAL NOT NULL DEFAULT 1.0,
                embedding_json TEXT DEFAULT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                worm_hash TEXT NOT NULL
            );

            -- FTS5 virtual table for full-text search
            CREATE VIRTUAL TABLE IF NOT EXISTS vault_fts USING fts5(
                id,
                entry_type,
                search_text,
                tags_text,
                source,
                content='vault_entries',
                content_rowid='rowid'
            );

            -- Triggers to keep FTS in sync
            CREATE TRIGGER IF NOT EXISTS vault_ai AFTER INSERT ON vault_entries BEGIN
                INSERT INTO vault_fts(rowid, id, entry_type, search_text, tags_text, source)
                VALUES (new.rowid, new.id, new.entry_type,
                        COALESCE(new.data_json, ''), COALESCE(new.tags_json, ''), new.source);
            END;

            CREATE TRIGGER IF NOT EXISTS vault_ad AFTER DELETE ON vault_entries BEGIN
                INSERT INTO vault_fts(vault_fts, rowid, id, entry_type, search_text, tags_text, source)
                VALUES ('delete', old.rowid, old.id, old.entry_type,
                        COALESCE(old.data_json, ''), COALESCE(old.tags_json, ''), old.source);
            END;

            -- WORM journal (append-only, hash-chained)
            CREATE TABLE IF NOT EXISTS worm_journal (
                seq INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT NOT NULL,
                action TEXT NOT NULL,
                entry_type TEXT NOT NULL,
                entry_id TEXT NOT NULL,
                details TEXT NOT NULL DEFAULT '',
                prev_hash TEXT NOT NULL DEFAULT '',
                hash TEXT NOT NULL
            );

            -- Stats cache
            CREATE TABLE IF NOT EXISTS vault_meta (
                key TEXT PRIMARY KEY,
                val TEXT NOT NULL
            );
        """)
        self._conn.commit()

    # ── Core CRUD ─────────────────────────────────────────────

    def store(self, entry_type: str, data: dict[str, Any],
              tags: list[str] | None = None, source: str = "unknown",
              confidence: float = 1.0, entry_id: str | None = None) -> str:
        """
        Store an entry in the vault.

        Args:
            entry_type: Type of entry (product, lead, supplier, campaign, insight)
            data: The actual entry data
            tags: Optional tags for categorization
            source: Where this data came from
            confidence: Confidence score 0-1
            entry_id: Optional ID (auto-generated if not provided)

        Returns:
            The entry ID
        """
        # Validate with Pydantic contract
        contract = VaultEntryContract(
            entry_type=entry_type,
            data=data,
            tags=tags or [],
            source=source,
            confidence=confidence,
        )

        if not entry_id:
            entry_id = _hash_data(
                contract.entry_type,
                json.dumps(contract.data, sort_keys=True, ensure_ascii=False),
                str(time.monotonic_ns()),
            )

        now = _now_iso()
        data_json = json.dumps(contract.data, ensure_ascii=False)
        tags_json = json.dumps(contract.tags, ensure_ascii=False)

        # Generate embedding for search text
        search_text = self._extract_search_text(contract.data)
        embedding = self.embedder.embed(search_text)
        embedding_json = json.dumps(embedding) if embedding else None

        # WORM journal
        worm_hash = self._append_worm("store", contract.entry_type, entry_id,
                                       f"stored {len(data_json)} bytes from {source}")

        # Upsert
        self._conn.execute("""
            INSERT OR REPLACE INTO vault_entries
                (id, entry_type, data_json, tags_json, source, confidence,
                 embedding_json, created_at, updated_at, worm_hash)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (entry_id, contract.entry_type, data_json, tags_json, contract.source,
              contract.confidence, embedding_json, now, now, worm_hash))

        self._conn.commit()
        return entry_id

    def get(self, entry_id: str) -> Optional[VaultSearchResult]:
        """Get a single entry by ID."""
        row = self._conn.execute(
            "SELECT * FROM vault_entries WHERE id = ?", (entry_id,)
        ).fetchone()
        if not row:
            return None
        return self._row_to_result(row)

    def search(self, query: str, entry_type: str | None = None,
               tags: list[str] | None = None, source: str | None = None,
               limit: int = 10, offset: int = 0,
               use_semantic: bool = True) -> list[VaultSearchResult]:
        """
        Search the vault using FTS5 (keyword) + optional semantic search.

        Graceful degradation:
        - If embeddings available: hybrid search (keyword + semantic)
        - If embeddings unavailable: keyword-only search
        """
        results: dict[str, VaultSearchResult] = {}

        # 1. Keyword search via FTS5
        keyword_results = self._keyword_search(query, entry_type, tags, source, limit * 3)
        for r in keyword_results:
            r.rank = r.rank * 0.6  # keyword weight
            results[r.id] = r

        # 2. Semantic search (if available)
        if use_semantic:
            semantic_results = self._semantic_search(query, entry_type, limit * 2)
            for r in semantic_results:
                if r.id in results:
                    # Combine scores
                    existing = results[r.id]
                    existing.rank = existing.rank + r.rank * 0.4  # semantic weight
                else:
                    r.rank = r.rank * 0.4  # semantic weight
                    results[r.id] = r

        # Sort by rank descending
        sorted_results = sorted(results.values(), key=lambda x: x.rank, reverse=True)

        # WORM journal the search
        self._append_worm("search", entry_type or "all", "query",
                          f"q='{query[:50]}' type={entry_type} limit={limit}")

        return sorted_results[offset:offset + limit]

    def delete(self, entry_id: str) -> bool:
        """Delete an entry. Appends to WORM journal."""
        row = self._conn.execute(
            "SELECT entry_type FROM vault_entries WHERE id = ?", (entry_id,)
        ).fetchone()
        if not row:
            return False

        self._append_worm("delete", row["entry_type"], entry_id, "deleted by user")
        self._conn.execute("DELETE FROM vault_entries WHERE id = ?", (entry_id,))
        self._conn.commit()
        return True

    def count(self, entry_type: str | None = None) -> int:
        """Count entries, optionally filtered by type."""
        if entry_type:
            row = self._conn.execute(
                "SELECT COUNT(*) as c FROM vault_entries WHERE entry_type = ?",
                (entry_type,)
            ).fetchone()
        else:
            row = self._conn.execute("SELECT COUNT(*) as c FROM vault_entries").fetchone()
        return row["c"]

    def stats(self) -> VaultStats:
        """Get vault statistics."""
        total = self.count()
        by_type = {}
        by_source = {}

        for row in self._conn.execute(
            "SELECT entry_type, COUNT(*) as c FROM vault_entries GROUP BY entry_type"
        ).fetchall():
            by_type[row["entry_type"]] = row["c"]

        for row in self._conn.execute(
            "SELECT source, COUNT(*) as c FROM vault_entries GROUP BY source"
        ).fetchall():
            by_source[row["source"]] = row["c"]

        db_size = self.db_path.stat().st_size if self.db_path.exists() else 0

        oldest = self._conn.execute(
            "SELECT MIN(created_at) as d FROM vault_entries"
        ).fetchone()["d"]
        newest = self._conn.execute(
            "SELECT MAX(created_at) as d FROM vault_entries"
        ).fetchone()["d"]

        return VaultStats(
            total_entries=total,
            by_type=by_type,
            by_source=by_source,
            db_size_bytes=db_size,
            oldest_entry=oldest,
            newest_entry=newest,
        )

    def recent(self, entry_type: str | None = None, limit: int = 20) -> list[VaultSearchResult]:
        """Get recent entries, optionally filtered by type."""
        if entry_type:
            rows = self._conn.execute(
                "SELECT * FROM vault_entries WHERE entry_type = ? ORDER BY created_at DESC LIMIT ?",
                (entry_type, limit)
            ).fetchall()
        else:
            rows = self._conn.execute(
                "SELECT * FROM vault_entries ORDER BY created_at DESC LIMIT ?",
                (limit,)
            ).fetchall()
        return [self._row_to_result(r) for r in rows]

    # ── Bulk operations ───────────────────────────────────────

    def bulk_store(self, entries: list[dict]) -> list[str]:
        """Store multiple entries at once. Returns list of IDs."""
        ids = []
        for entry in entries:
            eid = self.store(
                entry_type=entry["entry_type"],
                data=entry["data"],
                tags=entry.get("tags", []),
                source=entry.get("source", "bulk_import"),
                confidence=entry.get("confidence", 1.0),
            )
            ids.append(eid)
        return ids

    def import_json_file(self, path: str, entry_type: str, source: str = "file_import") -> int:
        """
        Import a JSON file into the vault.
        Supports both array format and object format.
        """
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)

        if isinstance(data, list):
            items = data
        elif isinstance(data, dict):
            # Could be a list under a key
            for key in ("products", "leads", "items", "data", "results"):
                if key in data and isinstance(data[key], list):
                    items = data[key]
                    break
            else:
                items = [data]
        else:
            raise ValueError(f"Unsupported JSON format in {path}")

        count = 0
        for item in items:
            tags = item.pop("_tags", [])
            conf = item.pop("_confidence", 1.0)
            src = item.pop("_source", source)
            self.store(entry_type, item, tags=tags, source=src, confidence=conf)
            count += 1

        return count

    # ── WORM Journal ──────────────────────────────────────────

    def worm_chain(self, limit: int = 20) -> list[dict]:
        """Get recent WORM journal entries."""
        rows = self._conn.execute(
            "SELECT * FROM worm_journal ORDER BY seq DESC LIMIT ?",
            (limit,)
        ).fetchall()
        return [dict(r) for r in rows]

    def verify_worm_chain(self) -> tuple[bool, str]:
        """Verify the integrity of the WORM journal chain."""
        rows = self._conn.execute(
            "SELECT seq, hash, prev_hash FROM worm_journal ORDER BY seq ASC"
        ).fetchall()

        if not rows:
            return True, "Empty chain — valid"

        prev_hash = ""
        for i, row in enumerate(rows):
            if i > 0 and row["prev_hash"] != prev_hash:
                return False, f"Chain broken at seq {row['seq']}: expected prev_hash={prev_hash}, got {row['prev_hash']}"
            prev_hash = row["hash"]

        return True, f"Chain intact — {len(rows)} entries verified"

    # ── Internal helpers ──────────────────────────────────────

    def _keyword_search(self, query: str, entry_type: str | None,
                        tags: list[str] | None, source: str | None,
                        limit: int) -> list[VaultSearchResult]:
        """FTS5 full-text search."""
        # Escape FTS5 special characters
        clean_query = query.replace('"', '""')

        # Build FTS5 query
        fts_query = f'"{clean_query}"'

        # Use MATCH on the FTS table with filtering
        sql_parts = ["""
            SELECT v.*, ft.rank as fts_rank
            FROM vault_fts ft
            JOIN vault_entries v ON ft.id = v.id
            WHERE ft.vault_fts MATCH ?
        """]
        params: list[Any] = [fts_query]

        if entry_type:
            sql_parts.append("AND v.entry_type = ?")
            params.append(entry_type)

        if source:
            sql_parts.append("AND v.source = ?")
            params.append(source)

        sql_parts.append("ORDER BY ft.rank DESC LIMIT ?")
        params.append(limit)

        try:
            rows = self._conn.execute(" ".join(sql_parts), params).fetchall()
        except sqlite3.OperationalError:
            # FTS5 query syntax error — fall back to LIKE
            rows = self._like_search(query, entry_type, limit)

        results = []
        for row in rows:
            r = self._row_to_result(row)
            # Normalize FTS rank to 0-1
            raw_rank = row["fts_rank"] if "fts_rank" in row.keys() else 0
            r.rank = min(1.0, max(0.0, (raw_rank + 10) / 20))  # FTS5 rank can be negative
            results.append(r)

        return results

    def _like_search(self, query: str, entry_type: str | None,
                     limit: int) -> list[sqlite3.Row]:
        """Fallback LIKE search when FTS5 fails."""
        sql = "SELECT * FROM vault_entries WHERE data_json LIKE ?"
        params: list[Any] = [f"%{query}%"]

        if entry_type:
            sql += " AND entry_type = ?"
            params.append(entry_type)

        sql += " LIMIT ?"
        params.append(limit)

        return self._conn.execute(sql, params).fetchall()

    def _semantic_search(self, query: str, entry_type: str | None,
                         limit: int) -> list[VaultSearchResult]:
        """
        Semantic search using embeddings.
        Returns empty list if embeddings are unavailable (graceful degradation).
        """
        query_vec = self.embedder.embed(query)
        if not query_vec:
            return []

        # Load all entries with embeddings
        if entry_type:
            rows = self._conn.execute(
                "SELECT * FROM vault_entries WHERE embedding_json IS NOT NULL AND entry_type = ?",
                (entry_type,)
            ).fetchall()
        else:
            rows = self._conn.execute(
                "SELECT * FROM vault_entries WHERE embedding_json IS NOT NULL"
            ).fetchall()

        if not rows:
            return []

        # Compute similarities
        scored: list[tuple[float, sqlite3.Row]] = []
        for row in rows:
            try:
                entry_vec = json.loads(row["embedding_json"])
                if not entry_vec:
                    continue
                sim = self.embedder.similarity(query_vec, entry_vec)
                if sim > 0.1:  # Minimum similarity threshold
                    scored.append((sim, row))
            except (json.JSONDecodeError, TypeError):
                continue

        # Sort by similarity descending
        scored.sort(key=lambda x: x[0], reverse=True)

        results = []
        for sim, row in scored[:limit]:
            r = self._row_to_result(row)
            r.rank = sim
            results.append(r)

        return results

    def _extract_search_text(self, data: dict[str, Any]) -> str:
        """Extract searchable text from data dict."""
        parts = []
        for key, value in data.items():
            if key.startswith("_"):
                continue
            if isinstance(value, str):
                parts.append(value)
            elif isinstance(value, (list, tuple)):
                parts.extend(str(v) for v in value if isinstance(v, str))
            elif isinstance(value, dict):
                parts.extend(str(v) for v in value.values() if isinstance(v, str))
        return " ".join(parts)[:2000]

    def _row_to_result(self, row: sqlite3.Row) -> VaultSearchResult:
        """Convert a database row to a VaultSearchResult."""
        data = json.loads(row["data_json"]) if row["data_json"] else {}
        tags = json.loads(row["tags_json"]) if row["tags_json"] else []
        return VaultSearchResult(
            id=row["id"],
            entry_type=row["entry_type"],
            data=data,
            tags=tags,
            source=row["source"],
            confidence=row["confidence"],
            rank=0.0,
            created_at=row["created_at"],
            worm_hash=row["worm_hash"],
        )

    def _last_worm_seq(self) -> int:
        """Get the last WORM journal sequence number."""
        row = self._conn.execute(
            "SELECT MAX(seq) as s FROM worm_journal"
        ).fetchone()
        return row["s"] or 0

    def _append_worm(self, action: str, entry_type: str, entry_id: str,
                     details: str) -> str:
        """Append to the WORM journal and return the new hash."""
        seq = self._last_worm_seq() + 1
        now = _now_iso()

        # Get previous hash
        prev_row = self._conn.execute(
            "SELECT hash FROM worm_journal WHERE seq = ?", (seq - 1,)
        ).fetchone()
        prev_hash = prev_row["hash"] if prev_row else "genesis"

        # Compute hash (chain: prev_hash + current data)
        current_hash = _hash_data(str(seq), now, action, entry_type, entry_id, prev_hash)

        self._conn.execute("""
            INSERT INTO worm_journal (seq, timestamp, action, entry_type, entry_id, details, prev_hash, hash)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (seq, now, action, entry_type, entry_id, details[:500], prev_hash, current_hash))
        self._conn.commit()

        return current_hash

    def close(self):
        """Close the database connection."""
        self._conn.close()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()


# ── CLI ────────────────────────────────────────────────────────

def main():
    """CLI interface for the Knowledge Vault."""
    import sys

    if len(sys.argv) < 2:
        print("Usage: python knowledge_vault.py <command> [args]")
        print("Commands: status, search <query>, recent [type], import <file> [type], verify, stats")
        return

    cmd = sys.argv[1]
    vault = KnowledgeVault()

    try:
        if cmd == "status" or cmd == "stats":
            s = vault.stats()
            print(f"  Knowledge Vault: {s.total_entries} entries")
            print(f"  DB size: {s.db_size_bytes / 1024:.1f} KB")
            print(f"  Oldest: {s.oldest_entry or 'N/A'}")
            print(f"  Newest: {s.newest_entry or 'N/A'}")
            if s.by_type:
                print("  By type:")
                for t, c in sorted(s.by_type.items(), key=lambda x: -x[1]):
                    print(f"    {t}: {c}")
            if s.by_source:
                print("  By source:")
                for src, c in sorted(s.by_source.items(), key=lambda x: -x[1]):
                    print(f"    {src}: {c}")

        elif cmd == "search":
            query = " ".join(sys.argv[2:]) if len(sys.argv) > 2 else ""
            if not query:
                print("Usage: search <query>")
                return
            results = vault.search(query, limit=10)
            print(f"  Search '{query}': {len(results)} results")
            for r in results:
                name = r.data.get("name") or r.data.get("title") or r.data.get("company") or r.id
                print(f"    [{r.entry_type}] {name} (rank={r.rank:.3f}, conf={r.confidence})")

        elif cmd == "recent":
            entry_type = sys.argv[2] if len(sys.argv) > 2 else None
            entries = vault.recent(entry_type=entry_type, limit=10)
            for r in entries:
                name = r.data.get("name") or r.data.get("title") or r.data.get("company") or r.id
                print(f"  [{r.entry_type}] {name} ({r.created_at})")

        elif cmd == "import":
            path = sys.argv[2] if len(sys.argv) > 2 else ""
            entry_type = sys.argv[3] if len(sys.argv) > 3 else "product"
            if not path:
                print("Usage: import <file> [type]")
                return
            count = vault.import_json_file(path, entry_type)
            print(f"  Imported {count} entries as '{entry_type}'")

        elif cmd == "verify":
            valid, msg = vault.verify_worm_chain()
            status = "✅ VALID" if valid else "❌ BROKEN"
            print(f"  WORM chain: {status} — {msg}")

        elif cmd == "worm":
            entries = vault.worm_chain(limit=20)
            print(f"  WORM Journal (last {len(entries)} entries):")
            for e in entries:
                print(f"    #{e['seq']} [{e['action']}] {e['entry_type']}:{e['entry_id']} — {e['timestamp']}")
                if e['details']:
                    print(f"      {e['details'][:80]}")

        else:
            print(f"Unknown command: {cmd}")

    finally:
        vault.close()


if __name__ == "__main__":
    main()
