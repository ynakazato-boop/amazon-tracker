FROM python:3.11-slim

# 日本語フォント（Amazon検索に必要）
RUN apt-get update && apt-get install -y \
    fonts-noto-cjk \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Playwright + Chromium（依存ライブラリも含めてインストール）
RUN playwright install --with-deps chromium

COPY . .

RUN mkdir -p data config

COPY start.sh .
RUN chmod +x start.sh

EXPOSE 8501

CMD ["./start.sh"]
