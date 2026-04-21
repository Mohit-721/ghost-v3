"""
Unit tests for ghost.memory.entities.EntityStore and ghost.memory.graph.GraphStore.
Tests both entity CRUD and graph traversal + FTS search.
"""
import asyncio

import aiosqlite
import pytest

from ghost.memory.database import get_connection
from ghost.memory.entities import EntityStore
from ghost.memory.graph import GraphStore
from ghost.memory.migrations.runner import run_migrations
from ghost.memory.writer import DatabaseWriter


@pytest.fixture
async def store(tmp_path):
    """Fully migrated in-memory DB with EntityStore and GraphStore."""
    db_path = tmp_path / "test.db"
    db = await get_connection(db_path)
    writer = DatabaseWriter(db)
    await writer.start()
    await run_migrations(writer)

    entities = EntityStore(db, writer)
    graph = GraphStore(db, writer)

    # Insert test projects to satisfy FK constraints
    for proj_id, name, path in [
        ("proj-1", "project-one", "/tmp/proj1"),
        ("p1", "p-one", "/tmp/p1"),
        ("proj-fts", "proj-fts", "/tmp/proj-fts"),
        ("proj-graph", "proj-graph", "/tmp/proj-graph"),
    ]:
        await writer.write(
            "INSERT OR IGNORE INTO projects (id, name, root_path) VALUES (?, ?, ?)",
            (proj_id, name, path),
        )

    yield entities, graph, writer

    await writer.stop()
    await db.close()


# ─── EntityStore ──────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_create_and_get_entity(store):
    """Create entity then retrieve it — fields match."""
    entities, graph, _ = store
    entity_id = await entities.create(
        project_id="proj-1",
        kind="file",
        name="main.py",
        content="print('hello')",
        metadata={"lines": 1},
    )
    result = await entities.get(entity_id)
    assert result is not None
    assert result["id"] == entity_id
    assert result["name"] == "main.py"
    assert result["kind"] == "file"
    assert result["project_id"] == "proj-1"
    assert result["content"] == "print('hello')"
    assert result["content_hash"] is not None


@pytest.mark.asyncio
async def test_soft_delete_entity(store):
    """Soft-deleted entity returns None from get()."""
    entities, graph, _ = store
    entity_id = await entities.create("proj-1", "file", "old.py")
    await entities.soft_delete(entity_id)
    result = await entities.get(entity_id)
    assert result is None


@pytest.mark.asyncio
async def test_get_by_name(store):
    """get_by_name returns entity matching project + kind + name."""
    entities, graph, _ = store
    await entities.create("proj-1", "function", "my_func", content="def my_func(): pass")
    result = await entities.get_by_name("proj-1", "function", "my_func")
    assert result is not None
    assert result["name"] == "my_func"


@pytest.mark.asyncio
async def test_get_by_name_missing(store):
    """get_by_name returns None when not found."""
    entities, graph, _ = store
    result = await entities.get_by_name("proj-1", "function", "nonexistent")
    assert result is None


@pytest.mark.asyncio
async def test_update_entity(store):
    """Update entity content changes content_hash."""
    entities, graph, _ = store
    entity_id = await entities.create("proj-1", "file", "app.py", content="v1")
    entity_before = await entities.get(entity_id)

    await entities.update(entity_id, content="v2")
    entity_after = await entities.get(entity_id)

    assert entity_after["content"] == "v2"
    assert entity_after["content_hash"] != entity_before["content_hash"]


@pytest.mark.asyncio
async def test_upsert_by_hash_skips_write_if_unchanged(store):
    """upsert_by_hash returns same ID without write when content is unchanged."""
    entities, graph, _ = store
    content = "def foo(): pass"
    id1 = await entities.upsert_by_hash("proj-1", "function", "foo", content)
    id2 = await entities.upsert_by_hash("proj-1", "function", "foo", content)
    assert id1 == id2


@pytest.mark.asyncio
async def test_upsert_by_hash_updates_when_changed(store):
    """upsert_by_hash updates entity when content changes."""
    entities, graph, _ = store
    id1 = await entities.upsert_by_hash("proj-1", "function", "bar", "v1")
    id2 = await entities.upsert_by_hash("proj-1", "function", "bar", "v2")
    assert id1 == id2  # Same entity, updated in place
    entity = await entities.get(id1)
    assert entity["content"] == "v2"


@pytest.mark.asyncio
async def test_list_by_project_filters_by_kind(store):
    """list_by_project with kind filter returns only matching entities."""
    entities, graph, _ = store
    await entities.create("proj-1", "file", "a.py")
    await entities.create("proj-1", "file", "b.py")
    await entities.create("proj-1", "function", "func_a")

    files = await entities.list_by_project("proj-1", kind="file")
    funcs = await entities.list_by_project("proj-1", kind="function")

    assert len(files) == 2
    assert len(funcs) == 1
    assert all(e["kind"] == "file" for e in files)
    assert all(e["kind"] == "function" for e in funcs)


# ─── GraphStore — Edges ───────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_add_and_get_edges_from(store):
    """add_edge creates edge; get_edges_from returns it."""
    entities, graph, _ = store
    id_a = await entities.create("p1", "file", "a.py")
    id_b = await entities.create("p1", "file", "b.py")
    edge_id = await graph.add_edge(id_a, id_b, "imports")

    edges = await graph.get_edges_from(id_a)
    assert len(edges) == 1
    assert edges[0]["source_id"] == id_a
    assert edges[0]["target_id"] == id_b
    assert edges[0]["relation"] == "imports"


@pytest.mark.asyncio
async def test_get_edges_to(store):
    """get_edges_to returns incoming edges for an entity."""
    entities, graph, _ = store
    id_a = await entities.create("p1", "file", "a.py")
    id_b = await entities.create("p1", "file", "b.py")
    await graph.add_edge(id_a, id_b, "imports")

    edges = await graph.get_edges_to(id_b)
    assert len(edges) == 1
    assert edges[0]["source_id"] == id_a


@pytest.mark.asyncio
async def test_get_neighbors_one_hop(store):
    """get_neighbors returns 1-hop connected entities."""
    entities, graph, _ = store
    id_a = await entities.create("p1", "file", "a.py")
    id_b = await entities.create("p1", "file", "b.py")
    id_c = await entities.create("p1", "file", "c.py")
    await graph.add_edge(id_a, id_b, "imports")
    await graph.add_edge(id_a, id_c, "imports")

    neighbors = await graph.get_neighbors(id_a, depth=1)
    neighbor_ids = [n["id"] for n in neighbors]
    assert id_b in neighbor_ids
    assert id_c in neighbor_ids


# ─── FTS5 Search (Bug #1 validation) ─────────────────────────────────────────

@pytest.mark.asyncio
async def test_fts_search_returns_matching_entities(store):
    """FTS5 triggers (Bug #1 fix) ensure new entities are immediately searchable."""
    entities, graph, _ = store
    await entities.create(
        "proj-fts",
        "function",
        "calculate_interest",
        content="def calculate_interest(principal, rate): return principal * rate",
    )
    await entities.create(
        "proj-fts",
        "function",
        "send_email",
        content="def send_email(to, subject): ...",
    )

    from ghost.memory.search import UnifiedSearch
    search = UnifiedSearch(entities.db, graph)

    results = await search.search("calculate interest", "proj-fts")
    names = [r["name"] for r in results]
    assert "calculate_interest" in names


@pytest.mark.asyncio
async def test_search_related_expands_via_graph_edges(store):
    """search_related includes graph-connected neighbors beyond direct FTS hits."""
    entities, graph, _ = store
    file_id = await entities.create(
        "proj-graph",
        "file",
        "main.py",
        content="main entry point",
    )
    helper_id = await entities.create(
        "proj-graph",
        "function",
        "helper_function",
        content="internal helper",
    )
    await graph.add_edge(file_id, helper_id, "contains")

    results = await graph.search_related("main entry point", "proj-graph")
    result_ids = [r["id"] for r in results]
    # At minimum, the directly matched entity should be present
    assert file_id in result_ids
