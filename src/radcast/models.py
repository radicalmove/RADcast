"""Shared pydantic models for RADcast."""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any

from typing_extensions import Literal

from pydantic import BaseModel, Field, model_validator


class OutputFormat(str, Enum):
    WAV = "wav"
    MP3 = "mp3"


class EnhancementModel(str, Enum):
    RESEMBLE = "resemble"
    DEEPFILTERNET = "deepfilternet"
    SGMSE = "sgmse"


class WorkerCapability(str, Enum):
    ENHANCE = "enhance"


class JobStatus(str, Enum):
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class ProjectCreateRequest(BaseModel):
    project_id: str = Field(min_length=2)
    course: str | None = None
    module: str | None = None
    lesson: str | None = None


class ProjectAccessGrantRequest(BaseModel):
    email: str = Field(min_length=3)


class ProjectAccessRevokeRequest(BaseModel):
    email: str = Field(min_length=3)


class SimpleEnhanceRequest(BaseModel):
    project_id: str = Field(min_length=2)
    input_audio_b64: str | None = Field(default=None, min_length=32)
    input_audio_filename: str | None = Field(default=None, min_length=1)
    input_audio_hash: str | None = Field(default=None, min_length=16, max_length=128)
    output_name: str | None = None
    output_format: OutputFormat = OutputFormat.MP3
    enhancement_model: EnhancementModel = EnhancementModel.RESEMBLE

    @model_validator(mode="after")
    def validate_audio_source(self) -> "SimpleEnhanceRequest":
        has_uploaded_audio = bool(self.input_audio_b64 and self.input_audio_filename)
        has_saved_audio = bool(self.input_audio_hash)
        if not has_uploaded_audio and not has_saved_audio:
            raise ValueError("Provide either input_audio_b64+input_audio_filename or input_audio_hash")
        if self.input_audio_b64 and not self.input_audio_filename:
            raise ValueError("input_audio_filename is required when input_audio_b64 is provided")
        return self


class ProjectSourceAudioUploadRequest(BaseModel):
    filename: str = Field(min_length=1)
    audio_b64: str = Field(min_length=32)


class OutputMetadata(BaseModel):
    output_file: Path
    input_file: Path
    duration_seconds: float
    output_format: OutputFormat
    enhancement_model: EnhancementModel | None = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    project_id: str
    job_id: str


class JobRecord(BaseModel):
    id: str
    project_id: str
    status: JobStatus
    stage: str
    progress: float = Field(default=0.0, ge=0.0, le=1.0)
    eta_seconds: int | None = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    error: str | None = None
    logs: list[str] = Field(default_factory=list)
    outputs: dict[str, Any] = Field(default_factory=dict)


class JobCancelResponse(BaseModel):
    job_id: str
    project_id: str
    status: str
    requested_at: str


class ProjectArtifactResponse(BaseModel):
    project_id: str
    output_name: str
    output_format: OutputFormat
    output_path: str
    download_url: str
    play_url: str
    created_at: str


class WorkerInviteResponse(BaseModel):
    invite_token: str
    expires_in_seconds: int
    install_command: str
    install_command_windows: str | None = None
    install_command_macos: str | None = None
    install_command_linux: str | None = None
    windows_installer_url: str | None = None
    macos_installer_url: str | None = None


class WorkerInviteRequest(BaseModel):
    capabilities: list[WorkerCapability] = Field(default_factory=lambda: [WorkerCapability.ENHANCE])


class WorkerRegisterRequest(BaseModel):
    invite_token: str = Field(min_length=10)
    worker_name: str = Field(min_length=2)
    capabilities: list[WorkerCapability] = Field(default_factory=lambda: [WorkerCapability.ENHANCE])


class WorkerRegisterResponse(BaseModel):
    worker_id: str
    api_key: str
    poll_interval_seconds: int = 5


class WorkerPullRequest(BaseModel):
    worker_id: str
    api_key: str


class WorkerEnhanceEnqueueRequest(BaseModel):
    project_id: str = Field(min_length=2)
    input_audio_b64: str = Field(min_length=32)
    input_audio_filename: str = Field(min_length=1)
    output_name: str | None = None
    output_format: OutputFormat = OutputFormat.MP3
    enhancement_model: EnhancementModel = EnhancementModel.RESEMBLE


class WorkerQueuedJob(BaseModel):
    job_id: str
    project_id: str
    type: Literal["enhance"]
    payload: dict[str, Any]


class WorkerPullResponse(BaseModel):
    job: WorkerQueuedJob | None = None


class WorkerJobCompleteRequest(BaseModel):
    worker_id: str
    api_key: str
    output_audio_b64: str = Field(min_length=32)
    output_format: OutputFormat
    duration_seconds: float = Field(gt=0)
    stage_durations_seconds: dict[str, float] = Field(default_factory=dict)


class WorkerJobProgressRequest(BaseModel):
    worker_id: str
    api_key: str
    progress: float = Field(ge=0.0, le=1.0)
    stage: str | None = None
    detail: str | None = None
    eta_seconds: int | None = Field(default=None, ge=0)


class WorkerJobFailRequest(BaseModel):
    worker_id: str
    api_key: str
    error: str = Field(min_length=1)


class WorkerSummary(BaseModel):
    worker_id: str
    worker_name: str
    capabilities: list[WorkerCapability]
    status: str
    last_seen_at: str | None = None
    created_at: str


def now_utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def touch_job_update(job: JobRecord) -> None:
    job.updated_at = datetime.now(timezone.utc)
