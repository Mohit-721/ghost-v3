"""Pydantic models for API request and response bodies."""

from pydantic import BaseModel, Field


class ForgeRequest(BaseModel):
    intent: str = Field(..., description="Natural language description of the tool")
    project_id: str | None = Field(None, description="Project ID for context")


class ForgeResponse(BaseModel):
    id: str
    name: str
    description: str
    file_path: str
    source_hash: str
    status: str
    capabilities: list[str] = []
    code_preview: str = ""


class ToolRunRequest(BaseModel):
    args: list[str] = []
    project_dir: str | None = None


class ToolRunResponse(BaseModel):
    exit_code: int
    stdout: str
    stderr: str
    timed_out: bool
    used_uv: bool


class ToolResponse(BaseModel):
    id: str
    name: str
    version: int
    description: str | None = None
    status: str
    runs: int = 0
    capabilities: str = "[]"


class MemorySearchRequest(BaseModel):
    query: str
    project_id: str | None = None
    limit: int = 20


class WatchRequest(BaseModel):
    path: str
    project_name: str | None = None


class LogLevelRequest(BaseModel):
    level: str


class HealthResponse(BaseModel):
    status: str
    version: str
    pid: int


class ShutdownResponse(BaseModel):
    message: str = "Shutting down..."
