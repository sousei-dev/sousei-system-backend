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
    # email: Optional[str] = None
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
    building_type: Optional[str] = Field(None, example="mansion")

class BuildingUpdate(BaseModel):
    name: Optional[str] = None
    address: Optional[str] = None
    total_rooms: Optional[int] = None
    note: Optional[str] = None

class BuildingResponse(BaseModel):
    name: str
    address: Optional[str] = None
    total_rooms: Optional[int] = None
    note: Optional[str] = None
    building_type: Optional[str] = None

    class Config:
        from_attributes = True
        json_encoders = {
            UUID: str
        }

class RoomCreate(BaseModel):
    building_id: str = Field(..., example="building-uuid")
    room_number: str = Field(..., example="101")
    rent: Optional[int] = Field(None, example=500000)
    maintenance: Optional[int] = Field(None, example=50000)
    service: Optional[int] = Field(None, example=50000)
    floor: Optional[int] = Field(None, example=1)
    capacity: Optional[int] = Field(None, example=4)
    is_available: Optional[bool] = Field(True, example=True)
    note: Optional[str] = Field(None, example="비고사항")

class RoomUpdate(BaseModel):
    room_number: Optional[str] = None
    rent: Optional[int] = None
    maintenance: Optional[int] = None
    service: Optional[int] = None
    floor: Optional[int] = None
    capacity: Optional[int] = None
    is_available: Optional[bool] = None
    note: Optional[str] = None

class RoomResponse(BaseModel):
    id: Optional[Union[UUID, str]] = None
    building_id: Optional[Union[UUID, str]] = None
    room_number: str
    rent: Optional[int] = None
    maintenance: Optional[int] = None
    service: Optional[int] = None
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
    resident_id: str
    resident_type: str
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
    maintenance: Optional[int] = None
    service: Optional[int] = None
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
    maintenance: Optional[int] = None
    service: Optional[int] = None
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
    residence_card_number: str = Field(..., description="카드 번호")
    residence_card_start: Union[date, str] = Field(..., description="시작일")
    residence_card_expiry: Union[date, str] = Field(..., description="만료일")
    visa_application_date: Union[date, str] = Field(..., description="비자 신청일")
    year: str = Field(..., description="갱신년째")
    note: Optional[str] = Field(None, description="비고사항")

    @field_validator('residence_card_start', 'residence_card_expiry', 'residence_card_number', 'year', mode='before')
    @classmethod
    def validate_date_fields(cls, v):
        if v == "" or v is None:
            return None
        return v

class AutoAllocationRequest(BaseModel):
    allocation_method: str = Field(..., description="배분 방법 (days_based 또는 usage_based)")
    include_inactive_residents: bool = Field(False, description="퇴실한 학생도 포함할지 여부")

class DatabaseLogCreate(BaseModel):
    table_name: str = Field(..., description="테이블 이름")
    record_id: str = Field(..., description="레코드 ID")
    action: str = Field(..., description="작업 유형 (CREATE, UPDATE, DELETE)")
    user_id: Optional[str] = Field(None, description="작업한 사용자 ID")
    old_values: Optional[str] = Field(None, description="변경 전 값 (JSON)")
    new_values: Optional[str] = Field(None, description="변경 후 값 (JSON)")
    changed_fields: Optional[str] = Field(None, description="변경된 필드들 (JSON)")
    ip_address: Optional[str] = Field(None, description="IP 주소")
    user_agent: Optional[str] = Field(None, description="User Agent")
    note: Optional[str] = Field(None, description="추가 메모")

class DatabaseLogResponse(BaseModel):
    id: str
    table_name: str
    record_id: str
    action: str
    user_id: Optional[str] = None
    old_values: Optional[str] = None
    new_values: Optional[str] = None
    changed_fields: Optional[str] = None
    ip_address: Optional[str] = None
    user_agent: Optional[str] = None
    created_at: datetime
    note: Optional[str] = None

    class Config:
        from_attributes = True
        json_encoders = {
            UUID: str
        }

class ElderlyCreate(BaseModel):
    name: str = Field(..., example="田中太郎")
    email: Optional[str] = Field(None, example="tanaka@example.com")
    phone: Optional[str] = Field(None, example="090-1234-5678")
    avatar: Optional[str] = Field(None, example="/src/assets/images/avatars/avatar-1.png")
    name_katakana: Optional[str] = Field(None, example="タナカタロウ")
    gender: Optional[str] = Field(None, example="男性")
    birth_date: Optional[Union[date, str]] = Field(None, example="1940-01-01")
    status: Optional[str] = Field("ACTIVE", example="ACTIVE")
    current_room_id: Optional[Union[UUID, str]] = Field(None, example="room-uuid")
    care_level: Optional[str] = Field(None, example="要介護1")

    @field_validator('current_room_id', mode='before')
    @classmethod
    def validate_uuid_fields(cls, v):
        if v == "" or v is None:
            return None
        return v

    @field_validator('birth_date', mode='before')
    @classmethod
    def validate_date_fields(cls, v):
        if v == "" or v is None:
            return None
        return v

    @field_validator('name_katakana', 'phone', 'gender', 'care_level', mode='before')
    @classmethod
    def validate_string_fields(cls, v):
        if v == "" or v is None:
            return None
        return v

class ElderlyUpdate(BaseModel):
    name: Optional[str] = None
    email: Optional[str] = None
    phone: Optional[str] = None
    avatar: Optional[str] = None
    name_katakana: Optional[str] = None
    gender: Optional[str] = None
    birth_date: Optional[date] = None
    status: Optional[str] = None
    current_room_id: Optional[UUID] = None
    care_level: Optional[str] = None

class ElderlyResponse(BaseModel):
    id: str
    name: str
    email: Optional[str] = None
    created_at: datetime
    phone: Optional[str] = None
    avatar: Optional[str] = None
    name_katakana: Optional[str] = None
    gender: Optional[str] = None
    birth_date: Optional[date] = None
    status: Optional[str] = None
    current_room_id: Optional[str] = None
    care_level: Optional[str] = None
    current_room: Optional[dict] = None

    class Config:
        from_attributes = True
        json_encoders = {
            UUID: str  # UUID를 문자열로 변환
        }

class ElderlyContractCreate(BaseModel):
    elderly_id: str = Field(..., description="고령자 ID")
    room_id: Optional[str] = Field(None, description="방 ID")
    base_rent: int = Field(..., description="기본 임대료")
    common_fee: Optional[int] = Field(0, description="공용부과금")
    service_fee: Optional[int] = Field(0, description="서비스 요금")
    deposit: Optional[int] = Field(0, description="보증금")
    contract_start: Union[date, str] = Field(..., description="계약 시작일")
    contract_end: Optional[Union[date, str]] = Field(None, description="계약 종료일")

    @field_validator('contract_start', 'contract_end', mode='before')
    @classmethod
    def validate_date_fields(cls, v):
        if v == "" or v is None:
            return None
        return v

class ElderlyContractUpdate(BaseModel):
    room_id: Optional[str] = None
    base_rent: Optional[int] = None
    common_fee: Optional[int] = None
    service_fee: Optional[int] = None
    deposit: Optional[int] = None
    contract_start: Optional[date] = None
    contract_end: Optional[date] = None

class ElderlyContractResponse(BaseModel):
    id: str
    elderly_id: Optional[str] = None
    room_id: Optional[str] = None
    base_rent: int
    common_fee: Optional[int] = None
    service_fee: Optional[int] = None
    deposit: Optional[int] = None
    contract_start: date
    contract_end: Optional[date] = None
    created_at: datetime
    elderly: Optional[dict] = None
    room: Optional[dict] = None

    class Config:
        from_attributes = True
        json_encoders = {
            UUID: str
        }

class ElderlyInvoiceItemCreate(BaseModel):
    elderly_invoice_id: str = Field(..., description="고령자 청구서 ID")
    name: str = Field(..., description="항목명")
    usage_quantity: Optional[float] = Field(None, description="사용량")
    amount: int = Field(..., description="금액")
    sort_order: Optional[int] = Field(0, description="정렬 순서")
    memo: Optional[str] = Field(None, description="메모")

class ElderlyInvoiceItemUpdate(BaseModel):
    name: Optional[str] = None
    usage_quantity: Optional[float] = None
    amount: Optional[int] = None
    sort_order: Optional[int] = None
    memo: Optional[str] = None

class ElderlyInvoiceItemResponse(BaseModel):
    id: str
    elderly_invoice_id: str
    name: str
    usage_quantity: Optional[float] = None
    amount: int
    sort_order: Optional[int] = None
    memo: Optional[str] = None

    class Config:
        from_attributes = True
        json_encoders = {
            UUID: str
        }

class ElderlyInvoiceCreate(BaseModel):
    elderly_contract_id: str = Field(..., description="고령자 계약 ID")
    invoice_date: Union[date, str] = Field(..., description="청구서 날짜")
    due_date: Optional[Union[date, str]] = Field(None, description="납부 기한")
    total_amount: Optional[int] = Field(None, description="총 금액")
    status: Optional[str] = Field("unpaid", description="상태")

    @field_validator('invoice_date', 'due_date', mode='before')
    @classmethod
    def validate_date_fields(cls, v):
        if v == "" or v is None:
            return None
        return v

class ElderlyInvoiceUpdate(BaseModel):
    invoice_date: Optional[date] = None
    due_date: Optional[date] = None
    total_amount: Optional[int] = None
    status: Optional[str] = None

class ElderlyInvoiceResponse(BaseModel):
    id: str
    elderly_contract_id: Optional[str] = None
    invoice_date: date
    due_date: Optional[date] = None
    total_amount: Optional[int] = None
    status: Optional[str] = None
    created_at: datetime
    elderly_contract: Optional[dict] = None
    items: Optional[List[ElderlyInvoiceItemResponse]] = None

    class Config:
        from_attributes = True
        json_encoders = {
            UUID: str
        }

class CareItemResponse(BaseModel):
    id: int
    name: str
    category: Optional[str] = None
    price: Optional[int] = None
    unit: Optional[str] = None
    description: Optional[str] = None
    is_active: Optional[bool] = True
    created_at: datetime

    class Config:
        from_attributes = True


class CareMealPriceCreate(BaseModel):
    meal_type: str = Field(..., description="식사 유형 (breakfast, lunch, dinner)")
    price: int = Field(..., description="1회 식사 단가")
    is_active: Optional[bool] = Field(True, description="활성화 여부")


class CareMealPriceUpdate(BaseModel):
    meal_type: Optional[str] = Field(None, description="식사 유형")
    price: Optional[int] = Field(None, description="1회 식사 단가")
    is_active: Optional[bool] = Field(None, description="활성화 여부")


class CareMealPriceResponse(BaseModel):
    id: str
    meal_type: str
    price: int
    is_active: bool
    created_at: datetime

    class Config:
        from_attributes = True
        json_encoders = {
            UUID: str
        }


class CareUtilityPriceCreate(BaseModel):
    utility_type: str = Field(..., description="공과금 유형 (electricity, water, gas)")
    price_per_unit: int = Field(..., description="단위당 요금")
    unit: str = Field(..., description="단위 (예: kWh, m3)")
    is_active: Optional[bool] = Field(True, description="활성화 여부")


class CareUtilityPriceUpdate(BaseModel):
    utility_type: Optional[str] = Field(None, description="공과금 유형")
    price_per_unit: Optional[int] = Field(None, description="단위당 요금")
    unit: Optional[str] = Field(None, description="단위")
    is_active: Optional[bool] = Field(None, description="활성화 여부")


class CareUtilityPriceResponse(BaseModel):
    id: str
    utility_type: str
    price_per_unit: int
    unit: str
    is_active: bool
    created_at: datetime

    class Config:
        from_attributes = True
        json_encoders = {
            UUID: str
        }

# Monthly Items 스키마
class BillingMonthlyItemCreate(BaseModel):
    student_id: str = Field(..., description="학생 ID")
    item_name: str = Field(..., description="항목 이름")
    memo: Optional[str] = Field(None, description="메모")

class BillingMonthlyItemUpdate(BaseModel):
    amount: Optional[float] = Field(None, description="금액")
    memo: Optional[str] = Field(None, description="메모")

class BillingMonthlyItemResponse(BaseModel):
    id: str
    student_id: str
    year: int
    month: int
    item_name: str
    amount: float
    memo: Optional[str] = None
    sort_order: int
    created_at: datetime

    class Config:
        from_attributes = True
        json_encoders = {
            UUID: str
        }

# Billing Invoice 스키마
class BillingInvoiceItemCreate(BaseModel):
    item_name: str = Field(..., description="항목 이름")
    amount: float = Field(..., description="금액")
    memo: Optional[str] = Field(None, description="메모")
    sort_order: int = Field(0, description="정렬 순서")
    original_item_id: Optional[str] = Field(None, description="원본 항목 ID")

class BillingInvoiceItemResponse(BaseModel):
    id: str
    invoice_id: str
    item_name: str
    amount: float
    memo: Optional[str] = None
    sort_order: int
    original_item_id: Optional[str] = None
    created_at: datetime

    class Config:
        from_attributes = True
        json_encoders = {
            UUID: str
        }

class BillingInvoiceCreate(BaseModel):
    student_id: str = Field(..., description="학생 ID")
    year: int = Field(..., description="년도")
    month: int = Field(..., description="월")
    total_amount: float = Field(..., description="총 금액")
    memo: Optional[str] = Field(None, description="메모")
    items: List[BillingInvoiceItemCreate] = Field(..., description="청구서 항목들")

class BillingInvoiceResponse(BaseModel):
    id: str
    student_id: str
    year: int
    month: int
    invoice_date: date
    total_amount: float
    memo: Optional[str] = None
    created_at: datetime
    items: List[BillingInvoiceItemResponse] = []

    class Config:
        from_attributes = True
        json_encoders = {
            UUID: str
        }

class ElderlyMealRecordCreate(BaseModel):
    resident_id: str = Field(..., description="거주자 ID")
    skip_date: Union[date, str] = Field(..., description="식사 건너뛴 날짜 (YYYY-MM-DD)")
    meal_type: str = Field(..., description="식사 유형 (breakfast, lunch, dinner)")

    @field_validator('skip_date', mode='before')
    @classmethod
    def validate_date_field(cls, v):
        if v == "" or v is None:
            return None
        return v

    @field_validator('meal_type')
    @classmethod
    def validate_meal_type(cls, v):
        if v not in ['breakfast', 'lunch', 'dinner']:
            raise ValueError('meal_type must be one of: breakfast, lunch, dinner')
        return v

class ElderlyMealRecordUpdate(BaseModel):
    skip_date: Optional[date] = Field(None, description="식사 건너뛴 날짜 (YYYY-MM-DD)")
    meal_type: Optional[str] = Field(None, description="식사 유형 (breakfast, lunch, dinner)")

    @field_validator('skip_date', mode='before')
    @classmethod
    def validate_date_field(cls, v):
        if v == "" or v is None:
            return None
        return v

    @field_validator('meal_type')
    @classmethod
    def validate_meal_type(cls, v):
        if v is not None and v not in ['breakfast', 'lunch', 'dinner']:
            raise ValueError('meal_type must be one of: breakfast, lunch, dinner')
        return v

class ElderlyMealRecordResponse(BaseModel):
    id: str
    resident_id: str
    skip_date: date
    meal_type: str
    created_at: datetime
    resident: Optional[dict] = None

    class Config:
        from_attributes = True
        json_encoders = {
            UUID: str
        }

class ElderlyHospitalizationCreate(BaseModel):
    elderly_id: str
    hospitalization_type: str  # 'admission' 또는 'discharge'
    hospital_name: str
    date: date
    last_meal_date: Optional[date] = None
    last_meal_type: Optional[str] = None  # 'breakfast', 'lunch', 'dinner'
    meal_resume_date: Optional[date] = None
    meal_resume_type: Optional[str] = None  # 'breakfast', 'lunch', 'dinner'
    note: Optional[str] = None

class ElderlyHospitalizationUpdate(BaseModel):
    hospital_name: Optional[str] = None
    date: Optional[date] = None
    last_meal_date: Optional[date] = None
    last_meal_type: Optional[str] = None
    meal_resume_date: Optional[date] = None
    meal_resume_type: Optional[str] = None
    note: Optional[str] = None

class ElderlyHospitalizationResponse(BaseModel):
    id: str
    resident_id: str
    hospitalization_type: str
    hospital_name: str
    date: date
    last_meal_date: Optional[date] = None
    last_meal_type: Optional[str] = None
    meal_resume_date: Optional[date] = None
    meal_resume_type: Optional[str] = None
    note: Optional[str] = None
    created_at: datetime
    created_by: Optional[str] = None
    resident: Optional[dict] = None

class ElderlyHospitalizationStatusResponse(BaseModel):
    resident_id: str
    resident_name: str
    hospitalization_status: str  # '正常' 또는 '入院中'
    latest_hospitalization: Optional[dict] = None