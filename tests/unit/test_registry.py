"""
Unit tests for ToolRegistry.
"""
from typing import Any

import pytest

from ghost.constants import TOOLS_DIR
from ghost.synthesis.registry import ToolRegistry


class MockWriter:
    """Mock DatabaseWriter + Connection for testing."""
    
    def __init__(self) -> None:
        self.written: list[tuple[str, tuple[Any, ...]]] = []
        
        class MockCursor:
            def __init__(self, rows: list[dict[str, Any]]):
                self.rows = rows
            
            async def fetchall(self) -> list[dict[str, Any]]:
                return self.rows
            
            async def fetchone(self) -> dict[str, Any] | None:
                return self.rows[0] if self.rows else None
        
        class MockDB:
            def __init__(self, parent: "MockWriter"):
                self.parent = parent
            
            async def execute(self, sql: str, params: tuple[Any, ...] = ()) -> MockCursor:
                if "JOIN tool_current" in sql:
                    # Mock for get_current
                    return MockCursor([{
                        "id": "id-123",
                        "name": "test_tool",
                        "file_path": "/tmp/tools/test_tool.py",
                        "version": 1,
                        "status": "registered"
                    }])
                elif "SELECT * FROM tools" in sql:
                    if tuple(params) == ("id-123",):
                        return MockCursor([{
                            "id": "id-123",
                            "name": "test_tool",
                            "file_path": "/tmp/quarantine/test_tool.py",
                            "version": 1,
                            "status": "approved"
                        }])
                    return MockCursor([{
                        "id": "id-123",
                        "name": "test_tool",
                        "file_path": "/tmp/tools/test_tool.py",
                        "version": 1,
                        "status": "registered"
                    }])
                return MockCursor([])
                
        self.db = MockDB(self)
    
    async def write(self, sql: str, params: tuple[Any, ...] = ()) -> None:
        self.written.append((sql, params))


@pytest.fixture
def registry(tmp_path):
    writer = MockWriter()
    return ToolRegistry(ghost_home=tmp_path, db=writer.db, writer=writer)


@pytest.mark.asyncio
async def test_register_moves_file(registry, tmp_path):
    """register() moves file from quarantine to tools dir."""
    # Setup mock file
    q_dir = tmp_path / "quarantine"
    q_dir.mkdir()
    q_file = q_dir / "test_tool.py"
    q_file.write_text("code")
    
    # Overwrite db mock specifically for this file path
    class SpecificDB:
        async def execute(self, sql: str, params: tuple[Any, ...] = ()):
            class Cursor:
                async def fetchone(self):
                    return {
                        "id": "id-123",
                        "name": "test_tool",
                        "file_path": str(q_file),
                        "version": 1,
                        "status": "approved"
                    }
            return Cursor()
    registry.db = SpecificDB()

    res = await registry.register("id-123")
    
    assert res is not None
    assert res["status"] == "registered"
    assert tmp_path.name in res["file_path"]

    # File should exist in tools_dir
    dest_file = tmp_path / TOOLS_DIR / q_file.name
    assert dest_file.exists()
    assert dest_file.read_text() == "code"


@pytest.mark.asyncio
async def test_get_current(registry):
    """get_current() returns the current version."""
    res = await registry.get_current("test_tool")
    assert res is not None
    assert res["name"] == "test_tool"
    assert res["status"] == "registered"


@pytest.mark.asyncio
async def test_list_all(registry):
    """list_all() returns all tools."""
    res = await registry.list_all()
    assert len(res) == 1
    assert res[0]["name"] == "test_tool"


@pytest.mark.asyncio
async def test_record_run(registry):
    """record_run() increments counter."""
    await registry.record_run("id-123")
    writer = registry.writer
    sql, params = writer.written[0]
    assert "UPDATE tools SET runs = runs + 1" in sql
    assert params[0] == "id-123"


@pytest.mark.asyncio
async def test_delete_removes_pointers(registry, tmp_path):
    """delete() removes file and DB record."""
    # First create a mock file
    file_path = tmp_path / "test_tool.py"
    file_path.touch()
    
    class SpecificDB:
        async def execute(self, sql: str, params: tuple[Any, ...] = ()):
            class Cursor:
                async def fetchone(self):
                    return {"id": "id-123", "name": "test_tool", "file_path": str(file_path), "status": "registered", "version": 1}
            return Cursor()
    registry.db = SpecificDB()
    
    await registry.delete("id-123")
    
    assert not file_path.exists()
    
    writer = registry.writer
    assert any("DELETE FROM tool_current" in s for s, p in writer.written)
    assert any("DELETE FROM tools" in s for s, p in writer.written)
