from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session, joinedload
from typing import Optional, List
from database import SessionLocal
from models import Invoice, InvoiceItem, Student, Company, Room, Building
from schemas import InvoiceCreate, InvoiceResponse, InvoiceUpdate
from datetime import datetime, date
import uuid

router = APIRouter(prefix="/invoices", tags=["인보이스 관리"])

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

@router.post("/", response_model=InvoiceResponse)
def create_invoice(invoice_data: InvoiceCreate, db: Session = Depends(get_db)):
    """새로운 인보이스 생성"""
    try:
        # 학생 존재 여부 확인
        student = db.query(Student).filter(Student.id == invoice_data.student_id).first()
        if not student:
            raise HTTPException(status_code=404, detail="학생을 찾을 수 없습니다")
        
        # 새 인보이스 생성
        new_invoice = Invoice(
            id=str(uuid.uuid4()),
            student_id=invoice_data.student_id,
            invoice_date=invoice_data.invoice_date,
            due_date=invoice_data.due_date,
            total_amount=invoice_data.total_amount,
            status=invoice_data.status or "pending",
            notes=invoice_data.notes
        )
        
        db.add(new_invoice)
        db.commit()
        db.refresh(new_invoice)
        
        return {
            "id": str(new_invoice.id),
            "student_id": str(new_invoice.student_id),
            "student_name": student.name,
            "invoice_date": new_invoice.invoice_date,
            "due_date": new_invoice.due_date,
            "total_amount": new_invoice.total_amount,
            "status": new_invoice.status,
            "notes": new_invoice.notes,
            "created_at": new_invoice.created_at
        }
        
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"인보이스 생성 중 오류가 발생했습니다: {str(e)}")

@router.get("/")
def get_invoices(
    student_id: Optional[str] = Query(None, description="학생 ID로 필터링"),
    status: Optional[str] = Query(None, description="상태로 필터링"),
    start_date: Optional[date] = Query(None, description="시작 날짜"),
    end_date: Optional[date] = Query(None, description="종료 날짜"),
    page: int = Query(1, description="페이지 번호", ge=1),
    page_size: int = Query(10, description="페이지당 항목 수", ge=1, le=100),
    db: Session = Depends(get_db)
):
    """인보이스 목록 조회"""
    try:
        query = db.query(Invoice).options(joinedload(Invoice.student))
        
        # 필터링 적용
        if student_id:
            query = query.filter(Invoice.student_id == student_id)
        if status:
            query = query.filter(Invoice.status == status)
        if start_date:
            query = query.filter(Invoice.invoice_date >= start_date)
        if end_date:
            query = query.filter(Invoice.invoice_date <= end_date)
        
        # 최신순으로 정렬
        query = query.order_by(Invoice.invoice_date.desc())
        
        # 전체 항목 수 계산
        total_count = query.count()
        
        # 페이지네이션 적용
        invoices = query.offset((page - 1) * page_size).limit(page_size).all()
        
        # 전체 페이지 수 계산
        total_pages = (total_count + page_size - 1) // page_size
        
        # 응답 데이터 준비
        result = []
        for invoice in invoices:
            invoice_data = {
                "id": str(invoice.id),
                "student_id": str(invoice.student_id),
                "student_name": invoice.student.name if invoice.student else None,
                "invoice_date": invoice.invoice_date,
                "due_date": invoice.due_date,
                "total_amount": invoice.total_amount,
                "status": invoice.status,
                "notes": invoice.notes,
                "created_at": invoice.created_at
            }
            result.append(invoice_data)
        
        return {
            "items": result,
            "total": total_count,
            "page": page,
            "page_size": page_size,
            "total_pages": total_pages,
            "has_next": page < total_pages,
            "has_previous": page > 1
        }
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"인보이스 목록 조회 중 오류가 발생했습니다: {str(e)}")

@router.get("/{invoice_id}")
def get_invoice(invoice_id: str, db: Session = Depends(get_db)):
    """특정 인보이스 상세 정보 조회"""
    try:
        invoice = db.query(Invoice).options(
            joinedload(Invoice.student),
            joinedload(Invoice.items)
        ).filter(Invoice.id == invoice_id).first()
        
        if not invoice:
            raise HTTPException(status_code=404, detail="인보이스를 찾을 수 없습니다")
        
        invoice_data = {
            "id": str(invoice.id),
            "student_id": str(invoice.student_id),
            "student_name": invoice.student.name if invoice.student else None,
            "invoice_date": invoice.invoice_date,
            "due_date": invoice.due_date,
            "total_amount": invoice.total_amount,
            "status": invoice.status,
            "notes": invoice.notes,
            "created_at": invoice.created_at,
            "items": [
                {
                    "id": str(item.id),
                    "description": item.description,
                    "quantity": item.quantity,
                    "unit_price": item.unit_price,
                    "total_price": item.total_price
                } for item in invoice.items
            ] if invoice.items else []
        }
        
        return invoice_data
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"인보이스 상세 정보 조회 중 오류가 발생했습니다: {str(e)}")

@router.get("/{invoice_id}/preview")
def get_invoice_preview(invoice_id: str, db: Session = Depends(get_db)):
    """인보이스 미리보기"""
    try:
        invoice = db.query(Invoice).options(
            joinedload(Invoice.student),
            joinedload(Invoice.items)
        ).filter(Invoice.id == invoice_id).first()
        
        if not invoice:
            raise HTTPException(status_code=404, detail="인보이스를 찾을 수 없습니다")
        
        return {
            "invoice_id": str(invoice.id),
            "student_name": invoice.student.name if invoice.student else None,
            "invoice_date": invoice.invoice_date,
            "due_date": invoice.due_date,
            "total_amount": invoice.total_amount,
            "status": invoice.status,
            "items_count": len(invoice.items) if invoice.items else 0
        }
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"인보이스 미리보기 조회 중 오류가 발생했습니다: {str(e)}")

@router.get("/{invoice_id}/pdf")
def get_invoice_pdf(invoice_id: str, db: Session = Depends(get_db)):
    """인보이스 PDF 다운로드"""
    try:
        invoice = db.query(Invoice).options(
            joinedload(Invoice.student),
            joinedload(Invoice.items)
        ).filter(Invoice.id == invoice_id).first()
        
        if not invoice:
            raise HTTPException(status_code=404, detail="인보이스를 찾을 수 없습니다")
        
        # PDF 생성 로직은 여기에 구현
        # 현재는 간단한 응답만 반환
        return {
            "message": "PDF 생성 기능은 별도 구현이 필요합니다",
            "invoice_id": str(invoice.id),
            "student_name": invoice.student.name if invoice.student else None
        }
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"인보이스 PDF 생성 중 오류가 발생했습니다: {str(e)}")

@router.put("/")
def update_invoice(invoice_update: InvoiceUpdate, db: Session = Depends(get_db)):
    """인보이스 수정"""
    try:
        invoice = db.query(Invoice).filter(Invoice.id == invoice_update.id).first()
        if not invoice:
            raise HTTPException(status_code=404, detail="인보이스를 찾을 수 없습니다")
        
        # 업데이트할 필드들
        update_data = invoice_update.dict(exclude_unset=True)
        for field, value in update_data.items():
            if field != "id":  # ID는 업데이트하지 않음
                setattr(invoice, field, value)
        
        db.commit()
        db.refresh(invoice)
        
        return {
            "message": "인보이스가 성공적으로 수정되었습니다",
            "invoice": {
                "id": str(invoice.id),
                "student_id": str(invoice.student_id),
                "invoice_date": invoice.invoice_date,
                "due_date": invoice.due_date,
                "total_amount": invoice.total_amount,
                "status": invoice.status,
                "notes": invoice.notes
            }
        }
        
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"인보이스 수정 중 오류가 발생했습니다: {str(e)}")

@router.get("/billing-options")
def get_billing_options(db: Session = Depends(get_db)):
    """청구 옵션 조회"""
    try:
        # 기본 청구 옵션들
        billing_options = {
            "payment_methods": ["bank_transfer", "credit_card", "cash"],
            "billing_cycles": ["monthly", "quarterly", "annually"],
            "currency": "JPY",
            "tax_rate": 0.10,
            "late_fee_rate": 0.05,
            "grace_period_days": 7
        }
        
        return billing_options
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"청구 옵션 조회 중 오류가 발생했습니다: {str(e)}")

@router.get("/company-invoice-pdf/{company_id}/{year}/{month}")
def get_company_invoice_pdf(
    company_id: str,
    year: int,
    month: int,
    db: Session = Depends(get_db)
):
    """회사별 월간 인보이스 PDF"""
    try:
        # 회사 존재 여부 확인
        company = db.query(Company).filter(Company.id == company_id).first()
        if not company:
            raise HTTPException(status_code=404, detail="회사를 찾을 수 없습니다")
        
        # 해당 회사 소속 학생들의 월간 인보이스 조회
        students = db.query(Student).filter(Student.company_id == company_id).all()
        
        # 월간 인보이스 데이터 구성
        monthly_data = {
            "company_id": company_id,
            "company_name": company.name,
            "billing_period": f"{year}년 {month}월",
            "total_students": len(students),
            "total_amount": 0,
            "students": []
        }
        
        for student in students:
            # 학생의 월간 인보이스 조회
            invoice = db.query(Invoice).filter(
                Invoice.student_id == student.id,
                db.func.extract('year', Invoice.invoice_date) == year,
                db.func.extract('month', Invoice.invoice_date) == month
            ).first()
            
            if invoice:
                monthly_data["total_amount"] += invoice.total_amount
                monthly_data["students"].append({
                    "student_id": str(student.id),
                    "student_name": student.name,
                    "amount": invoice.total_amount,
                    "status": invoice.status
                })
        
        return {
            "message": "회사 월간 인보이스 데이터가 준비되었습니다",
            "data": monthly_data
        }
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"회사 월간 인보이스 생성 중 오류가 발생했습니다: {str(e)}")

@router.get("/invoice/{student_id}/{year}/{month}")
def get_student_monthly_invoice(
    student_id: str,
    year: int,
    month: int,
    db: Session = Depends(get_db)
):
    """학생별 월간 인보이스 조회"""
    try:
        # 학생 존재 여부 확인
        student = db.query(Student).filter(Student.id == student_id).first()
        if not student:
            raise HTTPException(status_code=404, detail="학생을 찾을 수 없습니다")
        
        # 해당 월의 인보이스 조회
        invoice = db.query(Invoice).filter(
            Invoice.student_id == student_id,
            db.func.extract('year', Invoice.invoice_date) == year,
            db.func.extract('month', Invoice.invoice_date) == month
        ).first()
        
        if not invoice:
            return {
                "student_id": student_id,
                "student_name": student.name,
                "billing_period": f"{year}년 {month}월",
                "message": "해당 월에 인보이스가 없습니다"
            }
        
        return {
            "student_id": student_id,
            "student_name": student.name,
            "billing_period": f"{year}년 {month}월",
            "invoice": {
                "id": str(invoice.id),
                "invoice_date": invoice.invoice_date,
                "due_date": invoice.due_date,
                "total_amount": invoice.total_amount,
                "status": invoice.status,
                "notes": invoice.notes
            }
        }
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"학생 월간 인보이스 조회 중 오류가 발생했습니다: {str(e)}") 