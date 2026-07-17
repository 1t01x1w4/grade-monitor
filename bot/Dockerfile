FROM python:3.11-slim

WORKDIR /app

# 系统依赖
RUN apt-get update && apt-get install -y --no-install-recommends \
    libxml2 libxslt1.1 \
    && rm -rf /var/lib/apt/lists/*

# 安装 Python 依赖
COPY pyproject.toml .
RUN pip install --no-cache-dir lxml -i https://mirrors.aliyun.com/pypi/simple/ && \
    pip install --no-cache-dir -i https://mirrors.aliyun.com/pypi/simple/ \
    nonebot2 \
    nonebot-adapter-onebot \
    httpx \
    beautifulsoup4 \
    aiosqlite \
    apscheduler \
    python-dotenv \
    cryptography \
    websockets \
    ddddocr

COPY . .
RUN mkdir -p /app/data

CMD ["python", "-u", "bot.py"]
