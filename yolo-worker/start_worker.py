"""
start_worker.py — Inicia o rq worker com conexão Redis configurada com
socket_keepalive=True para evitar timeout em períodos longos de inatividade.
"""
import os
import redis
from rq import Worker, Queue

REDIS_URL = os.getenv("REDIS_URL", "redis://redis:6379/0")

conn = redis.from_url(
    REDIS_URL,
    socket_keepalive=True,
    socket_timeout=None,               # sem timeout de socket
    socket_connect_timeout=30,
    health_check_interval=30,          # ping a cada 30s para manter conexão viva
    retry_on_timeout=True,
)

queues = [Queue("yolo", connection=conn)]

worker = Worker(queues, connection=conn)

print(f"[WORKER] Iniciando em {REDIS_URL} | keepalive=True | health_check=30s", flush=True)
worker.work(with_scheduler=False)
