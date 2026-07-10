"""
Router: auth — đăng ký / đăng nhập bằng JWT.

- POST /auth/register/patient   — đăng ký bệnh nhân, đăng ký xong tự đăng nhập luôn.
- POST /auth/register/therapist — đăng ký chuyên viên trị liệu.
- POST /auth/login              — đăng nhập, trả JWT token.
- get_current_user()            — dependency dùng chung cho endpoint cần đăng nhập sau này.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.security import (
    create_access_token,
    decode_access_token,
    hash_password,
    verify_password,
)
from app.models.assessment import Assessment, AssessmentResult
from app.models.enums import AssessmentStatus, AssessmentType
from app.models.user import Patient, Profile, Therapist, User
from app.schemas.auth import (
    LoginRequest,
    MeResponse,
    PatientRegisterRequest,
    TherapistRegisterRequest,
    TokenResponse,
)
from app.services.phone_service import normalize_phone
from app.services.plan_service import create_initial_plan

router = APIRouter(prefix="/auth", tags=["auth"])

# tokenUrl chỉ để Swagger UI biết endpoint lấy token; không ràng buộc logic.
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/login")


def _email_exists(db: Session, email: str) -> bool:
    """True nếu email đã tồn tại trong bảng users (mọi role)."""
    return db.query(User).filter(User.email == email).first() is not None


@router.post("/register/patient", response_model=TokenResponse, status_code=201)
def register_patient(payload: PatientRegisterRequest, db: Session = Depends(get_db)):
    """Đăng ký bệnh nhân. Email trùng -> 409. Sđt trùng bệnh nhân khác -> 409
    (Mô hình A: claim khớp theo sđt, không cho 2 bệnh nhân trùng số).
    Thành công -> trả token (tự đăng nhập)."""
    if _email_exists(db, payload.email):
        raise HTTPException(status_code=409, detail="Email đã được đăng ký")

    # Chống trùng số GIỮA CÁC BỆNH NHÂN (payload.phone_number đã chuẩn hóa bởi schema;
    # dữ liệu cũ trong DB có thể còn dạng thô -> so trên dạng chuẩn hóa cả 2 phía).
    # TODO(tối ưu): thêm cột phone_normalized + unique index khi dữ liệu lớn.
    existing_phones = db.query(Patient).filter(Patient.phone_number.isnot(None)).all()
    if any(
        normalize_phone(p.phone_number) == payload.phone_number for p in existing_phones
    ):
        raise HTTPException(status_code=409, detail="Số điện thoại đã được đăng ký")

    patient = Patient(
        full_name=payload.full_name,
        email=payload.email,
        password_hash=hash_password(payload.password),
        phone_number=payload.phone_number,
        date_of_birth=payload.date_of_birth,
        gender=payload.gender,
        aphasia_type=payload.aphasia_type,
        severity_level=payload.severity_level,
        hospital_name=payload.hospital_name,
        referring_doctor_name=payload.referring_doctor_name,
    )
    db.add(patient)
    db.flush()  # cần patient.id trước khi tạo plan

    # Tự tạo kế hoạch trị liệu + giao bài ngay (cùng transaction). Nếu lỗi -> để lan ra,
    # rollback toàn bộ, KHÔNG tạo tài khoản dở dang.
    create_initial_plan(db, patient)

    # "Kết quả đánh giá ban đầu": nếu bác sĩ/người nhà cung cấp ÍT NHẤT 1 trong 3 chỉ số,
    # lưu thành 1 Assessment + AssessmentResult (cùng transaction). Nếu CẢ 3 đều None ->
    # KHÔNG tạo gì (tránh dòng rác toàn NULL).
    #
    # type=AssessmentType.language là lựa chọn TẠM THỜI (chưa có enum mô tả đúng "đánh giá
    # ban đầu do bác sĩ nhập tay"). Nếu team muốn tách riêng, thêm 1 giá trị enum mới rồi
    # đổi ở đây — KHÔNG ảnh hưởng logic bên dưới.
    if any(
        v is not None
        for v in (payload.accuracy_score, payload.completion_score, payload.fluency_score)
    ):
        now = datetime.now(timezone.utc)
        assessment = Assessment(
            patient_id=patient.id,
            type=AssessmentType.language,
            status=AssessmentStatus.completed,
            started_at=now,
            completed_at=now,
        )
        db.add(assessment)
        db.flush()  # cần assessment.id trước khi tạo result
        # Giá trị None -> để None trong DB, KHÔNG tự điền 0.
        db.add(
            AssessmentResult(
                assessment_id=assessment.id,
                accuracy_score=payload.accuracy_score,
                completion_score=payload.completion_score,
                fluency_score=payload.fluency_score,
            )
        )

    # Profile (1-1 với User): tạo trong CÙNG transaction NẾU có ít nhất 1 trong các field
    # Profile được cung cấp (địa chỉ / SĐT người chăm sóc). Cả 2 để trống -> KHÔNG tạo Profile,
    # tránh dòng rác toàn NULL (cùng nguyên tắc đã áp dụng cho Assessment ở trên).
    #   - address         -> Profile.address
    #   - caregiver_phone -> Profile.emergency_contact
    address = payload.address.strip() if payload.address else ""
    caregiver_phone = payload.caregiver_phone.strip() if payload.caregiver_phone else ""
    if address or caregiver_phone:
        db.add(
            Profile(
                user_id=patient.id,
                address=address or None,
                emergency_contact=caregiver_phone or None,
            )
        )

    db.commit()
    db.refresh(patient)

    token = create_access_token(user_id=str(patient.id), role=patient.role.value)
    return TokenResponse(access_token=token, role=patient.role.value)


@router.post("/register/therapist", response_model=TokenResponse, status_code=201)
def register_therapist(payload: TherapistRegisterRequest, db: Session = Depends(get_db)):
    """Đăng ký chuyên viên trị liệu. Email trùng -> 409. Thành công -> trả token."""
    if _email_exists(db, payload.email):
        raise HTTPException(status_code=409, detail="Email đã được đăng ký")

    therapist = Therapist(
        full_name=payload.full_name,
        email=payload.email,
        password_hash=hash_password(payload.password),
        phone_number=payload.phone_number,
        license_no=payload.license_no,
        specialization=payload.specialization,
    )
    db.add(therapist)
    db.commit()
    db.refresh(therapist)

    token = create_access_token(user_id=str(therapist.id), role=therapist.role.value)
    return TokenResponse(access_token=token, role=therapist.role.value)


@router.post("/login", response_model=TokenResponse)
def login(payload: LoginRequest, db: Session = Depends(get_db)):
    """
    Đăng nhập bằng email + password.

    Sai email HOẶC sai mật khẩu đều trả cùng 1 message chung chung
    "Email hoặc mật khẩu không đúng" — KHÔNG tiết lộ email nào đã đăng ký (chuẩn bảo mật).
    """
    user = db.query(User).filter(User.email == payload.email).first()
    if user is None or not verify_password(payload.password, user.password_hash):
        raise HTTPException(status_code=401, detail="Email hoặc mật khẩu không đúng")

    token = create_access_token(user_id=str(user.id), role=user.role.value)
    return TokenResponse(access_token=token, role=user.role.value)


def get_current_user(
    token: str = Depends(oauth2_scheme),
    db: Session = Depends(get_db),
) -> User:
    """
    Dependency dùng chung cho endpoint cần đăng nhập: decode JWT -> query User.
    Token sai/hết hạn hoặc user không tồn tại -> 401.
    """
    credentials_error = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Token không hợp lệ hoặc đã hết hạn",
        headers={"WWW-Authenticate": "Bearer"},
    )

    payload = decode_access_token(token)
    if payload is None:
        raise credentials_error

    user_id = payload.get("sub")
    if user_id is None:
        raise credentials_error

    try:
        user_uuid = uuid.UUID(user_id)
    except (ValueError, TypeError):
        raise credentials_error

    user = db.query(User).filter(User.id == user_uuid).first()
    if user is None:
        raise credentials_error

    return user


@router.get("/me", response_model=MeResponse)
def read_me(current_user: User = Depends(get_current_user)):
    """
    Trả thông tin user đang đăng nhập (đọc từ JWT).

    MỤC ĐÍCH: Frontend gọi endpoint này NGAY LÚC MỞ APP (dùng token đã lưu trên máy) để
    kiểm tra token còn hợp lệ không:
      - 200 OK  -> token còn sống, vào thẳng Trang chủ, KHÔNG cần đăng nhập lại.
      - 401     -> token sai/hết hạn, mới hiện màn đăng nhập.
    """
    return MeResponse(
        user_id=str(current_user.id),
        full_name=current_user.full_name,
        email=current_user.email,
        role=current_user.role.value,
    )
