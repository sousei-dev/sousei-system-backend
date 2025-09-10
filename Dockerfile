# 1. Python 3.12.3 slim 이미지 사용
FROM python:3.12.3-slim

# 2. 일본어 폰트 설치 + 필수 패키지 설치
RUN apt-get update && apt-get install -y \
    fonts-ipafont-gothic \
    fonts-ipafont-mincho \
    build-essential \
    curl \
    && rm -rf /var/lib/apt/lists/*

# 3. 작업 디렉토리 설정
WORKDIR /app

# 4. requirements.txt 복사 후 패키지 설치
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 5. 프로젝트 전체 소스 복사
COPY . .

# 6. FastAPI 실행
# 'app.main:app' 경로는 실제 프로젝트 구조에 맞게 수정 필요
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "10000"] 