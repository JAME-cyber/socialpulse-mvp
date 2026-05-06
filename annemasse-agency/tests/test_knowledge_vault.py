"""
Tests for Knowledge Vault — Skill #12 (RAG / Knowledge).
Skill #6 (Evals) — 25 tests covering all vault operations.

Tests use a temporary database and do NOT touch production state.
"""

import json
import os
import tempfile
from pathlib import Path

import pytest

from knowledge_vault import (
    KnowledgeVault,
    NullEmbedder,
    VaultEntryContract,
    VaultSearchResult,
    VaultStats,
    WormEntry,
    _hash_data,
    _now_iso,
)


@pytest.fixture
def vault(tmp_path):
    """Create a temporary vault for testing."""
    db_path = str(tmp_path / "test_vault.db")
    v = KnowledgeVault(db_path, enable_embeddings=False)  # No embeddings for speed
    yield v
    v.close()


@pytest.fixture
def populated_vault(vault):
    """Vault with sample data."""
    # Products
    vault.store("product", {"name": "Posture Corrector", "price": 12.99, "source_price": 3.50},
                tags=["health", "trending"], source="aliexpress", confidence=0.9)
    vault.store("product", {"name": "Car Phone Mount", "price": 15.99, "source_price": 4.00},
                tags=["automotive", "hot"], source="1688", confidence=0.85)
    vault.store("product", {"name": "Ice Roller Face", "price": 8.99, "source_price": 1.50},
                tags=["beauty", "viral"], source="aliexpress", confidence=0.95)

    # Suppliers
    vault.store("supplier", {"name": "CJ Dropshipping", "product": "Posture Corrector", "price": 4.50},
                tags=["verified"], source="scout", confidence=0.8)
    vault.store("supplier", {"name": "AliExpress Direct", "product": "Car Phone Mount", "price": 4.00},
                tags=[], source="scout", confidence=0.7)

    # Leads
    vault.store("lead", {"name": "Restaurant Le Lac", "city": "Annemasse", "sector": "restaurant"},
                tags=["hot", "restaurant"], source="overpass", confidence=0.75)
    vault.store("lead", {"name": "Maître Dupont", "city": "Gaillard", "sector": "avocat"},
                tags=["avocat"], source="overpass", confidence=0.8)

    return vault


# ── Contract Tests (Skill #2) ──────────────────────────────────

class TestVaultEntryContract:
    def test_valid_entry(self):
        c = VaultEntryContract(entry_type="product", data={"name": "Test"})
        assert c.entry_type == "product"
        assert c.data == {"name": "Test"}
        assert c.tags == []
        assert c.source == "unknown"
        assert c.confidence == 1.0

    def test_invalid_entry_type_rejected(self):
        with pytest.raises(Exception):
            VaultEntryContract(entry_type="invalid_type", data={})

    def test_valid_entry_types(self):
        for t in ["product", "lead", "supplier", "campaign", "insight", "feedback", "market", "creative"]:
            c = VaultEntryContract(entry_type=t, data={})
            assert c.entry_type == t

    def test_tags_normalized(self):
        c = VaultEntryContract(entry_type="product", data={}, tags=["  HEALTH  ", "Beauty ", ""])
        assert c.tags == ["health", "beauty"]

    def test_confidence_bounds(self):
        with pytest.raises(Exception):
            VaultEntryContract(entry_type="product", data={}, confidence=1.5)
        with pytest.raises(Exception):
            VaultEntryContract(entry_type="product", data={}, confidence=-0.1)

    def test_empty_entry_type_rejected(self):
        with pytest.raises(Exception):
            VaultEntryContract(entry_type="", data={})

    def test_large_tags_list_rejected(self):
        with pytest.raises(Exception):
            VaultEntryContract(entry_type="product", data={}, tags=[f"tag{i}" for i in range(25)])


# ── Core CRUD Tests ────────────────────────────────────────────

class TestStoreAndGet:
    def test_store_returns_id(self, vault):
        eid = vault.store("product", {"name": "Test Product"})
        assert isinstance(eid, str)
        assert len(eid) > 0

    def test_store_and_get(self, vault):
        eid = vault.store("product", {"name": "Test Product", "price": 9.99},
                          tags=["test"], source="unit_test", confidence=0.8)
        result = vault.get(eid)
        assert result is not None
        assert result.data["name"] == "Test Product"
        assert result.data["price"] == 9.99
        assert result.tags == ["test"]
        assert result.source == "unit_test"
        assert result.confidence == 0.8
        assert result.entry_type == "product"

    def test_get_nonexistent_returns_none(self, vault):
        result = vault.get("nonexistent_id")
        assert result is None

    def test_store_with_custom_id(self, vault):
        eid = vault.store("product", {"name": "Custom"}, entry_id="my_custom_id")
        assert eid == "my_custom_id"
        result = vault.get("my_custom_id")
        assert result is not None

    def test_upsert_replaces(self, vault):
        eid = vault.store("product", {"name": "V1"}, entry_id="upsert_test")
        vault.store("product", {"name": "V2"}, entry_id="upsert_test")
        result = vault.get("upsert_test")
        assert result.data["name"] == "V2"

    def test_count(self, populated_vault):
        assert populated_vault.count() == 7
        assert populated_vault.count("product") == 3
        assert populated_vault.count("supplier") == 2
        assert populated_vault.count("lead") == 2

    def test_delete(self, populated_vault):
        total_before = populated_vault.count()
        results = populated_vault.search("Posture Corrector", limit=1)
        assert len(results) == 1
        eid = results[0].id
        deleted = populated_vault.delete(eid)
        assert deleted
        assert populated_vault.count() == total_before - 1
        assert populated_vault.get(eid) is None

    def test_delete_nonexistent(self, vault):
        assert vault.delete("nonexistent") is False


# ── Search Tests ───────────────────────────────────────────────

class TestSearch:
    def test_keyword_search_finds_match(self, populated_vault):
        results = populated_vault.search("Posture Corrector")
        assert len(results) > 0
        assert any("Posture" in r.data.get("name", "") for r in results)

    def test_search_by_type(self, populated_vault):
        results = populated_vault.search("a", entry_type="product")
        assert all(r.entry_type == "product" for r in results)

    def test_search_limit(self, populated_vault):
        results = populated_vault.search("a", limit=2)
        assert len(results) <= 2

    def test_search_empty_query(self, vault):
        results = vault.search("")
        # Empty query may return nothing or everything depending on FTS
        assert isinstance(results, list)

    def test_search_no_results(self, vault):
        results = vault.search("xyznonexistent123")
        assert results == []

    def test_search_ranked(self, populated_vault):
        results = populated_vault.search("Posture")
        if len(results) > 1:
            assert results[0].rank >= results[-1].rank

    def test_search_restaurant(self, populated_vault):
        results = populated_vault.search("restaurant")
        assert len(results) > 0
        assert any("Restaurant" in r.data.get("name", "") for r in results)


# ── Recent / Stats Tests ──────────────────────────────────────

class TestRecentAndStats:
    def test_recent_returns_latest(self, populated_vault):
        recent = populated_vault.recent(limit=3)
        assert len(recent) <= 3

    def test_recent_by_type(self, populated_vault):
        recent = populated_vault.recent(entry_type="lead", limit=5)
        assert all(r.entry_type == "lead" for r in recent)

    def test_stats(self, populated_vault):
        stats = populated_vault.stats()
        assert isinstance(stats, VaultStats)
        assert stats.total_entries == 7
        assert "product" in stats.by_type
        assert stats.by_type["product"] == 3
        assert stats.db_size_bytes > 0


# ── Bulk Operations Tests ──────────────────────────────────────

class TestBulkOperations:
    def test_bulk_store(self, vault):
        entries = [
            {"entry_type": "product", "data": {"name": f"Product {i}"}}
            for i in range(5)
        ]
        ids = vault.bulk_store(entries)
        assert len(ids) == 5
        assert vault.count() == 5

    def test_import_json_array(self, vault, tmp_path):
        data = [{"name": "Item 1"}, {"name": "Item 2"}]
        path = tmp_path / "test.json"
        path.write_text(json.dumps(data))
        count = vault.import_json_file(str(path), "product")
        assert count == 2

    def test_import_json_dict_with_key(self, vault, tmp_path):
        data = {"products": [{"name": "A"}, {"name": "B"}]}
        path = tmp_path / "test2.json"
        path.write_text(json.dumps(data))
        count = vault.import_json_file(str(path), "product")
        assert count == 2


# ── WORM Journal Tests ────────────────────────────────────────

class TestWORMJournal:
    def test_worm_chain_integrity(self, populated_vault):
        valid, msg = populated_vault.verify_worm_chain()
        assert valid, msg

    def test_worm_entries_created(self, vault):
        vault.store("product", {"name": "Test"})
        chain = vault.worm_chain(limit=5)
        assert len(chain) > 0
        assert chain[0]["action"] in ("store", "search", "delete")

    def test_worm_hash_chain(self, vault):
        # Store multiple entries and verify chain
        vault.store("product", {"name": "A"})
        vault.store("product", {"name": "B"})
        vault.store("product", {"name": "C"})
        valid, msg = vault.verify_worm_chain()
        assert valid, msg

    def test_worm_search_logged(self, vault):
        vault.store("product", {"name": "Test"})
        vault.search("Test")
        chain = vault.worm_chain(limit=5)
        actions = [e["action"] for e in chain]
        assert "search" in actions

    def test_worm_delete_logged(self, vault):
        eid = vault.store("product", {"name": "ToDelete"})
        vault.delete(eid)
        chain = vault.worm_chain(limit=5)
        actions = [e["action"] for e in chain]
        assert "delete" in actions

    def test_empty_vault_valid_chain(self, vault):
        valid, msg = vault.verify_worm_chain()
        assert valid


# ── Embedder Tests ─────────────────────────────────────────────

class TestEmbedder:
    def test_null_embedder_returns_empty(self):
        ne = NullEmbedder()
        assert ne.embed("test") == []
        assert ne.similarity([], []) == 0.0

    def test_null_embedder_similarity(self):
        ne = NullEmbedder()
        assert ne.similarity([1.0, 2.0], [3.0, 4.0]) == 0.0
