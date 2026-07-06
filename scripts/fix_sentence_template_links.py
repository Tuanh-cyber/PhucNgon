"""
Sửa liên kết template_id bị gán CHÉO trong sentence_instance_assets.

BỐI CẢNH (07/2026): 15 dòng Sentence Instance chủ đề Số đếm trong Asset.xlsx bị gán
nhầm template_id giữa 2 template T009 'Bây giờ là ___ giờ' và T010 'Tôi có ___ cái áo'
(full_sentence + audio thuộc template này nhưng template_id trỏ sang template kia).
Hậu quả: màn hình hiển thị câu khuyết theo template SAI trong khi audio gợi ý + chấm
điểm theo full_sentence ĐÚNG -> người dùng thấy "phát sai audio" và không thể pass.

CÁCH SỬA: full_sentence + vocab + audio là bộ ba nhất quán (audio thu theo full_sentence),
nên template là mắt xích sai -> gán lại template_id cho khớp full_sentence:
  template "fits" full_sentence khi full = prefix + <phần khuyết> + suffix
  (prefix/suffix lấy từ template tách tại chỗ ___).

Idempotent: dòng đã khớp thì bỏ qua; chỉ sửa khi tìm được ĐÚNG 1 template khớp
(0 hoặc >=2 ứng viên -> log cảnh báo, không đụng).
Chạy:  python -m scripts.fix_sentence_template_links
"""

from __future__ import annotations

import logging
import re
import sys

from app.core.database import SessionLocal
from app.models.content import SentenceInstanceAsset, SentenceTemplateAsset

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
logger = logging.getLogger(__name__)


def template_fits(template: str, full_sentence: str) -> bool:
    """True nếu full_sentence khớp khuôn template (prefix ___ suffix)."""
    parts = re.split(r"_{2,}", " ".join(template.split()), maxsplit=1)
    if len(parts) != 2:
        return False
    prefix, suffix = parts[0].strip().lower(), parts[1].strip().lower()
    full = " ".join(full_sentence.split()).lower()
    return (
        full.startswith(prefix)
        and full.endswith(suffix)
        and len(full) > len(prefix) + len(suffix)  # phần khuyết phải khác rỗng
    )


def main() -> int:
    db = SessionLocal()
    try:
        templates = db.query(SentenceTemplateAsset).all()
        fixed = ok = skipped = 0
        for si in db.query(SentenceInstanceAsset).all():
            if template_fits(si.template.template, si.full_sentence):
                ok += 1
                continue
            candidates = [t for t in templates if template_fits(t.template, si.full_sentence)]
            if len(candidates) != 1:
                skipped += 1
                logger.warning(
                    "KHÔNG sửa %s (full=%r): %d template khớp %r",
                    si.audio_file, si.full_sentence, len(candidates),
                    [t.template for t in candidates],
                )
                continue
            logger.info(
                "Sửa %s: template %r -> %r (full=%r)",
                si.audio_file, si.template.template, candidates[0].template, si.full_sentence,
            )
            si.template_id = candidates[0].id
            fixed += 1

        db.commit()
        logger.info("✓ Xong: %d đã khớp sẵn / %d sửa lại / %d bỏ qua (cần xem tay)", ok, fixed, skipped)
        return 0 if skipped == 0 else 1
    finally:
        db.close()


if __name__ == "__main__":
    sys.exit(main())
