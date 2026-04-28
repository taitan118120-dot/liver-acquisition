FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1 \
    X_APP_DB_PATH=/data/data.sqlite \
    PORT=8080

WORKDIR /app

RUN apt-get update \
 && apt-get install -y --no-install-recommends ca-certificates \
 && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install -r requirements.txt

COPY app.py db.py x_api.py qualify.py ./
COPY static ./static

RUN mkdir -p /data

EXPOSE 8080

# 単一プロセス・複数スレッド。リサーチはバックグラウンドスレッドで動くので
# worker は 1 のまま、_research_state グローバル状態を一貫させる。
CMD ["gunicorn", "-w", "1", "--threads", "8", "-b", "0.0.0.0:8080", "--timeout", "120", "app:app"]
