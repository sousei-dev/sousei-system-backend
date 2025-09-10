# 1. Python 3.12.3 이미지 사용
FROM python:3.12.3-slim

# 2. 필수 OS 패키지 설치 (WeasyPrint용)
RUN apt-get update && apt-get upgrade -y && \
    apt-get install -y --no-install-recommends \
        build-essential \
        libcairo2 \
        libpango-1.0-0 \
        libgdk-pixbuf2.0-0 \
        libglib2.0-0 \
        libffi-dev \
        shared-mime-info \
        fonts-noto-cjk \
        --fix-missing && \
    apt-get clean && rm -rf /var/lib/apt/lists/*

# 3. 작업 디렉토리 설정 (소스 루트에 맞춤)
WORKDIR /sousei-system-backend

# 4. Python 패키지 설치
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 5. 앱 소스 전체 복사
COPY . .

# 6. WeasyPrint가 폰트를 찾도록 환경 변수 설정
ENV FONTCONFIG_PATH=/sousei-system-backend/static/fonts

# 7. FastAPI 앱 실행
# - 워커 수를 1로 줄여 메모리 부족 방지
# - 타임아웃 120초로 설정
CMD ["gunicorn", "main:app", "-w", "1", "-k", "uvicorn.workers.UvicornWorker", "--bind", "0.0.0.0:8000", "--timeout", "120"]