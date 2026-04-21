"""
Lifecycle management — graceful shutdown helpers.

Edge Case 2 fix: Uses os.killpg() to kill the entire process group,
preventing zombie child processes (uv run, reconciler threads, etc.).
"""

import logging
import os
import signal

logger = logging.getLogger(__name__)


def stop_daemon_by_pid(pid: int) -> bool:
    """
    Stop a daemon by PID. Kills entire process group.

    Edge Case 2 fix: os.killpg() reaches child processes spawned by the daemon
    (uv run subprocesses, etc.) preventing zombies.

    Returns True if signal was sent successfully.
    """
    try:
        # Kill entire process group
        pgid = os.getpgid(pid)
        os.killpg(pgid, signal.SIGTERM)
        logger.info(f"Sent SIGTERM to process group {pgid} (PID {pid})")
        return True
    except ProcessLookupError:
        logger.info(f"Process {pid} not found (already stopped)")
        return False
    except PermissionError:
        # Try just the main process
        try:
            os.kill(pid, signal.SIGTERM)
            logger.info(f"Sent SIGTERM to PID {pid} (couldn't reach group)")
            return True
        except (ProcessLookupError, PermissionError):
            return False
    except OSError as e:
        logger.error(f"Failed to stop PID {pid}: {e}")
        return False


def is_process_alive(pid: int) -> bool:
    """Check if a process with the given PID is running."""
    try:
        os.kill(pid, 0)
        return True
    except (ProcessLookupError, PermissionError):
        return False
    except OSError:
        return False
