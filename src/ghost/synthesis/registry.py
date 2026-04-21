"""
Tool registry — versioned storage for approved tools.

Supports multiple versions of the same tool name.
Each tool name has a "current version" pointer.
"""
import logging
import shutil
from pathlib import Path
from typing import Any

from ghost.constants import TOOLS_DIR

logger = logging.getLogger(__name__)


class ToolRegistry:
    """Manages registered (approved) tools."""

    def __init__(self, ghost_home: Path, db: Any, writer: Any) -> None:
        self.tools_dir = ghost_home / TOOLS_DIR
        self.tools_dir.mkdir(parents=True, exist_ok=True)
        self.db = db
        self.writer = writer

    async def register(self, tool_id: str) -> dict[str, Any] | None:
        """
        Register a tool (move from quarantined/approved to registered).
        Copies the tool file from quarantine to tools dir.
        Updates the current version pointer.
        """
        cursor = await self.db.execute(
            "SELECT * FROM tools WHERE id = ?", (tool_id,)
        )
        tool_row = await cursor.fetchone()
        if not tool_row:
            return None

        tool = dict(tool_row)

        # Copy file to tools directory
        src = Path(tool["file_path"])
        dst = self.tools_dir / src.name
        if src.exists():
            shutil.copy2(str(src), str(dst))
            # Update file_path
            await self.writer.write(
                "UPDATE tools SET file_path = ?, status = 'registered' WHERE id = ?",
                (str(dst), tool_id)
            )

        # Update current version pointer
        await self.writer.write(
            """INSERT OR REPLACE INTO tool_current (name, current_version_id)
               VALUES (?, ?)""",
            (tool["name"], tool_id)
        )

        logger.info(f"Tool '{tool['name']}' v{tool['version']} registered")
        tool["file_path"] = str(dst)
        tool["status"] = "registered"
        return tool

    async def get_current(self, name: str) -> dict[str, Any] | None:
        """Get the current version of a tool by name."""
        cursor = await self.db.execute(
            """SELECT t.* FROM tools t
               JOIN tool_current tc ON t.id = tc.current_version_id
               WHERE tc.name = ?""",
            (name,)
        )
        row = await cursor.fetchone()
        return dict(row) if row else None

    async def get_by_id(self, tool_id: str) -> dict[str, Any] | None:
        """Get a tool by its ID."""
        cursor = await self.db.execute("SELECT * FROM tools WHERE id = ?", (tool_id,))
        row = await cursor.fetchone()
        return dict(row) if row else None

    async def list_all(self, status: str | None = None) -> list[dict[str, Any]]:
        """List all tools, optionally filtered by status."""
        if status:
            cursor = await self.db.execute(
                "SELECT * FROM tools WHERE status = ? ORDER BY name, version DESC",
                (status,)
            )
        else:
            cursor = await self.db.execute(
                "SELECT * FROM tools ORDER BY name, version DESC"
            )
        return [dict(r) for r in await cursor.fetchall()]

    async def record_run(self, tool_id: str) -> None:
        """Increment run counter and update last_run_at."""
        await self.writer.write(
            """UPDATE tools SET runs = runs + 1, last_run_at = datetime('now')
               WHERE id = ?""",
            (tool_id,)
        )

    async def delete(self, tool_id: str) -> bool:
        """Delete a tool (file + DB record)."""
        tool = await self.get_by_id(tool_id)
        if not tool:
            return False

        # Delete file
        file_path = Path(tool["file_path"])
        if file_path.exists():
            file_path.unlink()

        # Remove current version pointer if this is the current version
        await self.writer.write(
            "DELETE FROM tool_current WHERE current_version_id = ?",
            (tool_id,)
        )

        # Delete DB record
        await self.writer.write("DELETE FROM tools WHERE id = ?", (tool_id,))

        logger.info(f"Tool '{tool['name']}' v{tool['version']} deleted")
        return True

    async def get_versions(self, name: str) -> list[dict[str, Any]]:
        """Get all versions of a tool by name."""
        cursor = await self.db.execute(
            "SELECT * FROM tools WHERE name = ? ORDER BY version DESC",
            (name,)
        )
        return [dict(r) for r in await cursor.fetchall()]
