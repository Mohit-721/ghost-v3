"""
Tool execution. Prefers `uv run` for automatic dependency management.
Falls back to bare `python` if uv is not installed.

Security:
- Runs in a temp directory (not in the project)
- API keys are NOT passed to tools
- Resource limits via POSIX setrlimit
- Timeout enforced
"""
import logging
import resource
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path

from ghost.config.schema import SandboxConfig

logger = logging.getLogger(__name__)


@dataclass
class ExecutionResult:
    """Result from tool execution."""
    exit_code: int
    stdout: str
    stderr: str
    timed_out: bool
    used_uv: bool


class ToolExecutor:
    """Execute tools in isolated subprocesses."""

    def __init__(self, config: SandboxConfig) -> None:
        self.exec_timeout = config.exec_timeout_seconds
        self.install_timeout = config.install_timeout_seconds
        self.memory_limit = config.memory_limit_mb * 1024 * 1024
        self.max_output = config.max_output_bytes
        self._has_uv = shutil.which("uv") is not None and config.prefer_uv

    async def execute(self, tool_path: Path, args: list[str] | None = None,
                      project_dir: Path | None = None) -> ExecutionResult:
        """
        Run a tool in an isolated subprocess.

        If uv is available: `uv run` reads PEP 723 metadata and auto-installs deps.
        If uv is not available: bare `python` (tools needing 3rd-party packages will fail).
        """
        cmd = self._build_command(tool_path, args)
        env = self._build_env(project_dir)

        # Use install_timeout for uv (may need to download deps first time)
        timeout = self.install_timeout if self._has_uv else self.exec_timeout

        try:
            with tempfile.TemporaryDirectory(prefix="ghost_") as tmpdir:
                result = subprocess.run(
                    cmd,
                    capture_output=True,
                    text=True,
                    timeout=timeout,
                    cwd=tmpdir,
                    env=env,
                    preexec_fn=self._set_limits,
                    check=False,
                )
                return ExecutionResult(
                    exit_code=result.returncode,
                    stdout=result.stdout[:self.max_output],
                    stderr=result.stderr[:self.max_output],
                    timed_out=False,
                    used_uv=self._has_uv,
                )
        except subprocess.TimeoutExpired:
            return ExecutionResult(
                exit_code=-1,
                stdout="",
                stderr=f"Execution timed out after {timeout}s",
                timed_out=True,
                used_uv=self._has_uv,
            )
        except Exception as e:
            return ExecutionResult(
                exit_code=-1,
                stdout="",
                stderr=str(e),
                timed_out=False,
                used_uv=self._has_uv,
            )

    def _build_command(self, tool_path: Path, args: list[str] | None) -> list[str]:
        if self._has_uv:
            return ["uv", "run", "--quiet", "--no-progress", str(tool_path)] + (args or [])
        else:
            return ["python", str(tool_path)] + (args or [])

    def _build_env(self, project_dir: Path | None) -> dict[str, str]:
        """Restricted environment. API keys are NOT passed."""
        env = {
            "PATH": "/usr/local/bin:/usr/bin:/bin",
            "HOME": "/tmp",
            "LANG": "en_US.UTF-8",
        }
        if project_dir:
            env["GHOST_PROJECT_DIR"] = str(project_dir)
        return env

    def _set_limits(self) -> None:
        """POSIX resource limits on child process."""
        try:
            resource.setrlimit(resource.RLIMIT_AS, (self.memory_limit, self.memory_limit))
            resource.setrlimit(resource.RLIMIT_CPU, (self.exec_timeout, self.exec_timeout))
        except (ValueError, OSError) as e:
            # Some systems don't support all limits
            logger.debug(f"Could not set resource limit: {e}")

    @property
    def has_uv(self) -> bool:
        return self._has_uv
