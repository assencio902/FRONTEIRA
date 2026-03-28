FROM python:3.11-slim
WORKDIR /app
COPY requirements.txt .
RUN apt-get update \
    && apt-get install -y --no-install-recommends docker.io \
    && rm -rf /var/lib/apt/lists/*
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
# Garante que /app/uploads existe como diretório na imagem.
# Se o bind mount do docker-compose for um diretório válido, ele sobrepõe este;
# se não houver bind mount, o serviço ainda funciona.
RUN if [ -e /app/uploads ] && [ ! -d /app/uploads ]; then \
        echo "ERRO: /app/uploads existe como arquivo na imagem - removendo" && \
        rm /app/uploads; \
    fi && mkdir -p /app/uploads
ENV PYTHONUNBUFFERED=1
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
