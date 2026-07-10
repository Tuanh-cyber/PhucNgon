"""
Chuẩn hóa số điện thoại VN (canonicalization) — dùng cho claim bệnh nhân theo SĐT.

Nguyên tắc: MỌI phép so khớp sđt phải so trên dạng ĐÃ CHUẨN HÓA (cả số bác sĩ nhập
lẫn số trong DB), không bao giờ so chuỗi thô.
"""

from __future__ import annotations

import re


def normalize_phone(raw: str | None) -> str | None:
    """
    Chuẩn hóa 1 số điện thoại VN về dạng canonical "0xxxxxxxxx":
      - Bỏ mọi ký tự không phải chữ số (khoảng trắng, dấu chấm, gạch, ngoặc, dấu +).
      - Tiền tố quốc tế VN: "+84..." / "84..." -> "0..." .
      - Kết quả hợp lệ = 10-11 chữ số bắt đầu bằng 0 (di động VN 10 số; chấp nhận 11
        cho dải cũ). Rỗng / không đạt -> None (caller tự quyết 422/404).

    Ví dụ: "+84 91 234-5678" -> "0912345678"; "0912.345.678" -> "0912345678".
    """
    if not raw:
        return None
    digits = re.sub(r"\D", "", raw)
    # "+84"/"84" đầu -> "0" (chỉ khi KHÔNG bắt đầu bằng 0 — "084..." đã là dạng nội địa)
    if digits.startswith("84") and len(digits) >= 10:
        digits = "0" + digits[2:]
    if re.fullmatch(r"0\d{9,10}", digits):
        return digits
    return None
