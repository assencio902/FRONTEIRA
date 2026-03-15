# Imagem base oficial com PyTorch 2.3.1 + CUDA 12.1 já incluídos
# Evita download de ~2.5 GB do torch+cu121 durante o build
FROM pytorch/pytorch:2.3.1-cuda12.1-cudnn8-runtime

ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONUNBUFFERED=1 \
    IMAGES_DIR=/app/uploads

RUN apt-get update && apt-get install -y --no-install-recommends \
    libgl1 libglib2.0-0 \
    tesseract-ocr tesseract-ocr-por \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir --timeout=300 -r requirements.txt

# Pre-download do modelo yolov8n.pt na build para não baixar em runtime
RUN python -c "from ultralytics import YOLO; YOLO('yolov8n.pt')"

COPY worker.py .

# Startup script garante keepalive no Redis e restart automático
COPY start_worker.py .
CMD ["python", "start_worker.py"]
