from sqlalchemy import Column, String, Integer, DateTime, ForeignKey, Boolean, Date, SmallInteger, UniqueConstraint, func, Text, Numeric
from sqlalchemy.orm import relationship
from sqlalchemy.ext.declarative import declarative_base
from datetime import datetime
import uuid
from sqlalchemy.dialects.postgresql import UUID

Base = declarative_base()

class User(Base):
    __tablename__ = "users"

    id = Column(String, primary_key=True, index=True)
    name = Column(String)
    email = Column(String, unique=True, index=True)
    password = Column(String)
    created_at = Column(DateTime, default=datetime.utcnow)

class Student(Base):
    __tablename__ = "students"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name = Column(String)
    email = Column(String)
    created_at = Column(DateTime, default=datetime.utcnow)
    company_id = Column(String, ForeignKey("companies.id"))
    consultant = Column(SmallInteger)
    phone = Column(String)
    avatar = Column(String, default="/src/assets/images/avatars/avatar-1.png")
    grade_id = Column(String, ForeignKey("grades.id"))
    cooperation_submitted_date = Column(Date)
    cooperation_submitted_place = Column(String)
    assignment_date = Column(Date)
    ward = Column(String)
    name_katakana = Column(String)
    gender = Column(String)
    birth_date = Column(Date)
    nationality = Column(String)
    has_spouse = Column(Boolean)
    japanese_level = Column(String)
    passport_number = Column(String)
    residence_card_number = Column(String)
    residence_card_start = Column(Date)
    residence_card_expiry = Column(Date)
    resignation_date = Column(Date)
    local_address = Column(String)
    address = Column(String)
    experience_over_2_years = Column(Boolean)
    status = Column(String, default='ACTIVE')
    arrival_type= Column(String)
    entry_date = Column(Date)
    interview_date = Column(Date)
    pre_guidance_date = Column(Date)
    orientation_date = Column(Date)
    certification_application_date = Column(Date)
    visa_application_date = Column(Date)
    passport_expiration_date = Column(Date)
    student_type = Column(String)
    current_room_id = Column(UUID(as_uuid=True), ForeignKey("rooms.id"))
    facebook_name = Column(String)
    visa_year = Column(String)

    # 관계 설정
    company = relationship("Company", back_populates="students")
    grade = relationship("Grade", back_populates="students")
    invoices = relationship("Invoice", back_populates="student", cascade="all, delete-orphan")
    current_room = relationship("Room", back_populates="current_residents")
    residences = relationship("Resident", back_populates="student")
    residence_card_histories = relationship("ResidenceCardHistory", foreign_keys="ResidenceCardHistory.student_id", cascade="all, delete-orphan")

class Company(Base):
    __tablename__ = "companies"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name = Column(String)
    created_at = Column(DateTime, default=datetime.utcnow)

    # Student와의 관계 설정
    students = relationship("Student", back_populates="company")

class Grade(Base):
    __tablename__ = "grades"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name = Column(String)
    created_at = Column(DateTime, default=datetime.utcnow)

    # Student와의 관계 설정
    students = relationship("Student", back_populates="grade")
  
class Invoice(Base):
    __tablename__ = "invoices"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    student_id = Column(String, ForeignKey("students.id", ondelete="CASCADE"), nullable=False)
    invoice_number = Column(String, nullable=False)
    year = Column(Integer, nullable=False)
    month = Column(Integer, nullable=False)
    total_amount = Column(Integer, default=0)
    status = Column(String)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    # 관계 설정
    student = relationship("Student", back_populates="invoices")
    items = relationship("InvoiceItem", back_populates="invoice", cascade="all, delete-orphan")

    __table_args__ = (
        UniqueConstraint('student_id', 'year', 'month', name='unique_invoice_per_month'),
    )

class InvoiceItem(Base):
    __tablename__ = "invoice_items"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    invoice_id = Column(UUID(as_uuid=True), ForeignKey("invoices.id", ondelete="CASCADE"), nullable=False)
    name = Column(String, nullable=False)
    unit_price = Column(Integer, nullable=False)  # 단가
    quantity = Column(Integer, nullable=False, default=1)  # 수량 추가
    amount = Column(Integer, nullable=False)  # 금액
    sort_order = Column(Integer, default=0)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    memo = Column(String)
    type = Column(String, nullable=False)

    # 관계 설정
    invoice = relationship("Invoice", back_populates="items")

class BillingItem(Base):
    __tablename__ = "billing_items"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name = Column(String, nullable=False)
    unit = Column(Integer, nullable=False)  # 단가
    billing_type = Column(String, nullable=False)
    qna = Column(Integer, nullable=False, default=1)  # 수량 추가
    value = Column(Integer, nullable=False)
    type = Column(String, nullable=False)
    group_type = Column(String, nullable=False)

class Building(Base):
    __tablename__ = "buildings"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name = Column(String, nullable=False)
    address = Column(String)
    total_rooms = Column(Integer)
    note = Column(String)

    # 관계 설정
    rooms = relationship("Room", back_populates="building", cascade="all, delete-orphan")

class Room(Base):
    __tablename__ = "rooms"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    building_id = Column(UUID(as_uuid=True), ForeignKey("buildings.id", ondelete="CASCADE"), nullable=False)
    room_number = Column(String, nullable=False)
    rent = Column(Integer)
    floor = Column(Integer)
    capacity = Column(Integer)
    is_available = Column(Boolean, default=True)
    note = Column(String)

    # 관계 설정
    building = relationship("Building", back_populates="rooms")
    current_residents = relationship("Student", back_populates="current_room")
    residents = relationship("Resident", back_populates="room")

class Resident(Base):
    __tablename__ = "residents"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    room_id = Column(UUID(as_uuid=True), ForeignKey("rooms.id", ondelete="CASCADE"), nullable=False)
    student_id = Column(UUID(as_uuid=True), ForeignKey("students.id", ondelete="CASCADE"), nullable=False)
    check_in_date = Column(Date, nullable=False)
    check_out_date = Column(Date)
    is_active = Column(Boolean, default=True)
    note = Column(String)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    # 관계 설정
    room = relationship("Room", back_populates="residents")
    student = relationship("Student", back_populates="residences")

    __table_args__ = (
        UniqueConstraint('room_id', 'student_id', 'is_active', name='unique_active_resident_per_room'),
    )

class RoomLog(Base):
    __tablename__ = "room_logs"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    room_id = Column(UUID(as_uuid=True), ForeignKey("rooms.id"), nullable=True)
    student_id = Column(UUID(as_uuid=True), ForeignKey("students.id"), nullable=True)
    action = Column(String, nullable=False)  # CHECK_IN, CHECK_OUT, MOVE, HISTORICAL_ENTRY
    action_date = Column(Date, nullable=False)
    note = Column(Text, nullable=True)

    # 관계 설정
    room = relationship("Room", foreign_keys=[room_id])
    student = relationship("Student", foreign_keys=[student_id])

class RoomCharge(Base):
    __tablename__ = "room_charges"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    student_id = Column(UUID(as_uuid=True), ForeignKey("students.id"), nullable=False)
    room_id = Column(UUID(as_uuid=True), ForeignKey("rooms.id"), nullable=False)
    charge_month = Column(Date, nullable=False)
    total_amount = Column(Numeric, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    note = Column(Text, nullable=True)

    # 관계 설정
    student = relationship("Student", foreign_keys=[student_id])
    room = relationship("Room", foreign_keys=[room_id])
    charge_items = relationship("ChargeItem", back_populates="room_charge", cascade="all, delete-orphan")

class ChargeItem(Base):
    __tablename__ = "charge_items"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    room_charge_id = Column(UUID(as_uuid=True), ForeignKey("room_charges.id"), nullable=False)
    charge_type = Column(Text, nullable=False)  # 'rent', 'electricity', 'water', 'gas', etc.
    period_start = Column(Date, nullable=True)
    period_end = Column(Date, nullable=True)
    amount = Column(Numeric, nullable=True)  # 항목별 전체 금액
    unit_price = Column(Numeric, nullable=True)  # 단가
    quantity = Column(Numeric, nullable=True)  # 사용량, 일수 등
    memo = Column(Text, nullable=True)

    # 관계 설정
    room_charge = relationship("RoomCharge", back_populates="charge_items")
    allocations = relationship("ChargeItemAllocation", back_populates="charge_item", cascade="all, delete-orphan")

class ChargeItemAllocation(Base):
    __tablename__ = "charge_item_allocations"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    charge_item_id = Column(UUID(as_uuid=True), ForeignKey("charge_items.id"), nullable=False)
    student_id = Column(UUID(as_uuid=True), ForeignKey("students.id"), nullable=False)
    amount = Column(Numeric, nullable=False)  # 학생별 부담금액
    days_used = Column(Integer, nullable=True)  # 해당 항목 기간 중 머문 일수
    memo = Column(Text, nullable=True)

    # 관계 설정
    charge_item = relationship("ChargeItem", back_populates="allocations")
    student = relationship("Student", foreign_keys=[student_id])

class RoomUtility(Base):
    __tablename__ = "room_utilities"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    room_id = Column(UUID(as_uuid=True), ForeignKey("rooms.id"), nullable=False)
    utility_type = Column(Text, nullable=False)  # 'electricity', 'water', 'gas' 등
    period_start = Column(Date, nullable=False)  # 검침 시작일
    period_end = Column(Date, nullable=False)    # 검침 종료일
    usage = Column(Numeric, nullable=True)       # 사용량
    unit_price = Column(Numeric, nullable=True)  # 단가
    total_amount = Column(Numeric, nullable=True)  # 총 요금
    charge_month = Column(Date, nullable=False)  # 어떤 월의 청구분인지
    memo = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    # 관계 설정
    room = relationship("Room", foreign_keys=[room_id])

class UtilityAllocation(Base):
    __tablename__ = "utility_allocations"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    utility_id = Column(UUID(as_uuid=True), ForeignKey("room_utilities.id"), nullable=False)
    student_id = Column(UUID(as_uuid=True), ForeignKey("students.id"), nullable=False)
    days_used = Column(Integer, nullable=False)  # 해당 공과금 기간 중 머문 일수
    amount = Column(Numeric, nullable=False)     # 학생별 부담금액
    usage_ratio = Column(Numeric, nullable=True) # 사용량 비율 (사용량 기반 계산 시)
    memo = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    # 관계 설정
    utility = relationship("RoomUtility", foreign_keys=[utility_id])
    student = relationship("Student", foreign_keys=[student_id])

class ResidenceCardHistory(Base):
    __tablename__ = "residence_card_histories"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    student_id = Column(UUID(as_uuid=True), ForeignKey("students.id"), nullable=False)
    card_number = Column(String, nullable=False)
    start_date = Column(Date, nullable=False)
    expiry_date = Column(Date, nullable=False)
    registered_at = Column(DateTime, default=datetime.utcnow)
    year = Column(String)
    note = Column(String)

    # 관계 설정
    student = relationship("Student", foreign_keys=[student_id])

class DatabaseLog(Base):
    __tablename__ = "database_logs"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    table_name = Column(String, nullable=False)  # 테이블 이름
    record_id = Column(String, nullable=False)   # 레코드 ID (UUID 문자열)
    action = Column(String, nullable=False)      # CREATE, UPDATE, DELETE
    user_id = Column(String, nullable=True)      # 작업한 사용자 ID
    old_values = Column(Text, nullable=True)     # 변경 전 값 (JSON)
    new_values = Column(Text, nullable=True)     # 변경 후 값 (JSON)
    changed_fields = Column(Text, nullable=True) # 변경된 필드들 (JSON)
    ip_address = Column(String, nullable=True)   # IP 주소
    user_agent = Column(Text, nullable=True)     # User Agent
    created_at = Column(DateTime, default=datetime.utcnow)
    note = Column(Text, nullable=True)           # 추가 메모

    # 인덱스 추가 (파티셔닝은 나중에 필요시 추가)
    __table_args__ = ()