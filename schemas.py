from pydantic import BaseModel, Field, EmailStr, field_validator
from typing import List, Optional, Union
from datetime import datetime, date
from uuid import UUID

class UserCreate(BaseModel):
    email: str
    password: str

class UserLogin(BaseModel):
    email: str
    password: str

class StudentCreate(BaseModel):
    name: str = Field(..., example="홍길동")
    company_id: Optional[Union[UUID, str]] = None
    consultant: Optional[int] = None
    grade_id: Optional[Union[UUID, str]] = None
    cooperation_submitted_date: Optional[Union[date, str]] = None
    cooperation_submitted_place: Optional[str] = None
    assignment_date: Optional[Union[date, str]] = None
    ward: Optional[str] = None
    name_katakana: Optional[str] = None
    gender: Optional[str] = None
    birth_date: Optional[Union[date, str]] = None
    nationality: Optional[str] = None
    has_spouse: Optional[bool] = None
    japanese_level: Optional[str] = None
    passport_number: Optional[str] = None
    residence_card_number: Optional[str] = None
    residence_card_start: Optional[Union[date, str]] = None
    residence_card_expiry: Optional[Union[date, str]] = None
    local_address: Optional[str] = None
    address: Optional[str] = None
    phone: Optional[str] = None
    experience_over_2_years: Optional[bool] = None
    arrival_type: Optional[str] = None
    entry_date: Optional[Union[date, str]] = None
    interview_date: Optional[Union[date, str]] = None
    pre_guidance_date: Optional[Union[date, str]] = None
    orientation_date: Optional[Union[date, str]] = None
    certification_application_date: Optional[Union[date, str]] = None
    visa_application_date: Optional[Union[date, str]] = None
    passport_expiration_date: Optional[Union[date, str]] = None
    student_type: Optional[str] = None
    current_room_id: Optional[Union[UUID, str]] = None
    interview_date: Optional[Union[date, str]] = None
    facebook_name: Optional[str] = None
    visa_year: Optional[str] = None
    
    # 방 관련 정보
    room_id: Optional[str] = Field(None, description="방 ID (기존 방에 배정하는 경우)")
    check_in_date: Optional[str] = Field(None, description="입주일 (YYYY-MM-DD)")
    room_note: Optional[str] = Field(None, description="입주 관련 비고사항")

    @field_validator('company_id', 'grade_id', 'current_room_id', mode='before')
    @classmethod
    def validate_uuid_fields(cls, v):
        if v == "" or v is None:
            return None
        return v

    @field_validator('cooperation_submitted_date', 'assignment_date', 'birth_date', 
                    'residence_card_start', 'residence_card_expiry', 'entry_date', 
                    'interview_date', 'pre_guidance_date', 'orientation_date', 
                    'certification_application_date', 'visa_application_date', 
                    'passport_expiration_date', mode='before')
    @classmethod
    def validate_date_fields(cls, v):
        if v == "" or v is None:
            return None
        return v

    @field_validator('name_katakana', 'nationality', 'passport_number', 'residence_card_number',
                    'local_address', 'address', 'phone', 'arrival_type', 'student_type',
                    'cooperation_submitted_place', 'ward', 'japanese_level', mode='before')
    @classmethod
    def validate_string_fields(cls, v):
        if v == "" or v is None:
            return None
        return v

class StudentUpdate(BaseModel):
    name: Optional[str] = None
    email: Optional[str] = None
    company_id: Optional[str] = None
    consultant: Optional[int] = None
    phone: Optional[str] = None
    grade_id: Optional[str] = None
    cooperation_submitted_date: Optional[date] = None
    cooperation_submitted_place: Optional[str] = None
    assignment_date: Optional[date] = None
    ward: Optional[str] = None
    name_katakana: Optional[str] = None
    gender: Optional[str] = None
    birth_date: Optional[date] = None
    nationality: Optional[str] = None
    has_spouse: Optional[bool] = None
    japanese_level: Optional[str] = None
    passport_number: Optional[str] = None
    residence_card_number: Optional[str] = None
    residence_card_start: Optional[date] = None
    residence_card_expiry: Optional[date] = None
    resignation_date: Optional[date] = None
    local_address: Optional[str] = None
    address: Optional[str] = None
    experience_over_2_years: Optional[bool] = None
    status: Optional[str] = None
    arrival_type: Optional[str] = None
    entry_date: Optional[date] = None
    interview_date: Optional[date] = None
    pre_guidance_date: Optional[date] = None
    orientation_date: Optional[date] = None
    certification_application_date: Optional[date] = None
    visa_application_date: Optional[date] = None
    passport_expiration_date: Optional[date] = None
    student_type: Optional[str] = None
    current_room_id: Optional[UUID] = None
    facebook_name: Optional[str] = None
    visa_year: Optional[str] = None

class StudentResponse(BaseModel):
    id: str
    name: str
    email: str
    created_at: datetime
    company_id: Optional[str] = None
    consultant: Optional[int] = None
    phone: Optional[str] = None
    avatar: Optional[str] = None
    grade_id: Optional[str] = None
    cooperation_submitted_date: Optional[date] = None
    cooperation_submitted_place: Optional[str] = None
    assignment_date: Optional[date] = None
    ward: Optional[str] = None
    name_katakana: Optional[str] = None
    gender: Optional[str] = None
    birth_date: Optional[date] = None
    nationality: Optional[str] = None
    has_spouse: Optional[bool] = None
    japanese_level: Optional[str] = None
    passport_number: Optional[str] = None
    residence_card_number: Optional[str] = None
    residence_card_start: Optional[date] = None
    residence_card_expiry: Optional[date] = None
    resignation_date: Optional[date] = None
    local_address: Optional[str] = None
    address: Optional[str] = None
    experience_over_2_years: Optional[bool] = None
    status: Optional[str] = None
    arrival_type: Optional[str] = None
    facebook_name: Optional[str] = None
    visa_year: Optional[str] = None

    class Config:
        from_attributes = True
        json_encoders = {
            UUID: str  # UUID를 문자열로 변환
        }

class InvoiceItemCreate(BaseModel):
    name: str
    unit_price: int = Field(gt=0)  # 단가
    quantity: int = Field(default=1, ge=1)  # 수량 추가
    amount: int = Field(gt=0)  # 금액
    sort_order: int = 0
    memo: Optional[str] = None
    type: Optional[str] = None

class InvoiceCreate(BaseModel):
    student_id: UUID
    year: int
    month: int = Field(ge=1, le=12)
    items: List[InvoiceItemCreate]
    invoice_number: Optional[str] = None

class InvoiceUpdate(BaseModel):
    invoice_id: UUID
    year: int
    month: int = Field(ge=1, le=12)
    items: List[InvoiceItemCreate]
    invoice_number: Optional[str] = None

class InvoiceItemResponse(BaseModel):
    id: UUID
    name: str
    unit_price: int
    quantity: int
    amount: int
    sort_order: int
    created_at: datetime

    class Config:
        from_attributes = True

class InvoiceResponse(BaseModel):
    id: UUID
    student_id: UUID
    year: int
    month: int
    created_at: datetime
    updated_at: datetime
    items: List[InvoiceItemResponse]

    class Config:
        from_attributes = True

class BuildingCreate(BaseModel):
    name: str = Field(..., example="SOUSEI HANOI")
    address: Optional[str] = Field(None, example="大阪府大阪市東住吉区矢田3-7-9")
    total_rooms: Optional[int] = Field(None, example=50)
    note: Optional[str] = Field(None, example="メモ")

class BuildingUpdate(BaseModel):
    name: Optional[str] = None
    address: Optional[str] = None
    total_rooms: Optional[int] = None
    note: Optional[str] = None

class BuildingResponse(BaseModel):
    id: str
    name: str
    address: Optional[str] = None
    total_rooms: Optional[int] = None
    note: Optional[str] = None

    class Config:
        from_attributes = True
        json_encoders = {
            UUID: str
        }

class RoomCreate(BaseModel):
    building_id: str = Field(..., example="building-uuid")
    room_number: str = Field(..., example="101")
    rent: Optional[int] = Field(None, example=500000)
    floor: Optional[int] = Field(None, example=1)
    capacity: Optional[int] = Field(None, example=4)
    is_available: Optional[bool] = Field(True, example=True)
    note: Optional[str] = Field(None, example="비고사항")

class RoomUpdate(BaseModel):
    room_number: Optional[str] = None
    rent: Optional[int] = None
    floor: Optional[int] = None
    capacity: Optional[int] = None
    is_available: Optional[bool] = None
    note: Optional[str] = None

class RoomResponse(BaseModel):
    id: str
    building_id: str
    room_number: str
    rent: Optional[int] = None
    floor: Optional[int] = None
    capacity: Optional[int] = None
    is_available: bool
    note: Optional[str] = None

    class Config:
        from_attributes = True
        json_encoders = {
            UUID: str
        }

# 방 관리 관련 스키마
class ChangeResidenceRequest(BaseModel):
    new_room_id: Optional[str] = Field(None, description="새로운 방 ID (None이면 퇴실만 처리)")
    change_date: str = Field(..., description="이사일 또는 퇴실일 (YYYY-MM-DD)")
    note: Optional[str] = Field(None, description="이사 또는 퇴실 비고사항")

class CheckInRequest(BaseModel):
    student_id: str = Field(..., description="학생 ID")
    check_in_date: str = Field(..., description="입주일 (YYYY-MM-DD)")
    note: Optional[str] = Field(None, description="입주 비고사항")

class CheckOutRequest(BaseModel):
    student_id: str = Field(..., description="학생 ID")
    check_out_date: str = Field(..., description="퇴실일 (YYYY-MM-DD)")
    note: Optional[str] = Field(None, description="퇴실 비고사항")

class AssignRoomRequest(BaseModel):
    room_id: Optional[str] = Field(None, description="방 ID (None이면 방 배정 해제)")

class NewResidenceRequest(BaseModel):
    new_room_id: str = Field(..., description="방 ID")
    change_date: str = Field(..., description="입주일 (YYYY-MM-DD)")
    check_out_date: Optional[str] = Field(None, description="퇴실일 (YYYY-MM-DD, None이면 현재 거주 중)")
    note: Optional[str] = Field(None, description="거주 관련 비고사항")

# 방 로그 관련 스키마
class RoomLogResponse(BaseModel):
    id: str
    room_id: Optional[str] = None
    student_id: Optional[str] = None
    action: str
    action_date: date
    note: Optional[str] = None
    room: Optional[dict] = None
    student: Optional[dict] = None

    class Config:
        from_attributes = True
        json_encoders = {
            UUID: str
        }

# 거주자 관련 스키마
class ResidentResponse(BaseModel):
    id: str
    room_id: str
    student_id: str
    check_in_date: date
    check_out_date: Optional[date] = None
    is_active: bool
    note: Optional[str] = None
    created_at: datetime
    updated_at: datetime
    room: Optional[dict] = None
    student: Optional[dict] = None

    class Config:
        from_attributes = True
        json_encoders = {
            UUID: str
        }

# 방 용량 상태 스키마
class RoomCapacityStatus(BaseModel):
    room_id: str
    room_number: str
    capacity: Optional[int] = None
    current_residents: int
    available_spots: Optional[int] = None
    usage_percentage: Optional[float] = None
    is_full: bool
    can_accept_more: bool

# 빈 방 옵션 스키마
class EmptyRoomOption(BaseModel):
    value: str
    label: str
    room_number: str
    floor: Optional[int] = None
    capacity: Optional[int] = None
    current_residents: int
    available_spots: Optional[int] = None
    rent: Optional[int] = None
    note: Optional[str] = None

# 빌딩 옵션 스키마
class BuildingOption(BaseModel):
    value: str
    label: str
    address: Optional[str] = None
    empty_rooms_count: int

# 사용 가능한 방 스키마
class AvailableRoom(BaseModel):
    id: str
    room_number: str
    floor: Optional[int] = None
    capacity: Optional[int] = None
    current_residents: int
    available_spots: Optional[int] = None
    rent: Optional[int] = None
    note: Optional[str] = None
    is_available_for_checkin: bool
    building: dict

# 광열비 관련 스키마
class ChargeItemCreate(BaseModel):
    charge_type: str = Field(..., description="청구 항목 유형 (rent, electricity, water, gas, etc.)")
    period_start: Optional[str] = Field(None, description="기간 시작일 (YYYY-MM-DD)")
    period_end: Optional[str] = Field(None, description="기간 종료일 (YYYY-MM-DD)")
    amount: Optional[float] = Field(None, description="항목별 전체 금액")
    unit_price: Optional[float] = Field(None, description="단가")
    quantity: Optional[float] = Field(None, description="사용량, 일수 등")
    memo: Optional[str] = Field(None, description="비고사항")

class ChargeItemUpdate(BaseModel):
    charge_type: Optional[str] = Field(None, description="청구 항목 유형")
    period_start: Optional[str] = Field(None, description="기간 시작일 (YYYY-MM-DD)")
    period_end: Optional[str] = Field(None, description="기간 종료일 (YYYY-MM-DD)")
    amount: Optional[float] = Field(None, description="항목별 전체 금액")
    unit_price: Optional[float] = Field(None, description="단가")
    quantity: Optional[float] = Field(None, description="사용량, 일수 등")
    memo: Optional[str] = Field(None, description="비고사항")

class ChargeItemAllocationCreate(BaseModel):
    student_id: str = Field(..., description="학생 ID")
    amount: float = Field(..., description="학생별 부담금액")
    days_used: Optional[int] = Field(None, description="해당 항목 기간 중 머문 일수")
    memo: Optional[str] = Field(None, description="비고사항")

class ChargeItemAllocationUpdate(BaseModel):
    amount: Optional[float] = Field(None, description="학생별 부담금액")
    days_used: Optional[int] = Field(None, description="해당 항목 기간 중 머문 일수")
    memo: Optional[str] = Field(None, description="비고사항")

class ChargeItemResponse(BaseModel):
    id: str
    room_charge_id: str
    charge_type: str
    period_start: Optional[date] = None
    period_end: Optional[date] = None
    amount: Optional[float] = None
    unit_price: Optional[float] = None
    quantity: Optional[float] = None
    memo: Optional[str] = None
    allocations: Optional[List[dict]] = None

    class Config:
        from_attributes = True
        json_encoders = {
            UUID: str
        }

class ChargeItemAllocationResponse(BaseModel):
    id: str
    charge_item_id: str
    student_id: str
    amount: float
    days_used: Optional[int] = None
    memo: Optional[str] = None
    student: Optional[dict] = None

    class Config:
        from_attributes = True
        json_encoders = {
            UUID: str
        }

class RoomChargeCreate(BaseModel):
    student_id: str = Field(..., description="학생 ID")
    room_id: str = Field(..., description="방 ID")
    charge_month: str = Field(..., description="청구 월 (YYYY-MM-DD)")
    total_amount: Optional[float] = Field(None, description="총 금액")
    note: Optional[str] = Field(None, description="비고사항")
    charge_items: Optional[List[ChargeItemCreate]] = Field(None, description="청구 항목 목록")

class RoomChargeUpdate(BaseModel):
    total_amount: Optional[float] = Field(None, description="총 금액")
    note: Optional[str] = Field(None, description="비고사항")

class RoomChargeResponse(BaseModel):
    id: str
    student_id: str
    room_id: str
    charge_month: date
    total_amount: Optional[float] = None
    created_at: datetime
    note: Optional[str] = None
    student: Optional[dict] = None
    room: Optional[dict] = None
    charge_items: Optional[List[ChargeItemResponse]] = None

    class Config:
        from_attributes = True
        json_encoders = {
            UUID: str
        }

class RoomUtilityCreate(BaseModel):
    room_id: str = Field(..., description="방 ID")
    utility_type: str = Field(..., description="공과금 유형 (electricity, water, gas 등)")
    period_start: str = Field(..., description="검침 시작일 (YYYY-MM-DD)")
    period_end: str = Field(..., description="검침 종료일 (YYYY-MM-DD)")
    usage: Optional[float] = Field(None, description="사용량")
    unit_price: Optional[float] = Field(None, description="단가")
    total_amount: Optional[float] = Field(None, description="총 요금")
    charge_month: str = Field(..., description="청구 월 (YYYY-MM-DD)")
    memo: Optional[str] = Field(None, description="비고사항")

class RoomUtilityUpdate(BaseModel):
    utility_type: Optional[str] = Field(None, description="공과금 유형")
    period_start: Optional[str] = Field(None, description="검침 시작일 (YYYY-MM-DD)")
    period_end: Optional[str] = Field(None, description="검침 종료일 (YYYY-MM-DD)")
    usage: Optional[float] = Field(None, description="사용량")
    unit_price: Optional[float] = Field(None, description="단가")
    total_amount: Optional[float] = Field(None, description="총 요금")
    charge_month: Optional[str] = Field(None, description="청구 월 (YYYY-MM-DD)")
    memo: Optional[str] = Field(None, description="비고사항")

class RoomUtilityResponse(BaseModel):
    id: str
    room_id: str
    utility_type: str
    period_start: date
    period_end: date
    usage: Optional[float] = None
    unit_price: Optional[float] = None
    total_amount: Optional[float] = None
    charge_month: date
    memo: Optional[str] = None
    created_at: datetime
    room: Optional[dict] = None

    class Config:
        from_attributes = True
        json_encoders = {
            UUID: str
        }

class UtilityAllocationCreate(BaseModel):
    student_id: str = Field(..., description="학생 ID")
    days_used: int = Field(..., description="해당 공과금 기간 중 머문 일수")
    amount: float = Field(..., description="학생별 부담금액")
    usage_ratio: Optional[float] = Field(None, description="사용량 비율")
    memo: Optional[str] = Field(None, description="비고사항")

class UtilityAllocationUpdate(BaseModel):
    days_used: Optional[int] = Field(None, description="머문 일수")
    amount: Optional[float] = Field(None, description="부담금액")
    usage_ratio: Optional[float] = Field(None, description="사용량 비율")
    memo: Optional[str] = Field(None, description="비고사항")

class UtilityAllocationResponse(BaseModel):
    id: str
    utility_id: str
    student_id: str
    days_used: int
    amount: float
    usage_ratio: Optional[float] = None
    memo: Optional[str] = None
    created_at: datetime
    student: Optional[dict] = None

    class Config:
        from_attributes = True
        json_encoders = {
            UUID: str
        }

class ResidenceCardHistoryCreate(BaseModel):
    student_id: str = Field(..., description="학생 ID")
    card_number: str = Field(..., description="카드 번호")
    start_date: str = Field(..., description="시작일 (YYYY-MM-DD)")
    expiry_date: str = Field(..., description="만료일 (YYYY-MM-DD)")
    note: Optional[str] = Field(None, description="비고사항")

class ResidenceCardHistoryUpdate(BaseModel):
    card_number: Optional[str] = Field(None, description="카드 번호")
    start_date: Optional[str] = Field(None, description="시작일 (YYYY-MM-DD)")
    expiry_date: Optional[str] = Field(None, description="만료일 (YYYY-MM-DD)")
    note: Optional[str] = Field(None, description="비고사항")

class ResidenceCardHistoryResponse(BaseModel):
    id: str
    student_id: str
    card_number: str
    start_date: date
    expiry_date: date
    registered_at: datetime
    note: Optional[str] = None

    class Config:
        from_attributes = True
        json_encoders = {
            UUID: str
        }

class VisaInfoUpdate(BaseModel):
    residence_card_number: Optional[str] = Field(None, description="카드 번호")
    residence_card_start: Optional[Union[date, str]] = Field(None, description="시작일")
    residence_card_expiry: Optional[Union[date, str]] = Field(None, description="만료일")
    passport_number: Optional[str] = Field(None, description="여권 번호")
    passport_expiration_date: Optional[Union[date, str]] = Field(None, description="여권 만료일")
    visa_application_date: Optional[Union[date, str]] = Field(None, description="비자 신청일")
    note: Optional[str] = Field(None, description="비고사항")

    @field_validator('residence_card_start', 'residence_card_expiry', 'passport_expiration_date', 'visa_application_date', mode='before')
    @classmethod
    def validate_date_fields(cls, v):
        if v == "" or v is None:
            return None
        return v

class AutoAllocationRequest(BaseModel):
    allocation_method: str = Field(..., description="배분 방법 (days_based 또는 usage_based)")
    include_inactive_residents: bool = Field(False, description="퇴실한 학생도 포함할지 여부")