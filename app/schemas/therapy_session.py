"""
Pydantic schemas cho PHIÊN TẬP (rule.md mục 3: 1 phiên = 10 bài, mode + topic).
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel

from app.schemas.content import AssignmentListItem

SessionMode = Literal[
    "naming",
    "command_identification",
    "sentence_building",
    "mixed",
    "logic_sequence",
    "color_recognition",
]


class SessionStartRequest(BaseModel):
    """POST /sessions/start — chọn MODE + TOPIC. topic bỏ trống = Mixed Topics."""

    mode: SessionMode
    topic: Optional[str] = None


class SessionStartResponse(BaseModel):
    """Phiên vừa tạo + danh sách 10 bài đã chọn cho phiên."""

    session_id: str
    mode: SessionMode
    topic: Optional[str]            # None = Mixed Topics
    vocab_level: Optional[int]      # None khi Mixed Topics (level theo từng bài)
    profile: str                    # snapshot: broca_like | wernicke_like | mixed
    planned_count: int
    exercises: list[AssignmentListItem]  # tối đa 10 bài (pending ưu tiên trước)


class SessionStateResponse(BaseModel):
    """GET /sessions/{id} + response của finish — trạng thái + tiến độ phiên."""

    session_id: str
    status: Literal["in_progress", "completed", "stopped_early"]
    mode: SessionMode
    topic: Optional[str]
    vocab_level: Optional[int]
    profile: str
    planned_count: int
    completed_count: int            # số bài ĐÃ KẾT THÚC (graded) trong phiên -> "x/10"
    total_retry_count: int          # tổng số lượt làm THÊM (retry) của mọi bài trong phiên
    started_at: datetime
    ended_at: Optional[datetime]
    duration_seconds: Optional[int]  # tính khi kết thúc phiên
