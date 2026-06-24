FROM python:3.11-slim
WORKDIR /app

RUN apt-get update && apt-get install -y \
    chromium \
    chromium-driver \
    poppler-utils \
    tesseract-ocr \
    tesseract-ocr-ben \
    tesseract-ocr-eng \
    fonts-noto-color-emoji \
    fonts-noto \
    curl \
    gcc \
    python3-dev \
    && rm -rf /var/lib/apt/lists/*

ENV OWNER_ID=5341425626

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

RUN mkdir -p /app/data

CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "7860"]	
# rebuild Mon Jun  8 20:51:36 +06 2026
# force rebuild Mon Jun  8 21:38:33 +06 2026
# force rebuild 1780934332
