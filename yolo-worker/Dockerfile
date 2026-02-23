FROM python:3.11-slim

ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONUNBUFFERED=1 \
    IMAGES_DIR=/app/uploads

RUN apt-get update && apt-get install -y --no-install-recommends \
    libgl1 libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir --timeout=300 -r requirements.txt

# Pre-download do modelo yolov8n.pt na build para não baixar em runtime
RUN python -c "from ultralytics import YOLO; YOLO('yolov8n.pt')"

COPY worker.py .

CMD ["rq", "worker", "--url", "redis://redis:6379/0", "yolo"]
