# 1. Python 3.12 일반 이미지 사용 (slim 대신)
FROM python:3.12

# 2. 필수 시스템 패키지 설치 (WeasyPrint용)
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libcairo2 \
    libpango-1.0-0 \
    libgdk-pixbuf2.0-0 \
    libglib2.0-0 \
    libffi-dev \
    shared-mime-info \
    fonts-noto \
    && apt-get clean && rm -rf /var/lib/apt/lists/*

# 3. 작업 디렉토리
WORKDIR /app

# 4. Python 패키지 설치
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 5. 앱 소스 복사
COPY . .

# 6. WeasyPrint가 폰트를 찾도록 환경 변수 설정
ENV FONTCONFIG_PATH=/app/static/fonts

# 7. FastAPI 앱 실행
CMD ["gunicorn", "main:app", "-w", "4", "-k", "uvicorn.workers.UvicornWorker", "--bind", "0.0.0.0:8000"]