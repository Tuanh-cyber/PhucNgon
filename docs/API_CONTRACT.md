# PhụcNgôn — API Contract (nguồn sự thật cho Frontend)

> Tài liệu này liệt kê chính xác các endpoint backend đã xây dựng, đã test, đang ổn định.
> Frontend build dựa theo đây, không đoán hình dạng dữ liệu.
> Base URL mặc định lúc phát triển: `http://127.0.0.1:8000` (đổi theo `.env` của Frontend khi deploy).

---

## 1. Auth — Đăng ký / Đăng nhập / Kiểm tra phiên

### POST `/auth/register/patient`
Đăng ký tài khoản bệnh nhân. Tự động tạo kế hoạch trị liệu (30 bài) + đánh giá ban đầu (nếu có).

**Request** (multipart hoặc JSON tuỳ Content-Type, khớp `PatientRegisterRequest`):
```json
{
  "full_name": "Huỳnh Đình Phúc Hào",
  "email": "hao@example.com",
  "password": "matkhau123",
  "phone_number": "0912345678",
  "date_of_birth": "1962-01-01",
  "address": "268 đường Lý Thường Kiệt, phường Diên Hồng, TP.HCM",
  "caregiver_phone": "0987654321",
  "gender": "male",
  "aphasia_type": "Aphasia Broca",
  "severity_level": "Trung bình",
  "hospital_name": "Bệnh viện Y dược TP.HCM",
  "referring_doctor_name": "BS. Thanh Phúc",
  "accuracy_score": 80.0,
  "completion_score": 55.0,
  "fluency_score": 45.0
}
```
**`phone_number` (SĐT bệnh nhân) BẮT BUỘC** — Mô hình A: bác sĩ nhận bệnh nhân bằng sđt.
Backend CHUẨN HÓA trước khi lưu (bỏ khoảng trắng/chấm/gạch, `+84`/`84` đầu → `0`; DB lưu dạng
`0xxxxxxxxx`). Số không hợp lệ (không ra 10-11 chữ số bắt đầu 0) → **422**.
Các field `address`, `caregiver_phone` (SĐT người chăm sóc — KHÔNG ép định dạng),
`aphasia_type`, `severity_level`, `hospital_name`, `referring_doctor_name`,
`accuracy_score`, `completion_score`, `fluency_score` đều **optional**.
`address` → lưu `Profile.address`; `caregiver_phone` → lưu `Profile.emergency_contact`
(chỉ tạo Profile khi có ít nhất 1 trong 2 field này).

**Response 200:**
```json
{ "access_token": "eyJ...", "token_type": "bearer", "role": "patient" }
```
**Response 409:** email đã tồn tại, HOẶC **số điện thoại đã được bệnh nhân khác đăng ký**
(so trên dạng chuẩn hóa — `0912...` và `+8491 2...` tính là cùng số).

### POST `/auth/register/therapist`
Tương tự, cho bác sĩ. Field riêng: `license_no` (bắt buộc), `specialization` (optional).

### POST `/auth/login`
```json
{ "email": "hao@example.com", "password": "matkhau123" }
```
**200:** giống response register. **401:** sai email/mật khẩu (message chung chung, không nói rõ sai cái nào).

### POST `/auth/change-password`
User ĐANG ĐĂNG NHẬP tự đổi mật khẩu của mình (mọi role). Yêu cầu header
`Authorization: Bearer <token>` — danh tính lấy từ token, KHÔNG đổi được mật khẩu người khác.
```json
{ "current_password": "matkhau123", "new_password": "matkhaumoi456" }
```
**200:** `{ "message": "Đổi mật khẩu thành công" }` — sau đó đăng nhập bằng mật khẩu MỚI,
mật khẩu cũ hết hiệu lực (token đã cấp vẫn sống tới khi hết hạn).
**400:** `current_password` sai — "Mật khẩu hiện tại không đúng".
**401:** chưa đăng nhập / token hết hạn. **422:** `new_password` dưới 6 ký tự.

### GET `/auth/me`
Yêu cầu header `Authorization: Bearer <token>`.
Dùng để kiểm tra token còn hợp lệ mỗi lần mở app — **200 → vào thẳng Trang chủ, 401 → hiện màn đăng nhập**.
```json
{ "user_id": "uuid", "full_name": "...", "email": "...", "role": "patient" }
```
Token sống **90 ngày** — không cần đăng nhập lại liên tục.

---

## 2. Assessment — Kết quả đánh giá ban đầu (do bác sĩ nhập lúc đăng ký)

### GET `/patients/me/initial-assessment`
Yêu cầu đăng nhập, role = patient.
```json
{
  "aphasia_type": "Aphasia Broca",
  "severity_level": "Trung bình",
  "hospital_name": "Bệnh viện Y dược TP.HCM",
  "referring_doctor_name": "BS. Thanh Phúc",
  "accuracy_score": 80.0,
  "completion_score": 55.0,
  "fluency_score": 45.0
}
```
**Lưu ý:** 3 field điểm số có thể là `null` nếu bác sĩ chưa cung cấp lúc đăng ký — Frontend hiển thị
"Chưa có dữ liệu" thay vì "0%" khi gặp `null`.

### GET `/patients/me/recommended-exercises`
Gợi ý 3 loại bài theo profile bệnh (rule.md "Profile => Exercise Weight"). Yêu cầu đăng nhập,
role = patient. `aphasia_type` của patient → profile: chứa "Broca" → `broca_like`, chứa
"Wernicke" → `wernicke_like`, còn lại (kể cả "Loại Aphasia khác"/trống) → `mixed`.
```json
[
  { "exercise_type": "naming", "display_name": "Gọi tên", "weight": 0.7, "recommended": true },
  { "exercise_type": "command_identification", "display_name": "Nghe và đoán", "weight": 0.3, "recommended": true },
  { "exercise_type": "sentence_building", "display_name": "Hoàn thành câu", "weight": 0.0, "recommended": false }
]
```
`recommended = weight >= 0.3`. CHỈ để hiển thị gợi ý — logic giao bài thật KHÔNG đổi
(vẫn 10 bài/loại).

### GET `/patients/me/profile`
Hồ sơ của bệnh nhân đang đăng nhập — màn "Tài khoản" (chỉ xem). Yêu cầu đăng nhập, role = patient.
```json
{
  "full_name": "Huỳnh Đình Phúc Hào", "email": "hao@example.com",
  "phone_number": "0912345678", "date_of_birth": "1962-01-01", "gender": "male",
  "severity_level": "Trung bình", "aphasia_type": "Broca", "hospital_name": "BV Chợ Rẫy"
}
```
`phone_number/severity_level/aphasia_type/hospital_name` có thể `null`.

### GET `/patients/me/stats`
3 chỉ số TÍNH TỰ ĐỘNG từ lịch sử làm bài thật (khác initial-assessment là số bác sĩ nhập tay).
Yêu cầu đăng nhập, role = patient.
```json
{ "accuracy_score": 72.5, "completion_score": 60.0, "fluency_score": null }
```
Field `null` = "chưa có dữ liệu để tính" (KHÔNG phải điểm 0).

### GET `/patients/me/progress-dashboard`
Dữ liệu dashboard tiến trình trên trang chủ. Yêu cầu đăng nhập, role = patient.
Patient mới chưa làm bài vẫn trả 200 (7 ngày toàn `null`, 30 ngày toàn `null`, streak 0, list rỗng) — KHÔNG 404.
```json
{
  "daily_scores": [
    { "date": "2026-06-29", "avg_score": null, "session_count": 0 },
    { "date": "2026-07-05", "avg_score": 60.9, "session_count": 2 }
  ],
  "daily_scores_30": [
    { "date": "2026-06-07", "avg_score": null, "session_count": 0 },
    { "date": "2026-07-05", "avg_score": 60.9, "session_count": 2 }
  ],
  "streak": {
    "current_streak_days": 1,
    "active_days_last_30": ["2026-07-04", "2026-07-05"]
  },
  "difficult_words": [
    { "word": "thịt", "attempts": 3, "fail_count": 2, "exercise_type": "naming" }
  ]
}
```
- `daily_scores`: ĐÚNG 7 phần tử (7 ngày gần nhất, cũ → mới, phần tử cuối = hôm nay).
  Dùng cho biểu đồ đường trên trang chủ.
  `avg_score` = trung bình `score` các lượt làm trong ngày, `null` nếu ngày không tập;
  `session_count` = số lượt làm bài trong ngày.
- `daily_scores_30`: ĐÚNG 30 phần tử (30 ngày gần nhất, cũ → mới, phần tử cuối = hôm nay).
  Dùng cho lịch heat-map 30 ngày đầy đủ (thay vì kết hợp 7 ngày chi tiết + 23 ngày binary).
  Cấu trúc giống `daily_scores` (date, avg_score, session_count).
- `streak.current_streak_days`: số ngày LIÊN TIẾP (tính tới hôm nay) có ≥1 bài hoàn
  thành (session graded); hôm nay chưa tập thì chuỗi tính tới hôm qua vẫn giữ.
  `active_days_last_30`: các ngày có ≥1 lượt làm bài trong 30 ngày qua (backup cho lịch, hoặc UI khác cần binary).
- `difficult_words`: tối đa 10 từ hay sai, sắp giảm dần `fail_count` (fail = result
  thuộc retry/incorrect/near). Heuristic MVP. Rỗng = chưa đủ dữ liệu.

---

## 3. Plans — Kế hoạch điều trị / Bài tập hôm nay

### GET `/plans/me/today`
Yêu cầu đăng nhập, role = patient.
```json
{
  "plan_id": "uuid",
  "exercises": [
    { "exercise_type": "naming", "display_name": "Gọi tên", "total_assigned": 10, "completed_count": 0, "completion_percent": 0.0 },
    { "exercise_type": "command_identification", "display_name": "Lặp lại", "total_assigned": 10, "completed_count": 5, "completion_percent": 52.0 },
    { "exercise_type": "sentence_building", "display_name": "Tạo câu", "total_assigned": 10, "completed_count": 10, "completion_percent": 100.0 }
  ]
}
```
**404** nếu chưa có kế hoạch nào (trường hợp hiếm, vì kế hoạch tự tạo lúc đăng ký).

**display_name:** backend đã đổi sang tên mới (Gọi tên / Nghe và đoán / Hoàn thành câu),
đồng bộ với map `src/constants/exercises.ts` phía Frontend.

### GET `/plans/me/topics?type={exercise_type}`
Các topic **thật sự có bài** trong plan active (màn "Chọn chủ đề"). Yêu cầu đăng nhập, role = patient.
`type` optional ∈ `naming` | `command_identification` | `sentence_building` | `mixed`;
`mixed` hoặc bỏ trống = xét cả 3 dạng. Giá trị khác → 422.
```json
[
  { "topic": "food_drink", "topic_display": "Ăn uống", "total_count": 8, "completed_count": 2 },
  { "topic": "number", "topic_display": "Số đếm", "total_count": 5, "completed_count": 0 }
]
```
`topic_display`: daily_activity→"Hoạt động thường ngày", food_drink→"Ăn uống",
household_item→"Vật dụng", family→"Gia đình", body_part→"Bộ phận cơ thể", number→"Số đếm".
`completed_count` = số bài có ≥1 lượt làm KẾT THÚC (graded) — cùng định nghĩa với
`status` của `/me/assignments`. **404** nếu chưa có plan.

### GET `/plans/me/assignments?type={exercise_type}&topic={topic}`
Danh sách bài CỤ THỂ (màn "Danh sách bài"). Yêu cầu đăng nhập, role = patient.
- `type` ∈ `naming` | `command_identification` | `sentence_building` | **`mixed`** (khác → 422).
  `mixed` = gộp bài của CẢ 3 dạng, **trộn ngẫu nhiên** thứ tự — seed theo
  (patient + topic + ngày) nên trong cùng 1 ngày refresh không đổi thứ tự, sang ngày mới đổi.
- `topic` optional ∈ enum Topic (khác → 422). Luồng chọn bài MỚI luôn truyền topic
  (chọn chủ đề TRƯỚC); bỏ trống = mọi topic (tương thích ngược màn cũ).
```json
[
  { "assignment_id": "uuid", "exercise_id": "uuid", "exercise_type": "naming",
    "topic": "food_drink", "order_index": 0, "status": "pending" }
]
```
Dạng đơn sắp theo `order_index`; `mixed` theo thứ tự đã trộn. `status = "completed"`
khi bài đã có 1 lượt làm KẾT THÚC (graded), kể cả trả lời sai — khác
`completion_percent` ở `/me/today` (chỉ đếm bài ĐẠT).

---

## 4. Attempts — Làm bài / Nộp bài

### GET `/exercises/{exercise_id}`
Thông tin cơ bản 1 bài (KHÔNG lộ đáp án đúng):
```json
{ "exercise_id": "uuid", "exercise_type": "naming", "topic": "household_item", "vocab_level": 1, "mode": null }
```

### GET `/assignments/{assignment_id}/content`
Nội dung chi tiết 1 bài để render UI — **KHÔNG BAO GIỜ chứa đáp án đúng**. Yêu cầu đăng nhập;
assignment phải thuộc patient đang đăng nhập (403 nếu không). Hình dạng response TUỲ loại bài:

```json
// naming — vocab_audio_url: audio phát âm mẫu của từ (null nếu thiếu file)
{ "exercise_type": "naming", "image_url": "/static/pictures/Object/VOB1001.jpg",
  "prompt": "Tên của vật này là gì?", "vocab_audio_url": "/static/vocab-audio/VOB1001.wav" }

// command_identification — mode recognition (4 lựa chọn, KHÔNG đánh dấu cái nào đúng)
{ "exercise_type": "command_identification", "mode": "recognition",
  "command_audio_url": "/static/command-audio/C001.wav",
  "command_text": "Con gì sống dưới nước, bơi bằng vây?",
  "choices": [ { "vocab_id": "uuid", "image_url": "/static/pictures/...", "word": "con cá" } ] }

// command_identification — mode repetition
{ "exercise_type": "command_identification", "mode": "repetition",
  "command_audio_url": "/static/command-audio/C001.wav",
  "image_url": "/static/pictures/...", "prompt": "Nghe và nhắc lại" }

// sentence_building
{ "exercise_type": "sentence_building", "template_display": "Tôi muốn ăn ____",
  "image_url": "/static/pictures/...", "sentence_audio_url": "/static/sentence-audio/SI001.wav",
  "prompt": "Hoàn thành câu" }
```
Mọi `*_url` là đường dẫn TƯƠNG ĐỐI — Frontend ghép `EXPO_PUBLIC_API_URL` (helper
`buildAssetUrl`). **`null` khi file thiếu** (vd audio vocab chưa có) — hiện placeholder/ẩn nút,
KHÔNG gọi URL null.

### File tĩnh (ảnh/audio)
- `GET /static/pictures/{TopicFolder}/{vocab_id}.jpg` (TopicFolder: Activity/Body/Family/Food&Drink/Number/Object)
- `GET /static/command-audio/{command_id}.wav` — audio câu hỏi bài Nghe và đoán
- `GET /static/sentence-audio/{sentence_instance_id}.wav` — audio câu mẫu bài Hoàn thành câu
- `GET /static/vocab-audio/{vocab_id}.wav` — audio phát âm mẫu từ vựng

### POST `/assignments/{assignment_id}/submit`
Yêu cầu đăng nhập. Multipart form-data:
- `audio_file`: file ghi âm (optional — không cần cho bài command_identification/recognition)
- `selected_vocab_id`: string (optional — chỉ dùng cho command_identification/recognition)

**Response 200** (khớp `AttemptSubmitResponse`):
```json
{
  "score": 85.0,
  "accuracy_score": 85.0,
  "completion_score": 100.0,
  "fluency_score": 88.0,
  "result": "pass",
  "feedback": [
    { "type": "ok", "text": "Đã gọi đúng tên" },
    { "type": "warn", "text": "Nói chưa đều nhịp, thử nói thong thả hơn nhé" }
  ],
  "feedback_messages": ["Đã gọi đúng tên", "Nói chưa đều nhịp, thử nói thong thả hơn nhé"],
  "transcript": "con mè",
  "attempt_number": 1,
  "is_final": true,
  "leveled_up": false,
  "new_level": null
}
```
`is_final = false` nghĩa là được phép thử lại (bài speech điểm thấp — result `near`/`retry`/`invalid`).

**3 tiêu chí RIÊNG lượt vừa làm** (`accuracy_score` / `completion_score` / `fluency_score`):
- `accuracy_score` = điểm của lượt (`= score`). `null` với bài Nghe-và-đoán dạng touch
  (chỉ Đúng/Sai) và input `invalid`.
- `completion_score` = **ĐỘ PHỦ NỘI DUNG** (recall phần cần nói) của lượt, thang **0–100
  (có thể `null`)**:
  * bài Hoàn-thành-câu → % từ khuyết nói được (điểm lẻ, vd nói 2/3 từ → ~66.7);
  * bài Gọi-tên / Nghe-và-đoán (repetition) → `100` nếu gọi đúng tên, `0` nếu không;
  * bài Nghe-và-đoán dạng touch → `100` nếu chọn đúng ô, `0` nếu chọn sai;
  * input `invalid` (không nghe được) → `null` (không đo được độ phủ).
  ⚠ ĐÂY LÀ "độ phủ nội dung của 1 lượt", **KHÁC** với `completion_score` ở
  `GET /patients/me/stats` (dashboard "Hoàn thành tuần" = tiến độ chương trình = số bài đã
  làm xong / tổng bài trong plan). Hai khái niệm cố ý khác nhau; đừng nhầm.
- `fluency_score` = `components["fluency"]` của lượt. `null` với recognition/`invalid`.

(`accuracy_score` & `fluency_score` vẫn dùng chung nguồn `attempt_to_metrics` với
`/patients/me/stats`; riêng `completion_score` ở 2 nơi là 2 khái niệm khác nhau như trên.)

**`feedback`** = danh sách câu nhận xét CÓ phân loại `{ type, text }` cho màn Kết quả bài tập:
`type` = `"ok"` (điều làm đúng — tô xanh) hoặc `"warn"` (cần cải thiện / lỗi input — tô vàng/đỏ).
Với input rác (`result="invalid"`) trả 1 câu thân thiện (vd "Hãy nói to và rõ hơn nhé!").
`feedback_messages` là danh sách text rút gọn (`= feedback[].text`), giữ để tương thích client cũ.
Đây CHỈ là text hiển thị, KHÔNG ảnh hưởng điểm.

**Progression (rule.md):** `leveled_up = true` khi lượt bài này vừa làm bệnh nhân đạt đủ
**3 lần liên tiếp `score >= 80` cùng topic** → vocab level của topic đó +1 (tối đa 3);
`new_level` là level mới (2 hoặc 3). Khi lên level, backend TỰ GIAO thêm 10 bài mới
(cùng loại bài + cùng topic, ở level mới) vào plan. Frontend hiện
"Chúc mừng! Bạn đã lên Level {new_level}". Bình thường: `leveled_up=false`, `new_level=null`.

**422:** lỗi audio (định dạng sai, không có tiếng nói...) — hiển thị message trong `detail`.
**403:** cố nộp bài không phải của mình.
**503:** dịch vụ ASR (ASR_MODE=real) không khả dụng — `detail` = "Dịch vụ nhận diện giọng nói
tạm thời không khả dụng. Vui lòng thử lại sau." (Frontend hiển thị nguyên văn, cho bấm thử lại.)

### POST `/exercises/{exercise_id}/attempt-preview` *(chỉ dùng để test nhanh, KHÔNG lưu lịch sử)*
Giống hệt response trên nhưng không yêu cầu đăng nhập, không lưu DB — dùng khi cần test độc lập.

---

## 5. Vocabulary — Từ vựng cho flashcard

### GET `/vocabulary?topic={topic}`
Toàn bộ từ vựng trong ngân hàng (90 từ) kèm URL ảnh + audio phát âm — dùng cho màn flashcard.
Yêu cầu đăng nhập. `topic` optional ∈ `daily_activity` | `food_drink` | `household_item` |
`family` | `body_part` | `number` (lọc theo chủ đề); bỏ trống = trả hết; giá trị khác → 422.
Sắp xếp ổn định theo topic rồi theo từ.
```json
[
  {
    "vocab_id": "uuid",
    "word": "ăn cơm",
    "topic": "daily_activity",
    "word_type": "verb",
    "image_url": "/static/pictures/Activity/VAC1001.jpg",
    "audio_url": "/static/vocab-audio/VAC1001.wav"
  }
]
```
- `word` = canonical_word. KHÔNG trả `accepted_answers` (đáp án chấm điểm chỉ ở phía scoring).
- `image_url` / `audio_url`: đường dẫn tương đối `/static/...` (frontend ghép qua `buildAssetUrl`);
  `null` nếu file thiếu trên server — frontend hiện placeholder/ẩn nút, KHÔNG gọi URL 404.

---

## 6. Therapist — Web bác sĩ (Bước 13.1)

Mô hình: bác sĩ↔bệnh nhân link qua `TherapyPlan.therapist_id` của plan ACTIVE. Có HAI loại
bệnh nhân song song, đều hợp lệ: **có bác sĩ** (therapist_id=UUID) và **tự do**
(therapist_id=NULL, tự đăng ký dùng một mình — không thuộc dashboard của bác sĩ nào).
Cả 3 endpoint yêu cầu đăng nhập role=therapist (khác role → 403).

### POST `/therapist/patients/claim`
Bác sĩ NHẬN một bệnh nhân đã đăng ký — khớp theo **SỐ ĐIỆN THOẠI** (Mô hình A: bệnh nhân
đăng ký kèm sđt; bác sĩ nhập số để nhận). Số được CHUẨN HÓA trước khi so khớp: bỏ khoảng
trắng/chấm/gạch/ngoặc, `+84`/`84` đầu → `0` — nên nhập `0912345678`, `+84 91 234 5678`,
`0912.345.678`... đều khớp cùng một bệnh nhân.
```json
{
  "phone": "0912345678",
  "aphasia_type": "Broca",
  "hospital_name": "BV Chợ Rẫy",
  "severity_level": "Trung bình",
  "accuracy_score": 70.0, "completion_score": 55.0, "fluency_score": 40.0
}
```
- Chỉ `phone` bắt buộc. `aphasia_type` ∈ `Broca|Wernicke|Anomic|Global|Conduction|Mixed|Khác`
  (khác → 422). Có ≥1 điểm baseline → tạo Assessment + AssessmentResult (như lúc đăng ký).
- Field không gửi thì KHÔNG đè lên hồ sơ cũ.

**200:** `{ "patient_id": "uuid", "full_name": "...", "status": "claimed" | "updated" }`
(`claimed` = vừa gán mới; `updated` = đã là bệnh nhân của tôi, idempotent cập nhật).
**422:** số không hợp lệ (cần số VN 10-11 chữ số).
**404:** không bệnh nhân nào dùng số này — "bệnh nhân cần đăng ký kèm SĐT trước".
**409:** nhiều bệnh nhân trùng số (cần xác định thêm), HOẶC bệnh nhân chưa có plan, HOẶC
đã thuộc **bác sĩ khác** (không lộ tên bác sĩ kia).
⚠️ Bệnh nhân cũ đăng ký KHÔNG kèm sđt sẽ không claim được bằng cách này (đăng ký mới đã BẮT BUỘC sđt nên chỉ ảnh hưởng tài khoản cũ).

### GET `/therapist/me/patients` *(13.2 — bảng bệnh nhân, mockup Ảnh 1)*
Bảng bệnh nhân CỦA bác sĩ đang đăng nhập, kèm số liệu. Query optional: `severity`,
`aphasia_type`, `status` (`good`|`attention`, khác → 422), `search` (theo tên, không phân biệt
hoa thường), `limit` (mặc định 50), `offset` (0). `total` = tổng SAU filter.
```json
{
  "total": 2,
  "items": [
    { "patient_id": "uuid", "full_name": "Nguyễn Văn Hùng", "email": "...",
      "aphasia_type": "Broca", "severity_level": "Trung bình", "hospital_name": "BV Chợ Rẫy",
      "progress_week": 3.3, "avg_score_2days": 85.0, "streak_days": 1,
      "sessions_per_week": 1, "status": "good" }
  ]
}
```
Định nghĩa số liệu:
- `progress_week`: % hoàn thành CẤP PLAN (completion có sẵn — % assignment đã graded); `null` = chưa có dữ liệu.
- `avg_score_2days`: TB điểm 2 ngày qua (bỏ ngày trống); `null` = không có buổi có điểm.
- `streak_days`: chuỗi ngày luyện liên tiếp (cùng định nghĩa dashboard bệnh nhân).
- `sessions_per_week`: số NGÀY có luyện trong 7 ngày gần nhất (0-7, hiển thị "x/7").
- `status`: `attention` = KHÔNG có buổi graded nào trong 3 ngày qua; ngược lại `good`.
Bệnh nhân của bác sĩ khác và bệnh nhân tự do KHÔNG BAO GIỜ xuất hiện.

### GET `/therapist/dashboard-summary` *(13.3 — 4 thẻ + banner)*
Tổng quan tính TRÊN TẬP bệnh nhân của bác sĩ đăng nhập.
```json
{
  "total_patients": 2,
  "practicing": 1,
  "need_attention": 1,
  "weekly_completion": 3.3,
  "attention_list": [ { "patient_id": "uuid", "full_name": "Lê Thị Mai" } ]
}
```
- `practicing`: số bệnh nhân có ≥1 buổi graded trong 7 ngày qua.
- `need_attention`: số bệnh nhân KHÔNG có buổi graded nào trong 3 ngày qua (khớp `attention_list`
  cho banner "N bệnh nhân chưa luyện tập 3 ngày").
- `weekly_completion`: TB `progress_week` across bệnh nhân (bỏ null); `null` = chưa ai có dữ liệu.

### GET `/therapist/patients/{patient_id}` *(13.4 — chi tiết, mockup Ảnh 2)*
Chi tiết 1 bệnh nhân CỦA TÔI.
```json
{
  "patient": { "full_name": "Nguyễn Văn Hùng", "age": 64, "aphasia_type": "Broca",
               "severity_level": "Trung bình", "hospital_name": "BV Chợ Rẫy",
               "doctor_name": "BS. Trần Thanh Phúc" },
  "dashboard": { "...": "y hệt GET /patients/me/progress-dashboard (daily_scores 7 + 30 + streak + difficult_words)" },
  "stats": { "accuracy_score": 85.0, "completion_score": 3.3, "fluency_score": 45.0 },
  "avg_score_day": 85.0,
  "sessions_per_week": 1,
  "score_delta_vs_last_week": null,
  "insight": { "type": "warn", "text": "Hoàn thành thấp – bệnh nhân bỏ dở nhiều, cân nhắc giảm độ khó." }
}
```
- `age` tính từ date_of_birth; `doctor_name` = tên bác sĩ đang đăng nhập.
- `stats`: 3 chỉ số thành phần (mục "Phân tích thành phần") — CÙNG nguồn compute_patient_stats
  với insight; từng field `null` = chưa có dữ liệu.
- `score_delta_vs_last_week`: TB 7 ngày gần nhất − TB 7 ngày trước đó; `null` nếu 1 trong 2 cửa
  sổ không có dữ liệu.
- `insight`: rule-based, chọn tiêu chí YẾU NHẤT dưới ngưỡng 60 trong 3 metric
  (fluency/accuracy/completion) → `type:"warn"` + câu gợi ý; cả 3 ổn → `type:"ok"`
  "Tiến triển tốt – duy trì kế hoạch hiện tại."; chưa có dữ liệu → `type:"ok"` "Chưa đủ dữ liệu...".
**404:** bệnh nhân không tồn tại / của bác sĩ khác / tự do — 404 ĐỒNG NHẤT, không tiết lộ
bệnh nhân có tồn tại hay không.

---

## 7. Appointments — Lịch hẹn

Múi giờ: backend LƯU + TRẢ UTC (ISO 8601) — frontend tự hiển thị giờ địa phương.

### GET `/patients/me/appointments?from=YYYY-MM-DD&to=YYYY-MM-DD`
Lịch hẹn của bệnh nhân đang đăng nhập trong khoảng ngày (lọc theo `starts_at`).
`from`/`to` optional — mặc định: từ đầu THÁNG TRƯỚC đến hết THÁNG SAU. Sắp theo `starts_at`.
Yêu cầu đăng nhập, role = patient.
```json
[
  {
    "appointment_id": "uuid",
    "starts_at": "2026-07-20T02:00:00Z", "ends_at": "2026-07-20T03:00:00Z",
    "location": "BV Chợ Rẫy", "room": "P.204", "note": "Tái khám định kỳ",
    "doctor_name": "BS. Trần Thanh Phúc"
  }
]
```
`room`/`note` có thể `null`. Chưa có lịch -> `[]` (không 404).

### POST `/therapist/patients/{patient_id}/appointments`
Bác sĩ đặt lịch cho 1 bệnh nhân CỦA MÌNH (mask get_owned_patient — bệnh nhân của bác sĩ
khác/tự do → **404** đồng nhất). Yêu cầu đăng nhập, role = therapist.
```json
{
  "starts_at": "2026-07-20T02:00:00Z", "ends_at": "2026-07-20T03:00:00Z",
  "location": "BV Chợ Rẫy", "room": "P.204", "note": "Tái khám định kỳ"
}
```
- `room`/`note` optional. **422** nếu `ends_at <= starts_at`.
- **200**: trả lịch vừa tạo (shape giống phần tử GET ở trên, kèm `doctor_name` = tên bác sĩ đặt).

---

## Quy tắc chung cho mọi API

- Mọi lỗi trả về dạng: `{ "detail": "Nội dung lỗi bằng tiếng Việt" }`
- Ngày giờ dùng chuẩn ISO 8601 (`"2026-07-04T10:00:00Z"`)
- UUID luôn ở dạng chuỗi (không phải object)
- Token gửi qua header: `Authorization: Bearer <access_token>`
