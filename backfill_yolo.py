"""
backfill_yolo.py
Enfileira no Redis/RQ lpr_events para re-análise pelo yolo-worker.

Modos:
  python backfill_yolo.py          -> apenas eventos sem yolo_result
  python backfill_yolo.py --force  -> TODOS os eventos (reprocessa cores erradas)
"""
import os
import sys
import psycopg2
import redis as _redis
from rq import Queue

POSTGRES_HOST     = os.getenv("POSTGRES_HOST",     "localhost")
POSTGRES_PORT     = os.getenv("POSTGRES_PORT",     "5432")
POSTGRES_DB       = os.getenv("POSTGRES_DB",       "monitor")
POSTGRES_USER     = os.getenv("POSTGRES_USER",     "monitor_user")
POSTGRES_PASSWORD = os.getenv("POSTGRES_PASSWORD", "monitor_pass")
REDIS_URL         = os.getenv("REDIS_URL",         "redis://localhost:6379/0")
IMAGES_DIR        = os.getenv("IMAGES_DIR",        "/app/uploads")
BATCH             = 500   # quantos jobs enfileirar por vez

def main():
    force = "--force" in sys.argv

    conn = psycopg2.connect(
        host=POSTGRES_HOST, port=POSTGRES_PORT,
        dbname=POSTGRES_DB, user=POSTGRES_USER, password=POSTGRES_PASSWORD,
    )
    cur = conn.cursor()

    if force:
        cur.execute("""
            SELECT COUNT(*) FROM lpr_events
            WHERE image_path IS NOT NULL AND image_path <> ''
        """)
        modo = "TODOS os eventos (--force)"
    else:
        cur.execute("""
            SELECT COUNT(*) FROM lpr_events
            WHERE yolo_result IS NULL AND image_path IS NOT NULL AND image_path <> ''
        """)
        modo = "eventos sem yolo_result"

    total = cur.fetchone()[0]
    print(f"[BACKFILL] Modo: {modo}")
    print(f"[BACKFILL] Total a processar: {total}")

    if total == 0:
        print("[BACKFILL] Nada a fazer.")
        cur.close(); conn.close()
        return

    rq_conn = _redis.from_url(REDIS_URL)
    queue   = Queue("yolo", connection=rq_conn)

    if force:
        cur.execute("""
            SELECT id, image_path FROM lpr_events
            WHERE image_path IS NOT NULL AND image_path <> ''
            ORDER BY id ASC
        """)
    else:
        cur.execute("""
            SELECT id, image_path FROM lpr_events
            WHERE yolo_result IS NULL AND image_path IS NOT NULL AND image_path <> ''
            ORDER BY id ASC
        """)

    enqueued = 0
    batch = cur.fetchmany(BATCH)
    while batch:
        for row in batch:
            event_id, image_path = row
            # Monta caminho absoluto como o worker espera
            if not image_path.startswith("/"):
                abs_path = f"{IMAGES_DIR}/{image_path}"
            else:
                abs_path = image_path
            queue.enqueue(
                "worker.job_analyze_event",
                abs_path,
                job_timeout=120,
            )
            enqueued += 1

        pct = enqueued / total * 100
        print(f"[BACKFILL] {enqueued}/{total} ({pct:.1f}%) enfileirados | fila atual: {queue.count}", flush=True)
        batch = cur.fetchmany(BATCH)

    print(f"[BACKFILL] Concluido — {enqueued} jobs enfileirados.")
    cur.close()
    conn.close()

if __name__ == "__main__":
    main()
