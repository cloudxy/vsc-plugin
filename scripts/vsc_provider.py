#!/usr/bin/env python3
"""Provider-neutral generation contract. Importing this module makes no remote call.

Business code prepares one of the three request types. A scheduler resolves a
registered model and calls the matching adapter; external task IDs and temporary
URLs remain in the job/media store, never in screenplay or shot objects.
"""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any, Literal, Protocol


@dataclass(frozen=True)
class BaseRequest:
    shot_id: str
    purpose: str
    context_sha256: str
    prompt: str
    reference_media_ids: tuple[str, ...] = ()
    params: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ImageRequest(BaseRequest):
    width: int = 1080
    height: int = 1920


@dataclass(frozen=True)
class VideoRequest(BaseRequest):
    duration_ms: int = 5000
    first_frame_media_id: str | None = None
    last_frame_media_id: str | None = None


@dataclass(frozen=True)
class AudioRequest(BaseRequest):
    script_line_ids: tuple[str, ...] = ()
    voice_media_id: str | None = None


@dataclass(frozen=True)
class JobHandle:
    provider: str
    model: str
    external_task_id: str | None
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class JobStatus:
    status: Literal["submitted", "running", "succeeded", "failed"]
    retryable: bool = False
    error_code: str | None = None
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class GeneratedAsset:
    modality: Literal["image", "video", "audio"]
    temporary_uri: str | None = None
    inline_bytes: bytes | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    local_path: str | None = None
    sha256: str | None = None


class ImageProvider(Protocol):
    def submit(self, req: ImageRequest) -> JobHandle: ...
    def poll(self, handle: JobHandle) -> JobStatus: ...
    def parse_result(self, raw: dict[str, Any]) -> list[GeneratedAsset]: ...


class VideoProvider(Protocol):
    def submit(self, req: VideoRequest) -> JobHandle: ...
    def poll(self, handle: JobHandle) -> JobStatus: ...
    def parse_result(self, raw: dict[str, Any]) -> list[GeneratedAsset]: ...


class AudioProvider(Protocol):
    def submit(self, req: AudioRequest) -> JobHandle: ...
    def poll(self, handle: JobHandle) -> JobStatus: ...
    def parse_result(self, raw: dict[str, Any]) -> list[GeneratedAsset]: ...
