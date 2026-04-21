"""
Database schema migration runner.

Reads .sql files from the migrations directory and applies them
in order, tracking which have been applied via the schema_version table.
"""
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

MIGRATIONS_DIR = Path(__file__).parent


async def run_migrations(writer: "DatabaseWriter") -> None:  # noqa: F821
    """
    Apply pending migrations.

    1. Ensure schema_version table exists
    2. Find all ###_*.sql files in migrations dir
    3. Apply any that haven't been applied yet (by version number)

    Args:
        writer: DatabaseWriter instance (all writes go through it)
    """
    # Bootstrap: create schema_version if it doesn't exist
    await writer.write(
        """
        CREATE TABLE IF NOT EXISTS schema_version (
            version INTEGER PRIMARY KEY,
            applied_at TEXT NOT NULL DEFAULT (datetime('now'))
        );
    """
    )

    # Get current version — reads go directly to db (WAL allows concurrent reads)
    cursor = await writer.db.execute(
        "SELECT COALESCE(MAX(version), 0) FROM schema_version"
    )
    row = await cursor.fetchone()
    current_version = row[0]

    # Find and sort migration files
    migration_files = sorted(MIGRATIONS_DIR.glob("[0-9][0-9][0-9]_*.sql"))

    for migration_file in migration_files:
        version = int(migration_file.name.split("_")[0])
        if version <= current_version:
            continue

        logger.info(f"Applying migration {migration_file.name}...")
        sql = migration_file.read_text()

        try:
            await writer.execute_script(sql)
            await writer.write(
                "INSERT INTO schema_version (version) VALUES (?)",
                (version,),
            )
            logger.info(f"Migration {migration_file.name} applied successfully")
        except Exception as e:
            # Migration 002 (vectors) is optional — skip gracefully if sqlite-vec absent
            if "002_vectors" in migration_file.name and "no such module" in str(e).lower():
                logger.info(
                    f"Migration {migration_file.name} skipped: "
                    f"sqlite-vec not available (vector search disabled)"
                )
            else:
                logger.error(f"Migration {migration_file.name} FAILED: {e}")
                raise
