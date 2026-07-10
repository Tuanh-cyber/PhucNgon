"""
Router: vocabulary — danh sách từ vựng cho flashcard.

GET /vocabulary?topic=...: toàn bộ từ vựng (bảng vocabulary_assets đã seed) kèm URL
ảnh + audio. Dữ liệu lấy TỪ DATABASE, không đọc Excel. URL dựng bằng CÙNG
asset_url_service với bài tập (single source) -> chỉ trả URL khi file tồn tại, thiếu -> None.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.models.content import VocabularyAsset
from app.models.enums import Topic
from app.routers.auth import get_current_user
from app.schemas.content import VocabularyItem
from app.services.asset_url_service import vocab_audio_url, vocab_image_url

router = APIRouter(prefix="/vocabulary", tags=["vocabulary"])


@router.get("", response_model=list[VocabularyItem])
def list_vocabulary(
    topic: str | None = None,
    current_user=Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Toàn bộ từ vựng cho flashcard (mặc định 90 từ), sắp theo topic rồi canonical_word
    để thứ tự ổn định giữa các lần gọi.

    - topic (optional): lọc theo chủ đề (enum value, vd "food_drink"). Không hợp lệ -> 422.
    - image_url / audio_url: dựng bằng asset_url_service (single source với bài tập),
      chỉ có URL khi file tồn tại trên đĩa; thiếu -> None (frontend hiện placeholder).
    """
    query = db.query(VocabularyAsset)

    if topic is not None:
        try:
            topic_enum = Topic(topic)
        except ValueError:
            raise HTTPException(
                status_code=422,
                detail=f"topic không hợp lệ: {topic!r} "
                f"(hợp lệ: {[t.value for t in Topic]})",
            )
        query = query.filter(VocabularyAsset.topic == topic_enum)

    vocabs = query.order_by(
        VocabularyAsset.topic, VocabularyAsset.canonical_word
    ).all()

    return [
        VocabularyItem(
            vocab_id=str(v.id),
            word=v.canonical_word,
            topic=v.topic.value,
            word_type=v.word_type.value,
            image_url=vocab_image_url(v),
            audio_url=vocab_audio_url(v),
        )
        for v in vocabs
    ]
