"""
Fixtures dùng chung cho toàn bộ test suite.

ensure_topic_progress_table: bảng topic_progress có migration (9260b605903f) nhưng migration
được giao cho người review chạy tay (`alembic upgrade head`), KHÔNG tự áp trong code. Trong lúc
đó submit_attempt() đã ghi vào bảng này ở MỌI lượt nộp bài — nên test sẽ vỡ nếu bảng chưa có.

Fixture này (autouse, session-scope):
  - Nếu bảng CHƯA có: tạo tạm từ ORM metadata (đúng schema migration) -> XOÁ khi hết suite,
    trả DB về trạng thái sạch để sau này `alembic upgrade head` chạy không vướng.
  - Nếu bảng ĐÃ có (migration đã áp): không làm gì, không xoá.
"""

import pytest
from sqlalchemy import inspect

from app.core.database import engine
from app.models.therapy import TopicProgress


@pytest.fixture(scope="session", autouse=True)
def ensure_topic_progress_table():
    inspector = inspect(engine)
    existed_before = inspector.has_table("topic_progress")

    if not existed_before:
        TopicProgress.__table__.create(bind=engine, checkfirst=True)

    yield

    if not existed_before:
        # Trả DB về sạch để migration thật (alembic upgrade head) không bị vướng bảng có sẵn.
        TopicProgress.__table__.drop(bind=engine, checkfirst=True)
