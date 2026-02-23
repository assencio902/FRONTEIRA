import asyncio
import os
import shutil
import uuid
import xml.etree.ElementTree as ET
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path
from typing import Optional

# -- Configuração de limpeza automática de disco ----------------------------
UPLOAD_DIR = Path("uploads")
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
# Manter pelo menos X MB livres no disco (padrão: 3 GB)
DISK_FREE_MIN_MB = int(os.getenv("DISK_FREE_MIN_MB", "3072"))
# Intervalo entre verificações em segundos (padrão: 5 min)
CLEANUP_INTERVAL_SEC = int(os.getenv("CLEANUP_INTERVAL_SEC", "300"))
# Extensões consideradas imagens (apagadas primeiro)
_IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".bmp", ".gif", ".webp"}

# -- Batedor: configurações anti-falso-positivo -----------------------------
MIN_LPR_CONFIDENCE = float(os.getenv("MIN_LPR_CONFIDENCE", "0.40"))
# Janela de deduplicação: passagens da mesma placa na mesma câmera em N segundos = 1 evento
DEDUP_SECONDS      = int(os.getenv("DEDUP_SECONDS", "60"))
# Delta-t mínimo/máximo entre câmeras para ser considerado comboio (segundos)
CONVOY_DT_MIN      = int(os.getenv("CONVOY_DT_MIN", "40"))
CONVOY_DT_MAX      = int(os.getenv("CONVOY_DT_MAX", "180"))

import psycopg2
import psycopg2.extras
import psycopg2.pool
from contextlib import contextmanager
from pydantic import BaseModel
from starlette.datastructures import UploadFile
from starlette.requests import ClientDisconnect

from fastapi import BackgroundTasks, FastAPI, File, HTTPException, Query, Request
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles

# -- Fila Redis/RQ (opcional  não trava ingest se Redis indisponível) ------
_rq_queue = None

def _get_queue():
    global _rq_queue
    if _rq_queue is not None:
        return _rq_queue
    try:
        import redis as _redis
        from rq import Queue as _Queue
        _url = os.getenv("REDIS_URL", "redis://redis:6379/0")
        _rq_queue = _Queue("yolo", connection=_redis.from_url(_url))
        print(f"[RQ] Fila 'yolo' conectada em {_url}", flush=True)
    except Exception as e:
        print(f"[RQ] Redis indisponivel, jobs YOLO desativados: {e}", flush=True)
        _rq_queue = False   # False = testado e falhou, não tenta novamente
    return _rq_queue


_db_pool: psycopg2.pool.ThreadedConnectionPool | None = None

def _get_pool() -> psycopg2.pool.ThreadedConnectionPool:
    global _db_pool
    if _db_pool is None or _db_pool.closed:
        _db_pool = psycopg2.pool.ThreadedConnectionPool(
            minconn=2,
            maxconn=10,
            host=os.getenv("POSTGRES_HOST", "postgres"),
            port=os.getenv("POSTGRES_PORT", "5432"),
            dbname=os.getenv("POSTGRES_DB", "monitor"),
            user=os.getenv("POSTGRES_USER", "monitor_user"),
            password=os.getenv("POSTGRES_PASSWORD", "monitor_pass"),
        )
    return _db_pool

@contextmanager
def _conn():
    pool = _get_pool()
    conn = pool.getconn()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        pool.putconn(conn)


def _init_db():
    with _conn() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                CREATE TABLE IF NOT EXISTS lpr_events (
                    id           SERIAL PRIMARY KEY,
                    plate        TEXT,
                    camera_id    TEXT,
                    channel_name TEXT,
                    camera_ip    TEXT,
                    confidence   FLOAT DEFAULT 0,
                    image_path   TEXT,
                    xml_path     TEXT,
                    occurred_at  TIMESTAMPTZ,
                    ts           TIMESTAMPTZ DEFAULT NOW()
                )
            """)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS vehicle_lists (
                    id            SERIAL PRIMARY KEY,
                    name          TEXT NOT NULL,
                    description   TEXT,
                    color         TEXT NOT NULL DEFAULT '#ef4444',
                    alarm_enabled BOOLEAN NOT NULL DEFAULT FALSE,
                    alarm_sound   TEXT NOT NULL DEFAULT 'beep',
                    created_at    TIMESTAMPTZ DEFAULT NOW()
                )
            """)
            # Migração para bases existentes
            cur.execute("ALTER TABLE vehicle_lists ADD COLUMN IF NOT EXISTS alarm_enabled BOOLEAN NOT NULL DEFAULT FALSE")
            cur.execute("ALTER TABLE vehicle_lists ADD COLUMN IF NOT EXISTS alarm_sound TEXT NOT NULL DEFAULT 'beep'")
            cur.execute("ALTER TABLE lpr_events ADD COLUMN IF NOT EXISTS yolo_result JSONB")
            cur.execute("""
                CREATE TABLE IF NOT EXISTS monitored_vehicles (
                    id         SERIAL PRIMARY KEY,
                    plate      TEXT NOT NULL,
                    list_id    INTEGER NOT NULL REFERENCES vehicle_lists(id) ON DELETE CASCADE,
                    notes      TEXT,
                    created_at TIMESTAMPTZ DEFAULT NOW(),
                    UNIQUE(plate, list_id)
                )
            """)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS alvo_plates (
                    id          SERIAL PRIMARY KEY,
                    plate       TEXT NOT NULL UNIQUE,
                    descricao   TEXT,
                    created_at  TIMESTAMPTZ DEFAULT NOW()
                )
            """)
            # Índices para acelerar consultas
            cur.execute("CREATE INDEX IF NOT EXISTS idx_lpr_ts      ON lpr_events (ts DESC)")
            cur.execute("CREATE INDEX IF NOT EXISTS idx_lpr_plate    ON lpr_events (plate)")
            cur.execute("CREATE INDEX IF NOT EXISTS idx_lpr_camera   ON lpr_events (camera_id)")
            cur.execute("CREATE INDEX IF NOT EXISTS idx_lpr_occurred ON lpr_events (occurred_at DESC)")
            # Índice funcional para queries YOLO
            cur.execute("CREATE INDEX IF NOT EXISTS idx_lpr_yolo_vc ON lpr_events ((yolo_result->>'vehicle_count')) WHERE yolo_result IS NOT NULL")
            # VIEW normalizada YOLO  contrato de dados por evento
            cur.execute("""
                CREATE OR REPLACE VIEW v_events_yolo AS
                SELECT
                    e.id,
                    e.plate,
                    e.camera_id,
                    e.ts,
                    e.occurred_at,
                    e.confidence,
                    e.image_path,
                    COALESCE((e.yolo_result->>'vehicle_count')::int, -1)   AS yolo_vehicle_count,
                    COALESCE((e.yolo_result->>'person_count')::int, -1)    AS yolo_person_count,
                    COALESCE(e.yolo_result->'vehicle_types', '{}'::jsonb)  AS yolo_vehicle_types,
                    COALESCE(e.yolo_result->'detections',   '[]'::jsonb)   AS yolo_detections,
                    (
                        SELECT key
                        FROM jsonb_each_text(e.yolo_result->'vehicle_types')
                        ORDER BY value::int DESC
                        LIMIT 1
                    ) AS yolo_dominant_type
                FROM lpr_events e
            """)
        conn.commit()


def _daily_upload_dir() -> Path:
    """Retorna (e cria se necessário) a subpasta do dia: uploads/YYYY-MM-DD/"""
    day = datetime.utcnow().strftime("%Y-%m-%d")
    d = UPLOAD_DIR / day
    d.mkdir(parents=True, exist_ok=True)
    return d


def _cleanup_uploads(min_free_mb: int = DISK_FREE_MIN_MB) -> int:
    """
    Remove os arquivos mais antigos de uploads/ (incluindo subpastas por data)
    até que o disco volte a ter pelo menos `min_free_mb` MB livres.
    Imagens são apagadas antes dos XMLs.
    Retorna o número de arquivos removidos.
    """
    removed = 0
    while True:
        usage = shutil.disk_usage(str(UPLOAD_DIR))
        free_mb = usage.free / (1024 * 1024)
        if free_mb >= min_free_mb:
            break

        # Varrer recursivamente todas as subpastas e a raiz
        files = sorted(
            [f for f in UPLOAD_DIR.rglob("*") if f.is_file()],
            key=lambda f: f.stat().st_mtime,
        )
        if not files:
            print("[CLEANUP] Nenhum arquivo para apagar, disco ainda cheio.")
            break

        # Prioriza imagens; se não houver, apaga qualquer arquivo
        images = [f for f in files if f.suffix.lower() in _IMAGE_EXTS]
        target = images[0] if images else files[0]

        try:
            size_mb = target.stat().st_size / (1024 * 1024)
            target.unlink()
            removed += 1
            print(
                f"[CLEANUP] Removido {target.name} ({size_mb:.1f} MB) "
                f" livres: {free_mb:.0f} MB -> {(free_mb + size_mb):.0f} MB"
            )
        except Exception as e:
            print(f"[CLEANUP] Erro ao remover {target}: {e}")
            break

    return removed


async def _disk_watchdog():
    """Verifica o espaço em disco periodicamente e dispara limpeza se necessário."""
    print(
        f"[CLEANUP] Watchdog iniciado  limite: {DISK_FREE_MIN_MB} MB livres, "
        f"intervalo: {CLEANUP_INTERVAL_SEC}s"
    )
    while True:
        await asyncio.sleep(CLEANUP_INTERVAL_SEC)
        try:
            usage = shutil.disk_usage(str(UPLOAD_DIR))
            free_mb = usage.free / (1024 * 1024)
            if free_mb < DISK_FREE_MIN_MB:
                print(f"[CLEANUP] Disco com {free_mb:.0f} MB livres  iniciando limpeza...")
                n = _cleanup_uploads()
                print(f"[CLEANUP] Limpeza concluida: {n} arquivo(s) removido(s).")
        except Exception as e:
            print(f"[CLEANUP][ERROR] {e}")


@asynccontextmanager
async def lifespan(app: FastAPI):
    _init_db()
    # Limpeza imediata na inicialização caso o disco já esteja cheio
    try:
        usage = shutil.disk_usage(str(UPLOAD_DIR))
        free_mb = usage.free / (1024 * 1024)
        if free_mb < DISK_FREE_MIN_MB:
            print(f"[CLEANUP] Startup: disco com {free_mb:.0f} MB livres  limpando...")
            n = _cleanup_uploads()
            print(f"[CLEANUP] Startup: {n} arquivo(s) removido(s).")
    except Exception as e:
        print(f"[CLEANUP][ERROR] startup cleanup: {e}")
    watchdog = asyncio.create_task(_disk_watchdog())
    yield
    watchdog.cancel()
    try:
        await watchdog
    except asyncio.CancelledError:
        pass


app = FastAPI(lifespan=lifespan)

# -- Pydantic models --------------------------------------------------------
class VehicleListCreate(BaseModel):
    name: str
    description: Optional[str] = None
    color: Optional[str] = '#ef4444'
    alarm_enabled: Optional[bool] = False
    alarm_sound: Optional[str] = 'beep'


class VehicleListUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    color: Optional[str] = None
    alarm_enabled: Optional[bool] = None
    alarm_sound: Optional[str] = None


class MonitoredVehicleCreate(BaseModel):
    plate: str
    list_id: int
    notes: Optional[str] = None


# Servir arquivos estáticos
os.makedirs("static", exist_ok=True)
app.mount("/static", StaticFiles(directory="static"), name="static")


@app.get("/dashboard", include_in_schema=False)
def dashboard():
    return FileResponse(
        "static/dashboard.html",
        headers={
            "Cache-Control": "no-store, no-cache, must-revalidate",
            "Pragma": "no-cache",
            "Expires": "0",
        }
    )


# -- Eventos LPR ------------------------------------------------------------

@app.get("/api/events")
def list_events(
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    plate: str | None = None,
    camera_id: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
):
    where = []
    params = {}

    if plate:
        where.append("plate ILIKE %(plate)s")
        params["plate"] = f"%{plate}%"

    if camera_id:
        where.append("camera_id = %(camera_id)s")
        params["camera_id"] = camera_id

    if date_from:
        where.append("ts >= %(date_from)s::timestamptz")
        params["date_from"] = date_from

    if date_to:
        where.append("ts <= %(date_to)s::timestamptz")
        params["date_to"] = date_to

    where_sql = ("WHERE " + " AND ".join(where)) if where else ""

    params["limit"] = limit
    params["offset"] = offset

    sql_total = f"SELECT COUNT(*) AS total FROM lpr_events {where_sql}"
    sql_items = f"""
        SELECT id, plate, camera_id, ts, occurred_at, confidence, image_path, xml_path, yolo_result
        FROM lpr_events
        {where_sql}
        ORDER BY id DESC
        LIMIT %(limit)s OFFSET %(offset)s
    """

    with _conn() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(sql_total, params)
            total = cur.fetchone()["total"]
            cur.execute(sql_items, params)
            items = cur.fetchall()

    return {"total": total, "limit": limit, "offset": offset, "items": items}


@app.get("/health")
async def health():
    return {"status": "ok"}


# -- Webhook principal Hikvision ANPR ---------------------------------------

@app.post("/api/simple-webhook")
async def simple_webhook(request: Request):
    ct = request.headers.get("content-type", "")

    if "multipart/form-data" not in ct:
        body = await request.body()
        return {"ok": True, "note": "not multipart", "content_type": ct, "bytes": len(body)}

    try:
        form = await request.form()
    except ClientDisconnect:
        print("[SIMPLE-WEBHOOK] ClientDisconnect (camera fechou conexao)")
        return {"ok": True, "note": "client disconnected before form was fully read"}

    xml_bytes: bytes | None = None
    images: list[tuple[str, bytes]] = []

    for k, v in form.multi_items():
        if isinstance(v, UploadFile):
            data = await v.read()
            fname = v.filename or ""
            cl = (v.content_type or "").lower()
            if "xml" in cl or fname.lower().endswith(".xml"):
                xml_bytes = data
            elif len(data) > 0:
                images.append((fname, data))
        else:
            val_str = str(v)
            if val_str.strip().startswith("<?xml") or "EventNotification" in val_str[:80]:
                xml_bytes = val_str.encode("utf-8")

    # Manter apenas a maior imagem (foto do veículo inteiro)
    # Imagens pequenas (< 10 KB) são thumbnails da placa  descartar
    vehicle_img: tuple[str, bytes] | None = None
    if images:
        big = [img for img in images if len(img[1]) >= 10_000]
        if big:
            vehicle_img = max(big, key=lambda x: len(x[1]))

    # Parsear XML Hikvision ANPR
    plate = "unknown"
    camera_id: str | None = None
    channel_name: str | None = None
    camera_ip: str | None = None
    confidence: float = 0.0
    occurred_at = None

    if xml_bytes:
        try:
            root = ET.fromstring(xml_bytes)
            ns = {"h": "http://www.isapi.org/ver20/XMLSchema"}

            def _x(tag: str) -> str | None:
                el = root.find(f"h:{tag}", ns)
                return el.text.strip() if el is not None and el.text else None

            lp = root.find(".//h:licensePlate", ns)
            if lp is not None and lp.text:
                plate = lp.text.strip() or "unknown"

            channel_name = _x("channelName") or _x("channelID")
            camera_id = channel_name
            camera_ip = _x("ipAddress")

            dt_str = _x("dateTime")
            if dt_str:
                try:
                    occurred_at = datetime.fromisoformat(dt_str)
                except Exception:
                    occurred_at = None

            conf_el = root.find(".//h:confidenceLevel", ns)
            if conf_el is not None and conf_el.text:
                try:
                    confidence = float(conf_el.text)
                except Exception:
                    confidence = 0.0
        except Exception as e:
            print(f"[SIMPLE-WEBHOOK] Erro ao parsear XML: {e}")

    # Salvar arquivos em subpasta do dia: uploads/YYYY-MM-DD/
    day_dir = _daily_upload_dir()
    day_str = day_dir.name  # ex: "2026-02-21"
    ts_prefix = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    image_path: str | None = None
    xml_path: str | None = None

    if vehicle_img:
        fname, data = vehicle_img
        suffix = Path(fname).suffix or ".jpg"
        img_name = f"{ts_prefix}_{uuid.uuid4().hex}{suffix}"
        try:
            (day_dir / img_name).write_bytes(data)
            image_path = f"uploads/{day_str}/{img_name}"
        except OSError as e:
            print(f"[SIMPLE-WEBHOOK] Erro ao salvar imagem: {e}  limpando disco...")
            _cleanup_uploads()
            try:
                (day_dir / img_name).write_bytes(data)
                image_path = f"uploads/{day_str}/{img_name}"
            except OSError as e2:
                print(f"[SIMPLE-WEBHOOK] Falha definitiva ao salvar imagem: {e2}")

    if xml_bytes:
        xml_name = f"{ts_prefix}_{uuid.uuid4().hex}.xml"
        try:
            (day_dir / xml_name).write_bytes(xml_bytes)
            xml_path = f"uploads/{day_str}/{xml_name}"
        except OSError as e:
            print(f"[SIMPLE-WEBHOOK] Erro ao salvar XML: {e}  limpando disco...")
            _cleanup_uploads()
            try:
                (day_dir / xml_name).write_bytes(xml_bytes)
                xml_path = f"uploads/{day_str}/{xml_name}"
            except OSError as e2:
                print(f"[SIMPLE-WEBHOOK] Falha definitiva ao salvar XML: {e2}")

    # Verificar espaço em disco após salvar
    try:
        usage = shutil.disk_usage(str(UPLOAD_DIR))
        free_mb = usage.free / (1024 * 1024)
        if free_mb < DISK_FREE_MIN_MB:
            _cleanup_uploads()
    except Exception as e:
        print(f"[CLEANUP][ERROR] pos-save: {e}")

    # Inserir evento no banco
    event_id = None
    try:
        with _conn() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    INSERT INTO lpr_events
                        (plate, camera_id, channel_name, camera_ip, confidence,
                         image_path, xml_path, occurred_at)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                    RETURNING id
                """, (plate, camera_id, channel_name, camera_ip, confidence,
                       image_path, xml_path, occurred_at))
                event_id = cur.fetchone()[0]
            conn.commit()
    except Exception as e:
        print(f"[SIMPLE-WEBHOOK][DB_ERROR] {e}")

    # Enfileirar job YOLO (não trava ingestão se Redis cair)
    if image_path and event_id:
        try:
            q = _get_queue()
            if q:
                # image_path = "uploads/YYYY-MM-DD/file.jpg"
                # No worker o volume é montado em /app/uploads, logo:
                rel = "/".join(image_path.split("/")[1:])   # "YYYY-MM-DD/file.jpg"
                abs_img = f"/app/uploads/{rel}"             # "/app/uploads/YYYY-MM-DD/file.jpg"
                job = q.enqueue("worker.job_analyze_event", abs_img)
                print(f"[RQ] Job enfileirado: {job.id} | evento #{event_id} | {abs_img}", flush=True)
        except Exception as e:
            print(f"[RQ][ERRO] Falha ao enfileirar job: {e}", flush=True)

    return {"ok": True}


# -- Listeners genéricos (debug / compatibilidade) --------------------------

def _inbox_dir() -> str:
    today = datetime.utcnow().strftime("%Y-%m-%d")
    base_dir = "/data/inbox"
    return os.path.join(base_dir, today)


def _save_bytes(base_dir: str, prefix: str, extension: str, data: bytes) -> str:
    os.makedirs(base_dir, exist_ok=True)
    unique_name = f"{prefix}-{uuid.uuid4().hex}{extension}"
    full_path = os.path.join(base_dir, unique_name)
    with open(full_path, "wb") as f:
        f.write(data)
    return full_path


def _background_persist(
    path: str,
    client_ip: str | None,
    content_type: str,
    content_length: str | None,
    is_multipart: bool,
    field_names: list[str],
    files: list[tuple[str, str | None, bytes]],
    raw_payload: bytes | None,
    raw_extension: str | None,
) -> None:
    try:
        base_dir = _inbox_dir()

        print(
            f"[INGEST] path={path} ip={client_ip} ct={content_type} "
            f"len={content_length} fields={field_names}"
        )

        if is_multipart and files:
            for field_name, filename, data in files:
                original = filename or "file.bin"
                _, dot, ext = original.rpartition(".")
                ext = f".{ext}" if dot else ""
                if not ext:
                    ext = ".bin"
                _save_bytes(base_dir, f"file-{field_name}", ext, data)

        if raw_payload is not None and raw_extension is not None:
            _save_bytes(base_dir, "payload", raw_extension, raw_payload)

    except Exception as e:
        print(f"[INGEST][ERROR_PERSIST] {e}")


async def _handle_event(request: Request, path: str, background_tasks: BackgroundTasks):
    client_ip = request.client.host if request.client else None
    content_type = request.headers.get("content-type") or ""
    content_length = request.headers.get("content-length")
    ct_lower = content_type.lower()

    is_multipart = "multipart/form-data" in ct_lower
    field_names: list[str] = []
    files: list[tuple[str, str | None, bytes]] = []
    raw_payload: bytes | None = None
    raw_extension: str | None = None

    try:
        if is_multipart:
            try:
                form = await request.form()
            except ClientDisconnect:
                print(f"[INGEST] ClientDisconnect path={path}")
                return JSONResponse({"ok": True})

            for name, value in form.multi_items():
                field_names.append(name)
                if isinstance(value, UploadFile):
                    data = await value.read()
                    files.append((name, value.filename, data))

        else:
            raw_payload = await request.body()

            if "application/json" in ct_lower:
                raw_extension = ".json"
            elif "application/xml" in ct_lower or "text/xml" in ct_lower:
                raw_extension = ".xml"
            elif "application/x-www-form-urlencoded" in ct_lower:
                raw_extension = ".form"
            elif "text/" in ct_lower:
                raw_extension = ".txt"
            else:
                raw_extension = ".bin"

    except Exception as e:
        print(f"[INGEST][ERROR_PARSE] path={path} error={e}")

    background_tasks.add_task(
        _background_persist,
        path,
        client_ip,
        content_type,
        content_length,
        is_multipart,
        field_names,
        files,
        raw_payload,
        raw_extension,
    )

    return JSONResponse({"ok": True})


@app.post("/api/lpr/receive")
async def lpr_receive(request: Request, background_tasks: BackgroundTasks):
    return await _handle_event(request, "/api/lpr/receive", background_tasks)


@app.post("/api/http-listener/receive")
async def http_listener_receive(request: Request, background_tasks: BackgroundTasks):
    return await _handle_event(request, "/api/http-listener/receive", background_tasks)


@app.post("/api/http-listener/receber")
async def http_listener_receber(request: Request, background_tasks: BackgroundTasks):
    return await _handle_event(request, "/api/http-listener/receber", background_tasks)


# -- Veículos monitorados ---------------------------------------------------

@app.get("/api/vehicles/lists")
def get_vehicle_lists():
    with _conn() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute("""
                SELECT vl.*, COUNT(mv.id) AS vehicle_count
                FROM vehicle_lists vl
                LEFT JOIN monitored_vehicles mv ON mv.list_id = vl.id
                GROUP BY vl.id
                ORDER BY vl.created_at DESC
            """)
            return {"items": cur.fetchall()}


@app.post("/api/vehicles/lists", status_code=201)
def create_vehicle_list(body: VehicleListCreate):
    with _conn() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                "INSERT INTO vehicle_lists (name, description, color, alarm_enabled, alarm_sound) VALUES (%s, %s, %s, %s, %s) RETURNING *",
                (body.name.strip(), body.description, body.color or '#ef4444',
                 body.alarm_enabled or False, body.alarm_sound or 'beep')
            )
            row = cur.fetchone()
        conn.commit()
    return row


@app.put("/api/vehicles/lists/{list_id}")
def update_vehicle_list(list_id: int, body: VehicleListUpdate):
    fields, vals = [], []
    if body.name is not None:
        fields.append("name = %s"); vals.append(body.name.strip())
    if body.description is not None:
        fields.append("description = %s"); vals.append(body.description)
    if body.color is not None:
        fields.append("color = %s"); vals.append(body.color)
    if body.alarm_enabled is not None:
        fields.append("alarm_enabled = %s"); vals.append(body.alarm_enabled)
    if body.alarm_sound is not None:
        fields.append("alarm_sound = %s"); vals.append(body.alarm_sound)
    if not fields:
        raise HTTPException(status_code=400, detail="Nenhum campo para atualizar")
    vals.append(list_id)
    with _conn() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                f"UPDATE vehicle_lists SET {', '.join(fields)} WHERE id = %s RETURNING *",
                vals
            )
            row = cur.fetchone()
        conn.commit()
    if not row:
        raise HTTPException(status_code=404, detail="Lista nao encontrada")
    return row


@app.delete("/api/vehicles/lists/{list_id}", status_code=204)
def delete_vehicle_list(list_id: int):
    with _conn() as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM vehicle_lists WHERE id = %s", (list_id,))
        conn.commit()


@app.get("/api/vehicles")
def get_vehicles(list_id: Optional[int] = None, plate: Optional[str] = None):
    where, params = [], {}
    if list_id:
        where.append("mv.list_id = %(list_id)s"); params["list_id"] = list_id
    if plate:
        where.append("mv.plate ILIKE %(plate)s"); params["plate"] = f"%{plate}%"
    where_sql = ("WHERE " + " AND ".join(where)) if where else ""
    with _conn() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(f"""
                SELECT mv.*, vl.name AS list_name, vl.color AS list_color
                FROM monitored_vehicles mv
                JOIN vehicle_lists vl ON vl.id = mv.list_id
                {where_sql}
                ORDER BY mv.created_at DESC
            """, params)
            return {"items": cur.fetchall()}


@app.post("/api/vehicles", status_code=201)
def add_vehicle(body: MonitoredVehicleCreate):
    plate = body.plate.strip().upper()
    if not plate:
        raise HTTPException(status_code=400, detail="Placa invalida")
    try:
        with _conn() as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute(
                    "INSERT INTO monitored_vehicles (plate, list_id, notes) VALUES (%s, %s, %s) RETURNING *",
                    (plate, body.list_id, body.notes)
                )
                row = cur.fetchone()
            conn.commit()
        return row
    except psycopg2.errors.UniqueViolation:
        raise HTTPException(status_code=409, detail="Placa ja cadastrada nesta lista")
    except psycopg2.errors.ForeignKeyViolation:
        raise HTTPException(status_code=404, detail="Lista nao encontrada")


@app.delete("/api/vehicles/{vehicle_id}", status_code=204)
def delete_vehicle(vehicle_id: int):
    with _conn() as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM monitored_vehicles WHERE id = %s", (vehicle_id,))
        conn.commit()


@app.get("/api/vehicles/check/{plate}")
def check_plate(plate: str):
    """Retorna todas as listas em que a placa esta cadastrada."""
    with _conn() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute("""
                SELECT mv.id, vl.name AS list_name, vl.color, mv.notes
                FROM monitored_vehicles mv
                JOIN vehicle_lists vl ON vl.id = mv.list_id
                WHERE mv.plate = %s
            """, (plate.strip().upper(),))
            rows = cur.fetchall()
    return {"plate": plate.upper(), "matches": rows, "found": len(rows) > 0}


@app.get("/api/vehicles/allplates")
def all_monitored_plates():
    """Retorna todas as placas monitoradas com suas listas (para highlight e alarme no dashboard)."""
    with _conn() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute("""
                SELECT mv.plate, vl.name AS list_name, vl.color,
                       vl.alarm_enabled, vl.alarm_sound
                FROM monitored_vehicles mv
                JOIN vehicle_lists vl ON vl.id = mv.list_id
                ORDER BY mv.plate
            """)
            rows = cur.fetchall()
    result = {}
    for r in rows:
        p = r["plate"]
        if p not in result:
            result[p] = []
        result[p].append({
            "list_name":     r["list_name"],
            "color":         r["color"],
            "alarm_enabled": r["alarm_enabled"],
            "alarm_sound":   r["alarm_sound"],
        })
    return {"plates": result}


# -- Alvos rastreados (suspeitos cadastrados) --------------------------------

@app.get("/api/alvos")
def list_alvos():
    """Retorna apenas alvos cadastrados manualmente na aba Alvos Rastreados."""
    with _conn() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute("SELECT * FROM alvo_plates ORDER BY created_at DESC")
            rows = cur.fetchall()
    return {"alvos": list(rows)}


class AlvoIn(BaseModel):
    plate:     str
    descricao: str = ""


@app.post("/api/alvos", status_code=201)
def add_alvo(body: AlvoIn):
    plate = body.plate.strip().upper()
    if not plate:
        raise HTTPException(status_code=400, detail="Placa invalida")
    with _conn() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                "INSERT INTO alvo_plates (plate, descricao) VALUES (%s, %s) "
                "ON CONFLICT (plate) DO UPDATE SET descricao=EXCLUDED.descricao RETURNING *",
                (plate, body.descricao.strip())
            )
            row = cur.fetchone()
        conn.commit()
    return dict(row)


@app.delete("/api/alvos/{alvo_id}", status_code=204)
def delete_alvo(alvo_id: int):
    with _conn() as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM alvo_plates WHERE id = %s", (alvo_id,))
        conn.commit()


@app.get("/api/alvos/recentes")
def alvos_recentes(window: str = Query("30m", regex=r"^\d+[hm]$")):
    """Retorna alvos com 2+ cameras vistas na janela.
    Retorna por placa: lista de cameras com ultimo horario e total de passes."""
    try:
        interval = _parse_window(window)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    sql = """
        WITH cam_hits AS (
            SELECT
                ap.plate,
                ap.descricao,
                e.camera_id,
                MAX(e.ts)  AS last_seen,
                COUNT(*)   AS passes,
                MAX(COALESCE((e.yolo_result->>'vehicle_count')::int, -1))                             AS max_yolo_vc,
                SUM(CASE WHEN COALESCE((e.yolo_result->>'vehicle_count')::int, 0) >= 2
                         THEN 1 ELSE 0 END)                                                          AS yolo_multi_passes,
                (
                    SELECT key
                    FROM jsonb_each_text(
                        COALESCE((
                            SELECT jsonb_object_agg(kv.k, agg_v)
                            FROM (
                                SELECT kk AS k, SUM(vv::int) AS agg_v
                                FROM lpr_events e2,
                                     jsonb_each_text(COALESCE(e2.yolo_result->'vehicle_types','{}')) AS t(kk,vv)
                                WHERE e2.plate = ap.plate
                                  AND e2.camera_id = e.camera_id
                                  AND e2.ts >= NOW() - INTERVAL %(window)s
                                GROUP BY kk
                            ) sub
                        ), '{}'::jsonb)
                    )
                    ORDER BY value::int DESC LIMIT 1
                ) AS dominant_type
            FROM alvo_plates ap
            JOIN lpr_events e ON e.plate = ap.plate
            WHERE e.ts >= NOW() - INTERVAL %(window)s
              AND e.confidence >= %(min_conf)s
            GROUP BY ap.plate, ap.descricao, e.camera_id
        ),
        per_plate AS (
            SELECT
                plate,
                descricao,
                COUNT(DISTINCT camera_id)                     AS total_cameras,
                SUM(yolo_multi_passes)                        AS yolo_multi_events,
                MODE() WITHIN GROUP (ORDER BY dominant_type)  AS dominant_type,
                jsonb_agg(
                    jsonb_build_object(
                        'camera_id',         camera_id,
                        'last_seen',         last_seen,
                        'passes',            passes,
                        'max_yolo_vc',       max_yolo_vc,
                        'yolo_multi_passes', yolo_multi_passes,
                        'dominant_type',     dominant_type
                    ) ORDER BY last_seen DESC
                ) AS cameras
            FROM cam_hits
            GROUP BY plate, descricao
            HAVING COUNT(DISTINCT camera_id) >= 2
        )
        SELECT * FROM per_plate ORDER BY total_cameras DESC
    """
    with _conn() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(sql, {"window": interval, "min_conf": MIN_LPR_CONFIDENCE})
            rows = cur.fetchall()
    return {"sightings": [dict(r) for r in rows]}


@app.get("/api/batedor/companions/{plate}")
def batedor_companions(
    plate:     str,
    window:    str = Query("24h", regex=r"^\d+[hm]$"),
    co_window: int = Query(600, ge=10, le=1800),
    limit:     int = Query(20, ge=1, le=100),
):
    """Para uma placa-alvo, retorna todas as placas vistas com ela (co-avistamento)
    e quem lidera (chega antes) em cada camera — identificando o possivel batedor."""
    try:
        interval = _parse_window(window)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    target = plate.strip().upper()
    sql = """
        WITH deduped AS (
            SELECT DISTINCT ON (plate, camera_id, (EXTRACT(EPOCH FROM ts)::int / %(dedup_sec)s))
                id, plate, camera_id, ts,
                COALESCE((yolo_result->>'vehicle_count')::int, -1) AS yolo_vc
            FROM lpr_events
            WHERE ts >= NOW() - INTERVAL %(window)s
              AND plate IS NOT NULL AND plate <> ''
              AND plate NOT ILIKE 'unknown%%'
              AND confidence >= %(min_conf)s
            ORDER BY plate, camera_id,
                     (EXTRACT(EPOCH FROM ts)::int / %(dedup_sec)s), ts
        ),
        target_events AS (
            SELECT * FROM deduped WHERE plate = %(target)s
        ),
        cosightings AS (
            SELECT
                b.plate                                              AS companion,
                a.camera_id                                          AS camera,
                a.ts                                                 AS ts_target,
                b.ts                                                 AS ts_companion,
                ABS(EXTRACT(EPOCH FROM (a.ts - b.ts)))::int          AS co_delta_sec,
                a.id                                                 AS event_target_id,
                b.id                                                 AS event_companion_id,
                a.yolo_vc                                            AS yolo_vc_target,
                b.yolo_vc                                            AS yolo_vc_companion
            FROM target_events a
            JOIN deduped b
              ON  b.camera_id = a.camera_id
             AND  b.plate <> %(target)s
             AND  ABS(EXTRACT(EPOCH FROM (a.ts - b.ts))) <= %(co_window)s
        )
        SELECT
            companion,
            COUNT(DISTINCT camera)                                                       AS cameras_together,
            COUNT(*)                                                                     AS total_cosightings,
            MIN(LEAST(ts_target, ts_companion))                                          AS first_seen,
            MAX(GREATEST(ts_target, ts_companion))                                       AS last_seen,
            AVG(co_delta_sec)::int                                                       AS avg_co_delta_sec,
            COUNT(*) FILTER (WHERE ts_companion < ts_target)                             AS companion_leads,
            COUNT(*) FILTER (WHERE ts_target <= ts_companion)                            AS target_leads,
            SUM(CASE WHEN GREATEST(yolo_vc_target, yolo_vc_companion) >= 2
                     THEN 1 ELSE 0 END)                                                  AS yolo_multi_events,
            jsonb_agg(jsonb_build_object(
                'camera',             camera,
                'ts_target',          ts_target,
                'ts_companion',       ts_companion,
                'co_delta_sec',       co_delta_sec,
                'event_target_id',    event_target_id,
                'event_companion_id', event_companion_id,
                'yolo_vc_target',     yolo_vc_target,
                'yolo_vc_companion',  yolo_vc_companion
            ) ORDER BY ts_target)                                                        AS evidence
        FROM cosightings
        GROUP BY companion
        ORDER BY cameras_together DESC, total_cosightings DESC
        LIMIT %(limit)s
    """
    params = {
        "window":    interval,
        "min_conf":  MIN_LPR_CONFIDENCE,
        "dedup_sec": DEDUP_SECONDS,
        "co_window": co_window,
        "target":    target,
        "limit":     limit,
    }
    try:
        with _conn() as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute(sql, params)
                companions = list(cur.fetchall())
        return {
            "plate":      target,
            "companions": companions,
            "count":      len(companions),
            "window":     window,
            "co_window":  co_window,
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# -- Batedor de suspeitos ---------------------------------------------------

@app.get("/api/batedor/suspects")
def batedor_suspects(
    window_minutes: int           = Query(180,  ge=1, le=129600),
    min_passes:     int           = Query(6,    ge=1),
    min_cameras:    int           = Query(2,    ge=1),
    limit:          int           = Query(50,   ge=1, le=500),
    ts_from:        Optional[str] = Query(None),
    ts_to:          Optional[str] = Query(None),
):
    if ts_from and ts_to:
        ts_filter = "ts BETWEEN %(ts_from)s AND %(ts_to)s"
    else:
        ts_filter = "ts >= NOW() - INTERVAL %(window)s"
    sql = f"""
        SELECT
            plate,
            COUNT(*)                            AS passes,
            COUNT(DISTINCT camera_id)           AS cameras,
            string_agg(DISTINCT camera_id, ',') AS camera_list,
            MIN(ts)                             AS first_seen,
            MAX(ts)                             AS last_seen,
            (COUNT(*) * 2 + COUNT(DISTINCT camera_id) * 5) AS score
        FROM lpr_events
        WHERE {ts_filter}
          AND plate IS NOT NULL
          AND plate NOT ILIKE 'unknown%%'
          AND plate <> ''
        GROUP BY plate
        HAVING COUNT(*) >= %(min_passes)s
           AND COUNT(DISTINCT camera_id) >= %(min_cameras)s
        ORDER BY score DESC
        LIMIT %(limit)s
    """
    params = {
        "window":      f"{window_minutes} minutes",
        "ts_from":     ts_from,
        "ts_to":       ts_to,
        "min_passes":  min_passes,
        "min_cameras": min_cameras,
        "limit":       limit,
    }
    try:
        with _conn() as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute(sql, params)
                items = cur.fetchall()
        return {"items": items, "count": len(items), "window_minutes": window_minutes}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/batedor/plate/{plate}")
def batedor_plate(
    plate: str,
    window_minutes: int = Query(180, ge=1, le=10080),
    limit:          int = Query(200, ge=1, le=1000),
):
    sql = """
        SELECT id, plate, ts, occurred_at, camera_id, confidence, image_path
        FROM lpr_events
        WHERE plate ILIKE %(plate)s
          AND ts >= NOW() - INTERVAL %(window)s
        ORDER BY ts DESC
        LIMIT %(limit)s
    """
    params = {"plate": plate, "window": f"{window_minutes} minutes", "limit": limit}
    try:
        with _conn() as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute(sql, params)
                items = cur.fetchall()
        return {"plate": plate, "items": items, "count": len(items)}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# -- Batedor v2: Escolta + Comboio com reforço YOLO -----------------------

def _parse_window(w: str) -> str:
    """Converte '2h' -> '2 hours', '30m' -> '30 minutes', '7d' -> '7 days'."""
    w = w.strip()
    if w.endswith("d"):
        return f"{int(w[:-1])} days"
    if w.endswith("h"):
        return f"{int(w[:-1])} hours"
    if w.endswith("m"):
        return f"{int(w[:-1])} minutes"
    raise ValueError(f"Formato de janela invalido: {w}")


@app.get("/api/batedor/escorts")
def batedor_escorts(
    window:       str = Query("2h",  regex=r"^\d+[hm]$"),
    limit:        int = Query(10,    ge=1, le=200),
    type:         str = Query("all"),
    min_passes:   int = Query(3,     ge=1),
    min_cameras:  int = Query(2,     ge=1),
):
    """
    Placas da hotlist detectadas com recorrência suspeita.
    Score reforçado se YOLO indicar vehicle_count >= 2 no frame.
    Filtro por vehicle_type disponível (car/motorcycle/truck/bus/all).
    """
    try:
        interval = _parse_window(window)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    sql = """
        WITH hotlist_events AS (
            SELECT DISTINCT ON (e.plate, e.camera_id, (EXTRACT(EPOCH FROM e.ts)::int / %(dedup_sec)s))
                e.id,
                e.plate,
                e.camera_id,
                e.ts,
                e.confidence,
                e.image_path,
                COALESCE((e.yolo_result->>'vehicle_count')::int, -1)  AS yolo_vc,
                COALESCE(e.yolo_result->'vehicle_types', '{}')        AS yolo_vt,
                (
                    SELECT key FROM jsonb_each_text(e.yolo_result->'vehicle_types')
                    ORDER BY value::int DESC LIMIT 1
                ) AS dominant_type
            FROM lpr_events e
            WHERE e.ts >= NOW() - INTERVAL %(window)s
              AND e.plate IS NOT NULL
              AND e.plate <> ''
              AND e.plate NOT ILIKE 'unknown%%'
              AND e.confidence >= %(min_conf)s
              AND EXISTS (
                  SELECT 1 FROM monitored_vehicles mv WHERE mv.plate = e.plate
              )
            ORDER BY e.plate, e.camera_id,
                     (EXTRACT(EPOCH FROM e.ts)::int / %(dedup_sec)s), e.ts
        ),
        grouped AS (
            SELECT
                he.plate,
                (
                    SELECT jsonb_agg(jsonb_build_object(
                        'list_id',   vl.id,
                        'list_name', vl.name,
                        'color',     vl.color
                    ))
                    FROM monitored_vehicles mv
                    JOIN vehicle_lists vl ON vl.id = mv.list_id
                    WHERE mv.plate = he.plate
                ) AS lists,
                COUNT(*)                                                    AS passes,
                COUNT(DISTINCT camera_id)                                   AS cameras,
                string_agg(DISTINCT camera_id, ',')                         AS camera_list,
                MIN(ts)                                                     AS first_seen,
                MAX(ts)                                                     AS last_seen,
                ROUND(AVG(confidence)::numeric, 2)                         AS avg_lpr_conf,
                SUM(CASE WHEN yolo_vc >= 2 THEN 1 ELSE 0 END)              AS yolo_multi_events,
                SUM(CASE WHEN yolo_vc >= 0 THEN 1 ELSE 0 END)              AS yolo_processed_events,
                MODE() WITHIN GROUP (ORDER BY dominant_type)               AS dominant_type,
                jsonb_agg(jsonb_build_object(
                    'id',        id,
                    'camera_id', camera_id,
                    'ts',        ts,
                    'lpr_conf',  confidence,
                    'yolo_vc',   yolo_vc,
                    'yolo_vt',   yolo_vt
                ) ORDER BY ts)                                             AS evidence,
                (COUNT(*) * 2
                 + COUNT(DISTINCT camera_id) * 5
                 + SUM(CASE WHEN yolo_vc >= 2 THEN 1 ELSE 0 END) * 3
                ) AS score
            FROM hotlist_events he
            GROUP BY he.plate
            HAVING COUNT(*) >= %(min_passes)s
               AND COUNT(DISTINCT camera_id) >= %(min_cameras)s
        )
        SELECT * FROM grouped
        ORDER BY score DESC
        LIMIT %(limit)s
    """
    params = {
        "window":      interval,
        "min_conf":    MIN_LPR_CONFIDENCE,
        "dedup_sec":   DEDUP_SECONDS,
        "min_passes":  min_passes,
        "min_cameras": min_cameras,
        "limit":       limit,
    }
    try:
        with _conn() as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute(sql, params)
                items = list(cur.fetchall())

        # Filtro por tipo de veículo (pós-SQL, baseado em dominant_type YOLO)
        type_filter = type.strip().lower()
        if type_filter != "all" and type_filter in {"car", "motorcycle", "truck", "bus"}:
            items = [
                r for r in items
                if (r.get("dominant_type") or "").lower() == type_filter
            ]

        return {
            "items": items,
            "count": len(items),
            "window": window,
            "filters": {
                "type":        type_filter,
                "min_passes":  min_passes,
                "min_cameras": min_cameras,
                "min_lpr_conf": MIN_LPR_CONFIDENCE,
            },
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/batedor/convoys")
def batedor_convoys(
    window:           str           = Query("2h",  regex=r"^\d+[hmd]$"),
    limit:            int           = Query(10,    ge=1, le=200),
    type:             str           = Query("all"),
    min_transitions:  int           = Query(2,     ge=1),
    dt_min:           int           = Query(CONVOY_DT_MIN, ge=1),
    dt_max:           int           = Query(CONVOY_DT_MAX, ge=2),
    ts_from:          Optional[str] = Query(None),
    ts_to:            Optional[str] = Query(None),
):
    """
    Detecta comboio/escolta sem alvo: mesma placa vista em 2+ câmeras com
    delta_t dentro da janela de trânsito esperada (default 40-180 s).
    Score reforçado quando YOLO indica múltiplos veículos no frame.
    """
    try:
        interval = _parse_window(window)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    sql = """
        WITH raw AS (
            SELECT DISTINCT ON (plate, camera_id, (EXTRACT(EPOCH FROM ts)::int / %(dedup_sec)s))
                id,
                plate,
                camera_id,
                ts,
                confidence,
                image_path,
                COALESCE((yolo_result->>'vehicle_count')::int, -1) AS yolo_vc,
                COALESCE(yolo_result->'vehicle_types', '{}')       AS yolo_vt,
                (
                    SELECT key FROM jsonb_each_text(yolo_result->'vehicle_types')
                    ORDER BY value::int DESC LIMIT 1
                ) AS dominant_type
            FROM lpr_events
            WHERE (%(ts_from)s IS NOT NULL AND %(ts_to)s IS NOT NULL
                   AND ts BETWEEN %(ts_from)s AND %(ts_to)s
                   OR  %(ts_from)s IS NULL
                   AND ts >= NOW() - INTERVAL %(window)s)
              AND plate IS NOT NULL
              AND plate <> ''
              AND plate NOT ILIKE 'unknown%%'
              AND confidence >= %(min_conf)s
            ORDER BY plate, camera_id,
                     (EXTRACT(EPOCH FROM ts)::int / %(dedup_sec)s), ts
        ),
        with_next AS (
            SELECT
                id              AS event_a_id,
                plate,
                camera_id       AS cam_a,
                ts              AS ts_a,
                image_path      AS img_a,
                yolo_vc         AS yolo_vc_a,
                yolo_vt         AS yolo_vt_a,
                dominant_type,
                LEAD(camera_id) OVER w AS cam_b,
                LEAD(ts)        OVER w AS ts_b,
                LEAD(id)        OVER w AS event_b_id,
                LEAD(yolo_vc)   OVER w AS yolo_vc_b
            FROM raw
            WINDOW w AS (PARTITION BY plate ORDER BY ts)
        ),
        pairs AS (
            SELECT
                plate,
                cam_a, cam_b,
                ts_a, ts_b,
                event_a_id, event_b_id,
                EXTRACT(EPOCH FROM (ts_b - ts_a))::int AS delta_t_sec,
                yolo_vc_a, yolo_vc_b, yolo_vt_a, dominant_type, img_a
            FROM with_next
            WHERE cam_b IS NOT NULL
              AND cam_b <> cam_a
              AND EXTRACT(EPOCH FROM (ts_b - ts_a)) BETWEEN %(dt_min)s AND %(dt_max)s
        )
        SELECT
            plate,
            COUNT(*)                                                         AS valid_transitions,
            MIN(ts_a)                                                        AS first_seen,
            MAX(ts_b)                                                        AS last_seen,
            AVG(delta_t_sec)::int                                            AS avg_delta_t_sec,
            SUM(CASE WHEN yolo_vc_a >= 2 OR yolo_vc_b >= 2 THEN 1 ELSE 0 END) AS yolo_multi_events,
            MODE() WITHIN GROUP (ORDER BY dominant_type)                    AS dominant_type,
            (COUNT(*) * 3
             + SUM(CASE WHEN yolo_vc_a >= 2 OR yolo_vc_b >= 2 THEN 1 ELSE 0 END) * 4
            )                                                               AS score,
            jsonb_agg(jsonb_build_object(
                'cam_a',       cam_a,
                'cam_b',       cam_b,
                'ts_a',        ts_a,
                'ts_b',        ts_b,
                'delta_t',     delta_t_sec,
                'event_a_id',  event_a_id,
                'event_b_id',  event_b_id,
                'yolo_vc_a',   yolo_vc_a,
                'yolo_vc_b',   yolo_vc_b,
                'yolo_vt_a',   yolo_vt_a
            ) ORDER BY ts_a)                                                AS evidence
        FROM pairs
        GROUP BY plate
        HAVING COUNT(*) >= %(min_transitions)s
        ORDER BY score DESC
        LIMIT %(limit)s
    """
    params = {
        "window":          interval,
        "ts_from":         ts_from,
        "ts_to":           ts_to,
        "min_conf":        MIN_LPR_CONFIDENCE,
        "dedup_sec":       DEDUP_SECONDS,
        "dt_min":          dt_min,
        "dt_max":          dt_max,
        "min_transitions": min_transitions,
        "limit":           limit,
    }
    try:
        with _conn() as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute(sql, params)
                items = list(cur.fetchall())

        type_filter = type.strip().lower()
        if type_filter != "all" and type_filter in {"car", "motorcycle", "truck", "bus"}:
            items = [
                r for r in items
                if (r.get("dominant_type") or "").lower() == type_filter
            ]

        return {
            "items": items,
            "count": len(items),
            "window": window,
            "filters": {
                "type":            type_filter,
                "dt_min":          dt_min,
                "dt_max":          dt_max,
                "min_transitions": min_transitions,
                "min_lpr_conf":    MIN_LPR_CONFIDENCE,
            },
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/batedor/groups")
def batedor_groups(
    window:      str           = Query("2h",  regex=r"^\d+[hmd]$"),
    limit:       int           = Query(20,    ge=1, le=200),
    min_shared:  int           = Query(1,     ge=1),
    co_window:   int           = Query(120,   ge=10, le=1800),
    ts_from:     Optional[str] = Query(None),
    ts_to:       Optional[str] = Query(None),
):
    """
    Detecta GRUPOS de 2+ placas diferentes viajando juntas:
    mesma transicao cam_A->cam_B dentro de co_window segundos entre si.
    min_shared: quantas transicoes em comum o par precisa ter.
    """
    try:
        interval = _parse_window(window)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    sql = """
        WITH deduped AS (
            SELECT DISTINCT ON (plate, camera_id, (EXTRACT(EPOCH FROM ts)::int / %(dedup_sec)s))
                id, plate, camera_id, ts,
                COALESCE((yolo_result->>'vehicle_count')::int, 0) AS yolo_vc,
                COALESCE((
                    SELECT key FROM jsonb_each_text(COALESCE(yolo_result->'vehicle_types', '{}'::jsonb))
                    ORDER BY value::int DESC LIMIT 1
                ), 'car') AS yolo_dom_type
            FROM lpr_events
            WHERE (%(ts_from)s IS NOT NULL AND %(ts_to)s IS NOT NULL
                   AND ts BETWEEN %(ts_from)s AND %(ts_to)s
                   OR  %(ts_from)s IS NULL
                   AND ts >= NOW() - INTERVAL %(window)s)
              AND plate IS NOT NULL AND plate <> ''
              AND plate NOT ILIKE 'unknown%%'
              AND confidence >= %(min_conf)s
            ORDER BY plate, camera_id,
                     (EXTRACT(EPOCH FROM ts)::int / %(dedup_sec)s), ts
        ),
        cosightings AS (
            -- pares de placas DIFERENTES vistas na MESMA camera dentro de co_window segundos
            SELECT
                LEAST(a.plate, b.plate)                            AS plate_a,
                GREATEST(a.plate, b.plate)                         AS plate_b,
                a.camera_id                                        AS camera,
                a.ts                                               AS ts_a,
                b.ts                                               AS ts_b,
                ABS(EXTRACT(EPOCH FROM (a.ts - b.ts)))::int        AS co_delta_sec,
                a.id                                               AS event_a_id,
                b.id                                               AS event_b_id,
                GREATEST(a.yolo_vc, b.yolo_vc)                    AS max_yolo_vc,
                COALESCE(NULLIF(a.yolo_dom_type,''), b.yolo_dom_type, 'car') AS dom_type
            FROM deduped a
            JOIN deduped b
              ON  b.camera_id = a.camera_id
             AND  b.plate <> a.plate
             AND  a.plate < b.plate
             AND  ABS(EXTRACT(EPOCH FROM (a.ts - b.ts))) <= %(co_window)s
        )
        SELECT
            plate_a,
            plate_b,
            COUNT(DISTINCT camera)                                 AS cameras_together,
            COUNT(*)                                               AS total_cosightings,
            MIN(LEAST(ts_a, ts_b))                                 AS first_seen,
            MAX(GREATEST(ts_a, ts_b))                              AS last_seen,
            AVG(co_delta_sec)::int                                 AS avg_co_delta_sec,
            COUNT(DISTINCT camera) * 5                             AS score,
            COUNT(*) FILTER (WHERE max_yolo_vc > 1)                AS yolo_multi_count,
            MODE() WITHIN GROUP (ORDER BY dom_type)                AS dominant_type,
            jsonb_agg(jsonb_build_object(
                'camera',       camera,
                'ts_a',         ts_a,
                'ts_b',         ts_b,
                'co_delta_sec', co_delta_sec,
                'event_a_id',   event_a_id,
                'event_b_id',   event_b_id
            ) ORDER BY ts_a)                                       AS evidence
        FROM cosightings
        GROUP BY plate_a, plate_b
        HAVING COUNT(DISTINCT camera) >= %(min_shared)s
        ORDER BY score DESC
        LIMIT %(limit)s
    """
    params = {
        "window":     interval,
        "ts_from":    ts_from,
        "ts_to":      ts_to,
        "min_conf":   MIN_LPR_CONFIDENCE,
        "dedup_sec":  DEDUP_SECONDS,
        "co_window":  co_window,
        "min_shared": min_shared,
        "limit":      limit,
    }
    try:
        with _conn() as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute(sql, params)
                items = list(cur.fetchall())
        return {
            "items": items,
            "count": len(items),
            "window": window,
            "filters": {
                "co_window":    co_window,
                "min_shared":   min_shared,
                "min_lpr_conf": MIN_LPR_CONFIDENCE,
            },
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# -- Helpers de imagem ------------------------------------------------------

def _get_event(event_id: int):
    with _conn() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute("SELECT * FROM lpr_events WHERE id = %s", (event_id,))
            return cur.fetchone()


def _safe_upload_path(rel_path: str) -> str:
    base = os.path.realpath("/app/uploads") + os.sep
    full = os.path.realpath(os.path.join("/app", rel_path))
    if not full.startswith(base):
        raise HTTPException(status_code=400, detail="Caminho invalido")
    if not os.path.exists(full):
        raise HTTPException(status_code=404, detail="Arquivo nao encontrado")
    return full


@app.get("/api/events/{event_id}/image")
def event_image(event_id: int):
    ev = _get_event(event_id)
    if not ev:
        raise HTTPException(status_code=404, detail="Evento nao encontrado")
    if not ev.get("image_path"):
        raise HTTPException(status_code=404, detail="Evento sem imagem")
    full = _safe_upload_path(ev["image_path"])
    return FileResponse(full)


@app.get("/api/events/{event_id}/thumbnail")
def event_thumbnail(
    event_id: int,
    w: int = Query(160, ge=40, le=640),
    h: int = Query(120, ge=30, le=480),
):
    from PIL import Image
    import io

    ev = _get_event(event_id)
    if not ev:
        raise HTTPException(status_code=404, detail="Evento nao encontrado")
    if not ev.get("image_path"):
        raise HTTPException(status_code=404, detail="Evento sem imagem")
    full = _safe_upload_path(ev["image_path"])
    try:
        img = Image.open(full)
        img.thumbnail((w, h), Image.LANCZOS)
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=75, optimize=True)
        buf.seek(0)
        return Response(
            content=buf.read(),
            media_type="image/jpeg",
            headers={"Cache-Control": "max-age=86400"},
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# -- Estatísticas / Dashboard -----------------------------------------------

@app.get("/api/stats/overview")
def stats_overview():
    with _conn() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute("""
                SELECT
                  (SELECT COUNT(*) FROM lpr_events) AS total_events,
                  (SELECT COUNT(*) FROM lpr_events
                     WHERE ts >= date_trunc('day', NOW() AT TIME ZONE 'UTC')) AS today_events,
                  (SELECT COUNT(*) FROM lpr_events
                     WHERE ts >= NOW() - INTERVAL '1 hour') AS last_hour_events,
                  (SELECT COUNT(DISTINCT camera_id) FROM lpr_events
                     WHERE ts >= NOW() - INTERVAL '24 hours' AND camera_id IS NOT NULL) AS active_cameras,
                  (SELECT COUNT(*) FROM monitored_vehicles) AS monitored_plates,
                  (SELECT COUNT(DISTINCT e.plate)
                     FROM lpr_events e
                     INNER JOIN monitored_vehicles mv ON mv.plate = e.plate
                     WHERE e.ts >= date_trunc('day', NOW() AT TIME ZONE 'UTC')) AS alerts_today
            """)
            row = cur.fetchone()
            return dict(row)


@app.get("/api/stats/events-per-hour")
def stats_events_per_hour():
    """Eventos por hora nas últimas 24h."""
    with _conn() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT date_trunc('hour', ts) AS hour, COUNT(*) AS total
                FROM lpr_events
                WHERE ts >= NOW() - INTERVAL '24 hours'
                GROUP BY 1
                ORDER BY 1
            """)
            rows = cur.fetchall()
            return {"data": [{"hour": r[0].isoformat(), "total": r[1]} for r in rows]}


@app.get("/api/stats/events-per-day")
def stats_events_per_day():
    """Eventos por dia nos últimos 30 dias."""
    with _conn() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT date_trunc('day', ts)::date AS day, COUNT(*) AS total
                FROM lpr_events
                WHERE ts >= NOW() - INTERVAL '30 days'
                GROUP BY 1
                ORDER BY 1
            """)
            rows = cur.fetchall()
            return {"data": [{"day": str(r[0]), "total": r[1]} for r in rows]}


@app.get("/api/stats/top-plates")
def stats_top_plates(limit: int = Query(10, ge=1, le=50)):
    """Placas mais vistas."""
    with _conn() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT plate, COUNT(*) AS total
                FROM lpr_events
                WHERE plate IS NOT NULL AND plate <> 'unknown'
                GROUP BY plate
                ORDER BY total DESC
                LIMIT %(limit)s
            """, {"limit": limit})
            rows = cur.fetchall()
            return {"data": [{"plate": r[0], "total": r[1]} for r in rows]}


@app.get("/api/stats/events-per-camera")
def stats_events_per_camera():
    """Eventos por câmera (últimas 24h)."""
    with _conn() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT COALESCE(camera_id, 'Desconhecida') AS camera, COUNT(*) AS total
                FROM lpr_events
                WHERE ts >= NOW() - INTERVAL '24 hours'
                GROUP BY 1
                ORDER BY total DESC
                LIMIT 12
            """)
            rows = cur.fetchall()
            return {"data": [{"camera": r[0], "total": r[1]} for r in rows]}
