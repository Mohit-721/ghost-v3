"""
Unit tests for QuarantineManager.
"""
from typing import Any

import pytest

from ghost.constants import QUARANTINE_DIR
from ghost.synthesis.quarantine import QuarantineManager


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
                if "status = 'quarantined'" in sql and "SELECT" in sql:
                    # Mock response for list_pending / get
                    return MockCursor([{
                        "id": params[0] if params else "id-123",
                        "name": "test_tool",
                        "file_path": "/tmp/quarantine/test_tool.py",
                        "status": "quarantined"
                    }])
                return MockCursor([])
                
        self.db = MockDB(self)
    
    async def write(self, sql: str, params: tuple[Any, ...] = ()) -> None:
        self.written.append((sql, params))


@pytest.fixture
def quarantine(tmp_path):
    writer = MockWriter()
    return QuarantineManager(ghost_home=tmp_path, writer=writer)


@pytest.mark.asyncio
async def test_add_creates_file(quarantine, tmp_path):
    """add() creates file in quarantine directory with PEP 723 header."""
    res = await quarantine.add(
        name="test_tool",
        description="A test tool",
        code="def main(): return 42"
    )
    
    file_path = tmp_path / QUARANTINE_DIR / Path(res["file_path"]).name
    assert file_path.exists()
    
    content = file_path.read_text()
    assert "# /// script" in content
    assert "def main(): return 42" in content


@pytest.mark.asyncio
async def test_add_registers_tool(quarantine):
    """add() registers tool in DB with status='quarantined'."""
    await quarantine.add(
        name="test_tool",
        description="A test tool",
        code="def main(): return 42"
    )
    
    writer = quarantine.writer
    assert len(writer.written) == 1
    sql, params = writer.written[0]
    assert "INSERT INTO tools" in sql
    assert params[1] == "test_tool"
    assert "quarantined" in sql


@pytest.mark.asyncio
async def test_approve_changes_status(quarantine):
    """approve() changes status to 'approved'."""
    await quarantine.approve("id-123")
    
    writer = quarantine.writer
    sql, params = writer.written[0]
    assert "UPDATE tools SET status = 'approved'" in sql
    assert params[0] == "id-123"


@pytest.mark.asyncio
async def test_reject_deletes_file_and_record(quarantine, tmp_path):
    """reject() deletes file and DB record."""
    # First create a mock file
    file_path = tmp_path / "test_tool.py"
    file_path.touch()
    
    # Overwrite the db mock to return this file path
    class SpecificMockDB:
        async def execute(self, sql: str, params: tuple[Any, ...] = ()): ...

    async def mock_execute(sql: str, params: tuple[Any, ...] = ()):
        class MockCursor:
            async def fetchone(self):
                return {"id": "id-123", "name": "test_tool", "file_path": str(file_path), "status": "quarantined"}
        return MockCursor()
    
    quarantine.writer.db.execute = mock_execute
    
    await quarantine.reject("id-123")
    
    assert not file_path.exists()
    
    writer = quarantine.writer
    sql, params = writer.written[0]
    assert "DELETE FROM tools WHERE id = ?" in sql
    assert params[0] == "id-123"

from pathlib import Path
