# ===========================
# INGEST FASTAPI - BPFRON
# ===========================

import os
import re
import uuid
import xml.etree.ElementTree as ET
from contextlib import asynccontextmanager, contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import psycopg2
import psycopg2.pool
from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import JSONResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from starlette.datastructures import UploadFile
from starlette.requests import ClientDisconnect
from starlette.responses import RedirectResponse

import json as _json_lib
import redis as _redis_lib
from rq import Queue as _RQ_Queue

from jose import JWTError, jwt as _jwt
from passlib.context import CryptContext
from starlette.middleware.base import BaseHTTPMiddleware

# ===========================
# CONFIG
# ===========================

UPLOAD_DIR = Path("uploads")
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

MIN_LPR_CONFIDENCE = float(os.getenv("MIN_LPR_CONFIDENCE", "0.40"))

# ===========================
# AUTH / JWT
# ===========================
JWT_SECRET  = os.getenv("JWT_SECRET", "bpfron-secret-change-me-2026")
JWT_ALG     = "HS256"
JWT_EXPIRE  = int(os.getenv("JWT_EXPIRE_HOURS", "8"))  # horas

_pwd_ctx = CryptContext(schemes=["bcrypt"], deprecated="auto")

def _hash_pw(plain: str) -> str:
    return _pwd_ctx.hash(plain)

def _verify_pw(plain: str, hashed: str) -> bool:
    return _pwd_ctx.verify(plain, hashed)

def _make_token(sub: str, role: str, full_name: str) -> str:
    exp = datetime.now(timezone.utc) + timedelta(hours=JWT_EXPIRE)
    return _jwt.encode({"sub": sub, "role": role, "name": full_name, "exp": exp}, JWT_SECRET, algorithm=JWT_ALG)

def _decode_token(token: str) -> dict:
    return _jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALG])

# Paths públicos (não exigem JWT)
_PUBLIC_PREFIXES = ("/api/health", "/static", "/uploads", "/login", "/api/webhook", "/api/simple-webhook", "/api/ingest")
_PUBLIC_EXACT    = {"/", "/dashboard", "/favicon.ico", "/api/auth/login"}

# Regex para endpoints de imagem que o browser carrega diretamente (sem JWT header)
_PUBLIC_RE = re.compile(r'^/api/events/\d+/(image|thumbnail)(\?.*)?$')

class _AuthMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        path = request.url.path
        if path in _PUBLIC_EXACT or any(path.startswith(p) for p in _PUBLIC_PREFIXES) or _PUBLIC_RE.match(path):
            return await call_next(request)
        auth = request.headers.get("Authorization", "")
        if not auth.startswith("Bearer "):
            return JSONResponse({"detail": "Não autenticado"}, status_code=401)
        try:
            payload = _decode_token(auth.split(" ", 1)[1])
            request.state.user = payload
        except JWTError:
            return JSONResponse({"detail": "Token inválido ou expirado"}, status_code=401)
        return await call_next(request)

# ===========================
# DB
# ===========================

_db_pool: psycopg2.pool.ThreadedConnectionPool | None = None


def _get_pool():
    global _db_pool
    if not _db_pool:
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


_rq_queue_obj: Any = None


def _get_rq_queue():
    global _rq_queue_obj
    if _rq_queue_obj is None:
        r = _redis_lib.from_url(os.getenv("REDIS_URL", "redis://redis:6379/0"))
        _rq_queue_obj = _RQ_Queue("yolo", connection=r)
    return _rq_queue_obj


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
            # Cameras
            cur.execute("""
                CREATE TABLE IF NOT EXISTS cameras (
                    id SERIAL PRIMARY KEY,
                    camera_id TEXT UNIQUE NOT NULL,
                    nome TEXT NOT NULL,
                    ativa BOOLEAN DEFAULT TRUE,
                    criticidade TEXT DEFAULT 'normal',
                    peso FLOAT DEFAULT 1.0,
                    created_at TIMESTAMPTZ DEFAULT NOW()
                );
            """)
            # Se tabela já existia, garante colunas novas
            cur.execute("ALTER TABLE cameras ADD COLUMN IF NOT EXISTS criticidade TEXT DEFAULT 'NORMAL';")
            cur.execute("ALTER TABLE cameras ADD COLUMN IF NOT EXISTS peso FLOAT DEFAULT 1.0;")
            cur.execute("ALTER TABLE cameras ADD COLUMN IF NOT EXISTS peso_score FLOAT DEFAULT 1.0;")
            cur.execute("ALTER TABLE cameras ADD COLUMN IF NOT EXISTS ip TEXT;")
            cur.execute("ALTER TABLE cameras ADD COLUMN IF NOT EXISTS posicao INTEGER DEFAULT 0;")
            cur.execute("ALTER TABLE cameras ADD COLUMN IF NOT EXISTS direcao TEXT DEFAULT NULL;")
            cur.execute("ALTER TABLE cameras ADD COLUMN IF NOT EXISTS latitude DOUBLE PRECISION DEFAULT NULL;")
            cur.execute("ALTER TABLE cameras ADD COLUMN IF NOT EXISTS longitude DOUBLE PRECISION DEFAULT NULL;")

            # Eventos LPR
            cur.execute("""
                CREATE TABLE IF NOT EXISTS lpr_events (
                    id SERIAL PRIMARY KEY,
                    plate TEXT,
                    camera_id TEXT,
                    channel_name TEXT,
                    camera_ip TEXT,
                    confidence FLOAT,
                    image_path TEXT,
                    occurred_at TIMESTAMPTZ,
                    ts TIMESTAMPTZ DEFAULT NOW()
                );
            """)
            cur.execute("ALTER TABLE lpr_events ADD COLUMN IF NOT EXISTS yolo_result JSONB;")
            # Garante que a coluna ts existe mesmo em tabelas criadas por versões mais antigas
            cur.execute("ALTER TABLE lpr_events ADD COLUMN IF NOT EXISTS ts TIMESTAMPTZ DEFAULT NOW();")
            cur.execute("ALTER TABLE lpr_events ADD COLUMN IF NOT EXISTS occurred_at TIMESTAMPTZ;")
            cur.execute("ALTER TABLE lpr_events ADD COLUMN IF NOT EXISTS channel_name TEXT;")
            cur.execute("ALTER TABLE lpr_events ADD COLUMN IF NOT EXISTS camera_ip TEXT;")
            cur.execute("ALTER TABLE lpr_events ADD COLUMN IF NOT EXISTS confidence FLOAT;")
            cur.execute("ALTER TABLE lpr_events ADD COLUMN IF NOT EXISTS image_path TEXT;")
            cur.execute("ALTER TABLE lpr_events ADD COLUMN IF NOT EXISTS plate TEXT;")
            cur.execute("ALTER TABLE lpr_events ADD COLUMN IF NOT EXISTS camera_id TEXT;")

            # Migração: preenche ip a partir do histórico de lpr_events
            # (usa o camera_ip mais recente para cada camera_id já cadastrada)
            # Executa após garantir que lpr_events e coluna ts existem
            cur.execute("""
                UPDATE cameras c
                SET ip = sub.camera_ip
                FROM (
                    SELECT DISTINCT ON (camera_id)
                        camera_id, camera_ip
                    FROM lpr_events
                    WHERE camera_id IS NOT NULL AND camera_ip IS NOT NULL
                      AND camera_ip NOT LIKE '172.19.%'
                    ORDER BY camera_id, ts DESC
                ) sub
                WHERE c.camera_id = sub.camera_id
                  AND c.ip IS NULL;
            """)

            # Veículos e Listas de Monitoramento
            cur.execute("""
                CREATE TABLE IF NOT EXISTS vehicle_lists (
                    id SERIAL PRIMARY KEY,
                    name TEXT NOT NULL,
                    description TEXT,
                    color TEXT,
                    alarm_enabled BOOLEAN DEFAULT FALSE,
                    alarm_sound TEXT,
                    created_at TIMESTAMPTZ DEFAULT NOW(),
                    updated_at TIMESTAMPTZ DEFAULT NOW()
                );
            """)

            # Garantir que as colunas existem (para tabelas existentes)
            cur.execute("ALTER TABLE vehicle_lists ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ DEFAULT NOW();")
            cur.execute("ALTER TABLE vehicle_lists ADD COLUMN IF NOT EXISTS color TEXT;")
            cur.execute("ALTER TABLE vehicle_lists ADD COLUMN IF NOT EXISTS alarm_enabled BOOLEAN DEFAULT FALSE;")
            cur.execute("ALTER TABLE vehicle_lists ADD COLUMN IF NOT EXISTS alarm_sound TEXT;")

            # Usuários
            cur.execute("""
                CREATE TABLE IF NOT EXISTS users (
                    id SERIAL PRIMARY KEY,
                    username TEXT UNIQUE NOT NULL,
                    password_hash TEXT NOT NULL,
                    full_name TEXT DEFAULT '',
                    role TEXT DEFAULT 'operator',
                    ativa BOOLEAN DEFAULT TRUE,
                    created_at TIMESTAMPTZ DEFAULT NOW(),
                    updated_at TIMESTAMPTZ DEFAULT NOW()
                );
            """)
            # Inserir admin padrão se não existir
            cur.execute("SELECT id FROM users WHERE username='admin' LIMIT 1")
            if not cur.fetchone():
                cur.execute(
                    "INSERT INTO users (username, password_hash, full_name, role) VALUES (%s, %s, %s, %s)",
                    ("admin", _hash_pw("admin123"), "Administrador", "admin")
                )

            cur.execute("""
                CREATE TABLE IF NOT EXISTS vehicle_list_items (
                    id SERIAL PRIMARY KEY,
                    list_id INTEGER NOT NULL REFERENCES vehicle_lists(id) ON DELETE CASCADE,
                    plate TEXT NOT NULL,
                    notes TEXT,
                    created_at TIMESTAMPTZ DEFAULT NOW(),
                    UNIQUE(list_id, plate)
                );
            """)



# ===========================
# HELPERS
# ===========================

def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def get_camera_row(camera_id: str) -> dict[str, Any] | None:
    with _conn() as conn:
        with conn.cursor() as cur:
            # Busca por camera_id (nome descritivo) OU por ip — necessário porque
            # as câmeras Hikvision enviam o próprio IP no XML <ipAddress> e esse
            # valor é usado como chave de lookup no webhook.
            cur.execute(
                "SELECT id, camera_id, nome, ativa, criticidade, peso, created_at, ip, direcao, latitude, longitude FROM cameras WHERE camera_id=%s OR ip=%s LIMIT 1",
                (camera_id, camera_id),
            )
            row = cur.fetchone()
            if not row:
                return None
            peso_val = float(row[5] or 1.0)
            return {
                "id": row[0],
                "camera_id": row[1],
                "nome": row[2],
                "ativa": row[3],
                "criticidade": (row[4] or "NORMAL").upper(),
                "peso": peso_val,
                "peso_score": peso_val,
                "ip": row[7],
                "created_at": row[6].isoformat() if row[6] else None,
                "direcao": row[8] or None,
                "latitude":  float(row[9])  if row[9]  is not None else None,
                "longitude": float(row[10]) if row[10] is not None else None,
            }


def ensure_camera_exists(camera_id: str, default_name: str | None = None, ip: str | None = None) -> dict[str, Any]:
    # Não auto-cadastra: apenas retorna a câmera se existir e atualiza o IP
    row = get_camera_row(camera_id)
    if row:
        if ip and not row.get("ip"):
            with _conn() as conn:
                with conn.cursor() as cur:
                    cur.execute("UPDATE cameras SET ip=%s WHERE camera_id=%s", (ip, camera_id))
        return row
    # Câmera não cadastrada: retorna dict mínimo sem gravar no banco
    nome = default_name or camera_id
    return {
        "camera_id": camera_id,
        "nome": nome,
        "ativa": True,
        "criticidade": "NORMAL",
        "peso": 1.0,
        "peso_score": 1.0,
        "ip": ip,
    }


def get_camera_name(camera_id: str | None) -> str | None:
    if not camera_id:
        return None
    try:
        row = get_camera_row(camera_id)
        if row and row.get("ativa"):
            return row["nome"]
    except Exception as e:
        print(f"[CAMERA] erro ao resolver camera_id={camera_id}: {e}")
    return None


def _get_client_ip(request: Request) -> str:
    xf = request.headers.get("x-forwarded-for")
    if xf:
        return xf.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def _parse_dt(s: str | None) -> datetime | None:
    if not s:
        return None
    try:
        dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
        if not dt.tzinfo:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except Exception:
        return None


# ===========================
# EVENT (buscar por ID) ✅ ADICIONADO
# ===========================

def get_event_by_id(event_id: int) -> dict[str, Any] | None:
    with _conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT id, plate, camera_id, channel_name, camera_ip, confidence, image_path,
                       COALESCE(occurred_at, ts) AS when_ts
                FROM lpr_events
                WHERE id = %s
                LIMIT 1
                """,
                (event_id,),
            )
            r = cur.fetchone()
            if not r:
                return None

    ts = r[7].isoformat() if r[7] else None
    img = r[6]
    return {
        "id": r[0],
        "plate": r[1],
        "camera_id": r[2],
        "channel_name": r[3],
        "camera_ip": r[4],
        "confidence": float(r[5] or 0.0),
        "image_path": img,
        "occurred_at": ts,
        "camera": r[3],
        "timestamp": ts,
        "image": img,
        "thumb": img,
    }


# ===========================
# FASTAPI
# ===========================

@asynccontextmanager
async def lifespan(app: FastAPI):
    _init_db()
    yield


app = FastAPI(lifespan=lifespan)
app.add_middleware(_AuthMiddleware)

# static
os.makedirs("static", exist_ok=True)
app.mount("/static", StaticFiles(directory="static"), name="static")
app.mount("/uploads", StaticFiles(directory="uploads"), name="uploads")


@app.get("/", include_in_schema=False)
def root():
    return FileResponse(
        "static/dashboard.html",
        headers={
            "Cache-Control": "no-store, no-cache, must-revalidate",
            "Pragma": "no-cache",
            "Expires": "0",
        },
    )


@app.get("/dashboard", include_in_schema=False)
def dashboard():
    return FileResponse(
        "static/dashboard.html",
        headers={
            "Cache-Control": "no-store, no-cache, must-revalidate",
            "Pragma": "no-cache",
            "Expires": "0",
        },
    )

@app.get("/login", include_in_schema=False)
def login_page():
    return FileResponse(
        "static/login.html",
        headers={
            "Cache-Control": "no-store, no-cache, must-revalidate",
            "Pragma": "no-cache",
            "Expires": "0",
        },
    )

# ===========================
# AUTH ENDPOINTS
# ===========================

@app.post("/api/auth/login")
async def auth_login(request: Request):
    data = await request.json()
    username = str(data.get("username") or "").strip().lower()
    password = str(data.get("password") or "")
    if not username or not password:
        raise HTTPException(status_code=400, detail="username e password são obrigatórios")
    with _conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT id, username, password_hash, full_name, role, ativa FROM users WHERE username=%s LIMIT 1", (username,))
            row = cur.fetchone()
    if not row:
        raise HTTPException(status_code=401, detail="Usuário ou senha inválidos")
    uid, uname, pw_hash, full_name, role, ativa = row
    if not ativa:
        raise HTTPException(status_code=403, detail="Usuário inativo")
    if not _verify_pw(password, pw_hash):
        raise HTTPException(status_code=401, detail="Usuário ou senha inválidos")
    token = _make_token(uname, role, full_name or uname)
    return {"access_token": token, "token_type": "bearer", "role": role, "full_name": full_name or uname, "username": uname}

@app.get("/api/auth/me")
async def auth_me(request: Request):
    user = getattr(request.state, "user", None)
    if not user:
        raise HTTPException(status_code=401, detail="Não autenticado")
    return {"username": user.get("sub"), "role": user.get("role"), "full_name": user.get("name")}

@app.put("/api/auth/password")
async def change_my_password(request: Request):
    user = getattr(request.state, "user", None)
    if not user:
        raise HTTPException(status_code=401, detail="Não autenticado")
    data = await request.json()
    current_pw = data.get("current_password", "")
    new_pw     = data.get("new_password", "")
    if not current_pw or not new_pw:
        raise HTTPException(status_code=400, detail="Campos obrigatórios: current_password e new_password")
    if len(new_pw) < 6:
        raise HTTPException(status_code=400, detail="Nova senha deve ter pelo menos 6 caracteres")
    username = user.get("sub")
    with _conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT id, password_hash FROM users WHERE username=%s", (username,))
            row = cur.fetchone()
            if not row:
                raise HTTPException(status_code=404, detail="Usuário não encontrado")
            if not _verify_pw(current_pw, row[1]):
                raise HTTPException(status_code=400, detail="Senha atual incorreta")
            cur.execute("UPDATE users SET password_hash=%s, updated_at=NOW() WHERE id=%s", (_hash_pw(new_pw), row[0]))
    return {"ok": True}

# ===========================
# USERS CRUD
# ===========================

@app.get("/api/users")
async def list_users(request: Request):
    user = getattr(request.state, "user", {})
    if user.get("role") != "admin":
        raise HTTPException(status_code=403, detail="Acesso restrito a administradores")
    with _conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT id, username, full_name, role, ativa, created_at FROM users ORDER BY id")
            rows = cur.fetchall()
    return {"items": [{"id": r[0], "username": r[1], "full_name": r[2], "role": r[3], "ativa": r[4], "created_at": r[5].isoformat() if r[5] else None} for r in rows]}

@app.post("/api/users", status_code=201)
async def create_user(request: Request):
    user = getattr(request.state, "user", {})
    if user.get("role") != "admin":
        raise HTTPException(status_code=403, detail="Acesso restrito a administradores")
    data = await request.json()
    username  = str(data.get("username") or "").strip().lower()
    password  = str(data.get("password") or "").strip()
    full_name = str(data.get("full_name") or "").strip()
    role      = str(data.get("role") or "operator").strip()
    ativa     = bool(data.get("ativa", True))
    if not username: raise HTTPException(status_code=400, detail="username obrigatório")
    if not password: raise HTTPException(status_code=400, detail="password obrigatório")
    if role not in ("admin", "operator", "viewer"): raise HTTPException(status_code=400, detail="role inválido")
    try:
        with _conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "INSERT INTO users (username, password_hash, full_name, role, ativa) VALUES (%s,%s,%s,%s,%s) RETURNING id",
                    (username, _hash_pw(password), full_name, role, ativa)
                )
                new_id = cur.fetchone()[0]
    except Exception as e:
        if "unique" in str(e).lower():
            raise HTTPException(status_code=409, detail="Username já existe")
        raise
    return {"id": new_id, "username": username, "full_name": full_name, "role": role, "ativa": ativa}

@app.put("/api/users/{uid}")
async def update_user(uid: int, request: Request):
    requester = getattr(request.state, "user", {})
    if requester.get("role") != "admin" and requester.get("sub") != uid:
        raise HTTPException(status_code=403, detail="Acesso negado")
    data = await request.json()
    sets, vals = [], []
    if "full_name" in data: sets.append("full_name=%s"); vals.append(str(data["full_name"]).strip())
    if "role" in data:
        role = str(data["role"]).strip()
        if role not in ("admin", "operator", "viewer"): raise HTTPException(status_code=400, detail="role inválido")
        sets.append("role=%s"); vals.append(role)
    if "ativa" in data: sets.append("ativa=%s"); vals.append(bool(data["ativa"]))
    if "password" in data and data["password"]:
        sets.append("password_hash=%s"); vals.append(_hash_pw(str(data["password"])))
    if not sets: raise HTTPException(status_code=400, detail="Nenhum campo para atualizar")
    sets.append("updated_at=NOW()")
    vals.append(uid)
    with _conn() as conn:
        with conn.cursor() as cur:
            cur.execute(f"UPDATE users SET {', '.join(sets)} WHERE id=%s", tuple(vals))
            if cur.rowcount == 0: raise HTTPException(status_code=404, detail="Usuário não encontrado")
    return {"ok": True}

@app.delete("/api/users/{uid}", status_code=204)
async def delete_user(uid: int, request: Request):
    requester = getattr(request.state, "user", {})
    if requester.get("role") != "admin":
        raise HTTPException(status_code=403, detail="Acesso restrito a administradores")
    with _conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT username FROM users WHERE id=%s", (uid,))
            row = cur.fetchone()
            if not row: raise HTTPException(status_code=404, detail="Usuário não encontrado")
            if row[0] == "admin": raise HTTPException(status_code=400, detail="Não é possível excluir o admin principal")
            cur.execute("DELETE FROM users WHERE id=%s", (uid,))


# ===========================
# HEALTH
# ===========================

@app.get("/health")
def health():
    return {"status": "ok"}


# ===========================
# CAMERAS (CRUD) + CLASSIFICAÇÃO
# ===========================

@app.get("/api/cameras")
def list_cameras(include_inactive: bool = False):
    where = "" if include_inactive else "WHERE c.ativa = TRUE"
    with _conn() as conn:
        with conn.cursor() as cur:
            cur.execute(f"""
                SELECT c.id, c.camera_id, c.nome, c.ativa, c.criticidade, c.peso,
                       c.created_at, c.ip,
                       s.last_seen, s.total_events, s.events_today,
                       c.direcao, c.latitude, c.longitude
                FROM cameras c
                LEFT JOIN (
                    SELECT camera_id,
                           MAX(COALESCE(occurred_at, ts))          AS last_seen,
                           COUNT(*)                                 AS total_events,
                           COUNT(*) FILTER (WHERE COALESCE(occurred_at, ts) >= CURRENT_DATE) AS events_today
                    FROM lpr_events
                    GROUP BY camera_id
                ) s ON s.camera_id = c.camera_id
                      OR s.camera_id = c.ip
                {where}
                ORDER BY c.id ASC
            """)
            rows = cur.fetchall()

    items = []
    for r in rows:
        items.append({
            "id":           r[0],
            "camera_id":    r[1],
            "nome":         r[2],
            "ativa":        r[3],
            "criticidade":  (r[4] or "NORMAL").upper(),
            "peso_score":   float(r[5] or 1.0),
            "created_at":   r[6].isoformat() if r[6] else None,
            "ip":           r[7],
            "last_seen":    r[8].isoformat() if r[8] else None,
            "total_events": int(r[9] or 0),
            "events_today": int(r[10] or 0),
            "direcao":      r[11] or None,
            "latitude":     float(r[12]) if r[12] is not None else None,
            "longitude":    float(r[13]) if r[13] is not None else None,
        })
    return {"items": items, "total": len(items)}


@app.get("/api/cameras/status")
def cameras_status():
    """Retorna timestamp do último evento por camera_id (para indicador online/offline)."""
    with _conn() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT camera_id, MAX(occurred_at) AS last_seen
                FROM lpr_events
                WHERE camera_id IS NOT NULL
                GROUP BY camera_id
            """)
            rows = cur.fetchall()
    result = {}
    for r in rows:
        result[r[0]] = r[1].isoformat() if r[1] else None
    return {"status": result}


@app.post("/api/cameras")
async def create_camera(request: Request):
    data = await request.json()
    camera_id = (data.get("camera_id") or "").strip()
    nome = (data.get("nome") or "").strip()
    criticidade = (data.get("criticidade") or "NORMAL").strip().upper()
    peso = float(data.get("peso_score") or data.get("peso") or 1.0)
    ip = (data.get("ip") or "").strip() or None
    direcao = (data.get("direcao") or "").strip().upper() or None
    latitude  = float(data["latitude"])  if data.get("latitude")  not in (None, "") else None
    longitude = float(data["longitude"]) if data.get("longitude") not in (None, "") else None

    if not camera_id or not nome:
        raise HTTPException(status_code=400, detail="camera_id e nome são obrigatórios")
    if criticidade not in ("NORMAL", "CRITICA"):
        raise HTTPException(status_code=400, detail="criticidade deve ser 'NORMAL' ou 'CRITICA'")
    if peso <= 0:
        raise HTTPException(status_code=400, detail="peso deve ser > 0")
    if direcao and direcao not in ("CRESCENTE", "DECRESCENTE"):
        raise HTTPException(status_code=400, detail="direcao deve ser 'CRESCENTE' ou 'DECRESCENTE'")

    with _conn() as conn:
        with conn.cursor() as cur:
            # Bloqueia IP duplicado
            if ip:
                cur.execute("SELECT camera_id FROM cameras WHERE ip=%s AND camera_id!=%s LIMIT 1", (ip, camera_id))
                dup = cur.fetchone()
                if dup:
                    raise HTTPException(status_code=400, detail=f"IP {ip} já está em uso pela câmera '{dup[0]}'")
            cur.execute(
                """
                INSERT INTO cameras (camera_id, nome, ativa, criticidade, peso, peso_score, ip, direcao, latitude, longitude)
                VALUES (%s, %s, TRUE, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (camera_id) DO UPDATE SET
                    nome = EXCLUDED.nome,
                    ativa = TRUE,
                    criticidade = EXCLUDED.criticidade,
                    peso = EXCLUDED.peso,
                    peso_score = EXCLUDED.peso_score,
                    ip = COALESCE(EXCLUDED.ip, cameras.ip),
                    direcao = EXCLUDED.direcao,
                    latitude  = COALESCE(EXCLUDED.latitude,  cameras.latitude),
                    longitude = COALESCE(EXCLUDED.longitude, cameras.longitude)
                """,
                (camera_id, nome, criticidade, peso, peso, ip, direcao, latitude, longitude),
            )

    return {"ok": True, "camera": get_camera_row(camera_id)}


@app.put("/api/cameras/{cam_id}")
async def update_camera(cam_id: int, request: Request):
    data = await request.json()
    nome        = data.get("nome")
    criticidade = data.get("criticidade")
    peso        = data.get("peso_score") or data.get("peso")
    ativa       = data.get("ativa")
    new_cam_id  = data.get("camera_id")
    ip          = data.get("ip")
    direcao     = data.get("direcao")

    if criticidade is not None:
        criticidade = str(criticidade).strip().upper()
        if criticidade not in ("NORMAL", "CRITICA"):
            raise HTTPException(status_code=400, detail="criticidade deve ser 'NORMAL' ou 'CRITICA'")

    if peso is not None:
        peso = float(peso)
        if peso <= 0:
            raise HTTPException(status_code=400, detail="peso deve ser > 0")

    with _conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT 1 FROM cameras WHERE id=%s LIMIT 1", (cam_id,))
            if not cur.fetchone():
                raise HTTPException(status_code=404, detail="câmera não encontrada")

            sets: list[str] = []
            vals: list[Any] = []

            if new_cam_id is not None:
                sets.append("camera_id=%s"); vals.append(str(new_cam_id).strip())
            if nome is not None:
                sets.append("nome=%s"); vals.append(str(nome).strip())
            if criticidade is not None:
                sets.append("criticidade=%s"); vals.append(criticidade)
            if peso is not None:
                sets.append("peso=%s");       vals.append(peso)
                sets.append("peso_score=%s"); vals.append(peso)
            if ativa is not None:
                sets.append("ativa=%s"); vals.append(bool(ativa))
            if ip is not None:
                clean_ip = str(ip).strip() or None
                # Bloqueia IP duplicado no update
                if clean_ip:
                    cur.execute("SELECT camera_id FROM cameras WHERE ip=%s AND id!=%s LIMIT 1", (clean_ip, cam_id))
                    dup = cur.fetchone()
                    if dup:
                        raise HTTPException(status_code=400, detail=f"IP {clean_ip} já está em uso pela câmera '{dup[0]}'")
                sets.append("ip=%s"); vals.append(clean_ip)
            if direcao is not None:
                d_val = str(direcao).strip().upper() or None
                if d_val and d_val not in ("CRESCENTE", "DECRESCENTE"):
                    raise HTTPException(status_code=400, detail="direcao deve ser 'CRESCENTE' ou 'DECRESCENTE'")
                sets.append("direcao=%s"); vals.append(d_val)
            if "latitude" in data:
                lat_val = float(data["latitude"]) if data["latitude"] not in (None, "") else None
                sets.append("latitude=%s"); vals.append(lat_val)
            if "longitude" in data:
                lng_val = float(data["longitude"]) if data["longitude"] not in (None, "") else None
                sets.append("longitude=%s"); vals.append(lng_val)

            if sets:
                vals.append(cam_id)
                cur.execute(f"UPDATE cameras SET {', '.join(sets)} WHERE id=%s", tuple(vals))

    # retorna a câmera atualizada via get_camera_row por id
    with _conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT id, camera_id, nome, ativa, criticidade, peso, created_at, ip, latitude, longitude FROM cameras WHERE id=%s LIMIT 1",
                (cam_id,),
            )
            row = cur.fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="câmera não encontrada")
    peso_val = float(row[5] or 1.0)
    return {
        "id": row[0], "camera_id": row[1], "nome": row[2], "ativa": row[3],
        "criticidade": (row[4] or "NORMAL").upper(),
        "peso_score": peso_val, "peso": peso_val,
        "created_at": row[6].isoformat() if row[6] else None,
        "ip": row[7],
        "latitude":  float(row[8]) if row[8] is not None else None,
        "longitude": float(row[9]) if row[9] is not None else None,
    }


@app.delete("/api/cameras/{cam_id}")
def delete_camera(cam_id: int):
    with _conn() as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM cameras WHERE id=%s", (cam_id,))
    return {"ok": True}


# ===========================
# EVENTS (lista para o dashboard)
# ===========================

@app.get("/api/events")
def list_events(
    page: int = 1,
    limit: int = 10,
    offset: int | None = None,   # dashboard envia offset direto
    plate: str | None = None,
    camera_id: str | None = None,
    dt_from: str | None = None,
    dt_to: str | None = None,
):
    limit = max(1, min(200, int(limit)))
    if offset is not None:
        offset = max(0, int(offset))
        page = (offset // limit) + 1
    else:
        page = max(1, int(page))
        offset = (page - 1) * limit

    where = []
    vals: list[Any] = []

    if plate:
        where.append("e.plate ILIKE %s")
        vals.append(f"%{plate.strip()}%")

    if camera_id:
        where.append("e.camera_id = %s")
        vals.append(camera_id.strip())

    f = _parse_dt(dt_from)
    t = _parse_dt(dt_to)
    if f:
        where.append("COALESCE(e.occurred_at, e.ts) >= %s")
        vals.append(f)
    if t:
        where.append("COALESCE(e.occurred_at, e.ts) <= %s")
        vals.append(t)

    wsql = ("WHERE " + " AND ".join(where)) if where else ""

    with _conn() as conn:
        with conn.cursor() as cur:
            cur.execute(f"SELECT COUNT(*) FROM lpr_events e {wsql}", tuple(vals))
            total = int(cur.fetchone()[0])

            cur.execute(
                f"""
                SELECT e.id, e.plate, e.camera_id, e.channel_name, e.camera_ip, e.confidence,
                       e.image_path, COALESCE(e.occurred_at, e.ts) AS when_ts, e.yolo_result,
                       c.nome AS cam_nome, c.direcao
                FROM lpr_events e
                LEFT JOIN cameras c ON c.ip = e.camera_id OR c.ip = e.camera_ip
                {wsql}
                ORDER BY COALESCE(e.occurred_at, e.ts) DESC
                LIMIT %s OFFSET %s
                """,
                tuple(vals + [limit, offset]),
            )
            rows = cur.fetchall()

    items = []
    for r in rows:
        ts = r[7].isoformat() if r[7] else None
        img = r[6]
        yolo = _json_lib.loads(r[8]) if r[8] else None
        items.append({
            "id": r[0],
            "plate": r[1],
            "camera_id": r[2],
            "channel_name": r[3],
            "camera_ip": r[4],
            "confidence": float(r[5] or 0.0),
            "image_path": img,
            "occurred_at": ts,
            "camera": r[9] or r[3],
            "timestamp": ts,
            "image": img,
            "thumb": img,
            "yolo_result": yolo,
            # Campos extraídos do yolo_result para fácil acesso no frontend
            "sem_placa_motivo": yolo.get("sem_placa_motivo") if yolo else None,
            "vehicle_details":  yolo.get("vehicle_details")  if yolo else None,
            "image_quality":    yolo.get("image_quality")    if yolo else None,
            "cam_nome": r[9] or r[3],
            "direcao": r[10] or None,
        })

    return {"items": items, "page": page, "limit": limit, "total": total}


@app.get("/api/events/{event_id}/image")
def get_event_image(event_id: int):
    """Redireciona para image_path do evento (usado pelo modal do dashboard)."""
    with _conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT image_path FROM lpr_events WHERE id=%s LIMIT 1", (event_id,))
            row = cur.fetchone()
    if not row or not row[0]:
        raise HTTPException(status_code=404, detail="imagem não encontrada")
    return RedirectResponse(url=row[0])


# ===========================
# STATS (dashboard)
# ===========================

@app.get("/api/stats/overview")
def stats_overview():
    now          = _utcnow()
    one_hour_ago = now - timedelta(hours=1)
    today_start  = now.replace(hour=0, minute=0, second=0, microsecond=0)

    with _conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM lpr_events")
            total = int(cur.fetchone()[0])

            cur.execute("""
                SELECT plate, COALESCE(occurred_at, ts)
                FROM lpr_events
                ORDER BY COALESCE(occurred_at, ts) DESC
                LIMIT 1
            """)
            last       = cur.fetchone()
            last_plate = last[0] if last else None
            last_ts    = last[1].isoformat() if last and last[1] else None

            cur.execute("""
                SELECT COUNT(*) FROM lpr_events
                WHERE COALESCE(occurred_at, ts) >= %s
            """, (one_hour_ago,))
            last_hour = int(cur.fetchone()[0])

            cur.execute("""
                SELECT COUNT(*) FROM lpr_events
                WHERE COALESCE(occurred_at, ts) >= %s
            """, (today_start,))
            today_events = int(cur.fetchone()[0])

            cur.execute("""
                SELECT COUNT(DISTINCT camera_id) FROM lpr_events
                WHERE COALESCE(occurred_at, ts) >= %s
                  AND camera_id IS NOT NULL
            """, (now - timedelta(hours=24),))
            active_cameras = int(cur.fetchone()[0])

            cur.execute("""
                SELECT AVG(confidence) FROM (
                    SELECT confidence FROM lpr_events
                    WHERE confidence IS NOT NULL
                    ORDER BY COALESCE(occurred_at, ts) DESC
                    LIMIT 50
                ) t
            """)
            avg_conf = cur.fetchone()[0]
            avg_conf = float(avg_conf) if avg_conf is not None else 0.0

    avg_conf_val = round(avg_conf * 100, 1) if avg_conf <= 1.0 else round(avg_conf, 1)
    return {
        "total":                  total,
        "total_db":               total,
        "total_events":           total,
        "today_events":           today_events,
        "last_plate":             last_plate,
        "last_ts":                last_ts,
        "last_hour":              last_hour,
        "last_hour_count":        last_hour,
        "last_hour_events":       last_hour,
        "active_cameras":         active_cameras,
        "monitored_plates":       0,
        "alerts_today":           0,
        "alerts":                 0,
        "avg_confidence_last_50": avg_conf_val,
        "avg_conf_last50":        avg_conf_val,
    }


@app.get("/api/stats/events-per-hour")
def stats_events_per_hour(hours: int = 12):
    hours = max(1, min(72, int(hours)))
    now = _utcnow()
    start = now - timedelta(hours=hours)

    with _conn() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT date_trunc('hour', COALESCE(occurred_at, ts)) AS h, COUNT(*)
                FROM lpr_events
                WHERE COALESCE(occurred_at, ts) >= %s
                GROUP BY 1
                ORDER BY 1 ASC
            """, (start,))
            rows = cur.fetchall()

    items = [{"hour": r[0].strftime("%H:00"), "count": int(r[1])} for r in rows]
    return {
        "items": items,
        "labels": [r["hour"] for r in items],
        "values": [r["count"] for r in items],
    }


@app.get("/api/stats/events-per-day")
def stats_events_per_day(days: int = 30):
    days = max(1, min(365, int(days)))
    now = _utcnow()
    start = now - timedelta(days=days)

    with _conn() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT date_trunc('day', COALESCE(occurred_at, ts)) AS d, COUNT(*)
                FROM lpr_events
                WHERE COALESCE(occurred_at, ts) >= %s
                GROUP BY 1
                ORDER BY 1 ASC
            """, (start,))
            rows = cur.fetchall()

    items = [{"day": r[0].date().isoformat(), "count": int(r[1])} for r in rows]
    return {
        "items": items,
        "labels": [r["day"] for r in items],
        "values": [r["count"] for r in items],
    }


@app.get("/api/stats/top-plates")
def stats_top_plates(limit: int = 10):
    limit = max(1, min(50, int(limit)))
    with _conn() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT plate, COUNT(*) as c
                FROM lpr_events
                WHERE plate IS NOT NULL AND plate <> ''
                GROUP BY plate
                ORDER BY c DESC
                LIMIT %s
            """, (limit,))
            rows = cur.fetchall()

    return {"items": [{"plate": r[0], "count": int(r[1])} for r in rows]}


@app.get("/api/stats/events-per-camera")
def stats_events_per_camera():
    with _conn() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT COALESCE(channel_name, camera_id, 'desconhecida') as cam, COUNT(*) as c
                FROM lpr_events
                GROUP BY 1
                ORDER BY c DESC
                LIMIT 50
            """)
            rows = cur.fetchall()

    return {"items": [{"camera": r[0], "count": int(r[1])} for r in rows[:10]]}


# ===========================
# WEBHOOK HIKVISION (ISAPI multipart)
# ===========================

@app.post("/api/simple-webhook")
async def simple_webhook(request: Request):
    client_ip = _get_client_ip(request)
    content_type = request.headers.get("content-type", "")

    if "multipart/form-data" not in content_type:
        body = await request.body()
        return JSONResponse({"ok": True, "bytes": len(body)})

    try:
        form = await request.form()
    except ClientDisconnect:
        return JSONResponse({"ok": True})

    xml_bytes = None
    images: list[tuple[str, bytes]] = []

    for _, v in form.multi_items():
        if isinstance(v, UploadFile):
            data = await v.read()
            if v.filename and v.filename.lower().endswith(".xml"):
                xml_bytes = data
            elif len(data) >= 10_000:
                images.append((v.filename or "image.jpg", data))

    plate = "unknown"
    camera_id = None
    xml_ip = None          # IP real da câmera (do XML <ipAddress>)
    channel_name_xml = None
    confidence = 0.0
    occurred_at = None

    if xml_bytes:
        try:
            root = ET.fromstring(xml_bytes)
            ns = {"h": "http://www.isapi.org/ver20/XMLSchema"}

            def x(tag):
                # busca recursiva: encontra tags aninhadas (ex: ANPR/licensePlate)
                el = root.find(f".//h:{tag}", ns)
                return el.text.strip() if el is not None and el.text else None

            plate            = x("licensePlate") or "unknown"
            xml_ip           = x("ipAddress")           # IP real: "172.21.151.16"
            channel_name_xml = x("channelName")         # nome do canal: "11_PRAINHA_1_CHACARAS"
            channel_id_xml   = x("channelID")           # fallback: "1"

            # camera_id = IP real do XML (identificador único por dispositivo)
            # fallback: channelName, depois channelID
            camera_id = xml_ip or channel_name_xml or channel_id_xml

            dt = x("dateTime")
            if dt:
                try:
                    occurred_at = datetime.fromisoformat(dt)
                    if not occurred_at.tzinfo:
                        occurred_at = occurred_at.replace(tzinfo=timezone.utc)
                except Exception:
                    occurred_at = None

            try:
                confidence = float(x("confidenceLevel") or 0)
            except Exception:
                confidence = 0.0

        except Exception as e:
            print(f"[XML] erro parse: {e}")

    # Rejeita se não identificou nenhuma câmera no XML
    if not camera_id:
        print(f"[INGEST] evento sem camera_id ignorado (ip cliente={client_ip})")
        return JSONResponse({"ok": False, "detail": "camera não identificada no XML"}, status_code=400)

    channel_name = None
    if camera_id:
        # nome padrão = channelName do XML; fallback = próprio camera_id
        default_nome = channel_name_xml or camera_id
        cam = ensure_camera_exists(camera_id, default_name=default_nome, ip=xml_ip)
        # Rejeita evento se câmera não estiver cadastrada no banco
        if not cam.get("id"):
            print(f"[INGEST] câmera não cadastrada ignorada: camera_id={camera_id} ip={xml_ip}")
            return JSONResponse({"ok": False, "detail": f"câmera '{camera_id}' não cadastrada"}, status_code=403)
        channel_name = cam.get("nome") or default_nome

    image_path = None
    if images:
        _, data = images[0]
        day = _utcnow().strftime("%Y-%m-%d")
        d = UPLOAD_DIR / day
        d.mkdir(parents=True, exist_ok=True)
        fname = f"{uuid.uuid4().hex}.jpg"
        (d / fname).write_bytes(data)
        image_path = f"/uploads/{day}/{fname}"
        # Enfileira análise YOLO para esta imagem
        try:
            abs_path = f"/app/uploads/{day}/{fname}"
            _get_rq_queue().enqueue(
                "worker.job_analyze_event",
                abs_path,
                plate or "",          # plate_raw: permite calcular sem_placa_motivo
                job_timeout=120,
            )
        except Exception as _rq_err:
            print(f"[RQ] Falha ao enfileirar job YOLO: {_rq_err}")

    with _conn() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO lpr_events
                    (plate, camera_id, channel_name, camera_ip, confidence, image_path, occurred_at)
                VALUES
                    (%s, %s, %s, %s, %s, %s, %s)
            """, (
                plate,
                camera_id,
                channel_name,
                xml_ip or client_ip,   # usa o IP real da câmera (do XML); fallback: IP do cliente HTTP
                confidence,
                image_path,
                occurred_at
            ))

    return JSONResponse({
        "ok": True,
        "plate": plate,
        "camera_id": camera_id,
        "channel_name": channel_name
    })


# ===========================
# STUBS (para dashboard não dar 404)
# ===========================

@app.get("/api/vehicles/allplates")
def vehicles_allplates():
    """Retorna todos os veículos cadastrados agrupados por placa com suas listas."""
    try:
        with _conn() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT DISTINCT vli.plate, vl.id, vl.name, vl.color
                    FROM vehicle_list_items vli
                    JOIN vehicle_lists vl ON vl.id = vli.list_id
                    ORDER BY vli.plate
                """)
                rows = cur.fetchall()
        
        plates = {}
        for plate, list_id, list_name, color in rows:
            if plate not in plates:
                plates[plate] = []
            plates[plate].append({
                "list_id": list_id,
                "list_name": list_name,
                "color": color
            })
        
        return {"plates": plates, "items": list(plates.keys())}
    except Exception as e:
        return {"plates": {}, "items": [], "error": str(e)}


# ===== VEÍCULOS E LISTAS =====
@app.get("/api/vehicles/lists")
def vehicles_lists():
    """Retorna lista de todas as listas com contagem de veículos."""
    try:
        with _conn() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT vl.id, vl.name, vl.description, vl.color, vl.alarm_enabled, 
                           vl.alarm_sound, vl.created_at, vl.updated_at,
                           COUNT(vli.id) as vehicle_count
                    FROM vehicle_lists vl
                    LEFT JOIN vehicle_list_items vli ON vli.list_id = vl.id
                    GROUP BY vl.id
                    ORDER BY vl.updated_at DESC
                """)
                rows = cur.fetchall()
        
        items = []
        for r in rows:
            items.append({
                "id": r[0],
                "name": r[1],
                "description": r[2],
                "color": r[3],
                "alarm_enabled": r[4],
                "alarm_sound": r[5],
                "created_at": r[6].isoformat() if r[6] else None,
                "updated_at": r[7].isoformat() if r[7] else None,
                "vehicle_count": int(r[8] or 0)
            })
        return {"items": items}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/vehicles/lists")
async def vehicles_lists_create(request: Request):
    """Cria uma nova lista de monitoramento."""
    try:
        data = await request.json()
        name = (data.get("name") or "").strip()
        description = (data.get("description") or "").strip()
        color = data.get("color") or "#000000"
        alarm_enabled = data.get("alarm_enabled", False)
        alarm_sound = data.get("alarm_sound")
        
        if not name:
            raise HTTPException(status_code=400, detail="name é obrigatório e não pode ser vazio")
        
        with _conn() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    INSERT INTO vehicle_lists (name, description, color, alarm_enabled, alarm_sound)
                    VALUES (%s, %s, %s, %s, %s)
                    RETURNING id, created_at, updated_at
                """, (name, description if description else None, color, alarm_enabled, alarm_sound))
                r = cur.fetchone()
        
        return {
            "id": r[0],
            "name": name,
            "description": description if description else None,
            "color": color,
            "alarm_enabled": alarm_enabled,
            "alarm_sound": alarm_sound,
            "created_at": r[1].isoformat() if r[1] else None,
            "updated_at": r[2].isoformat() if r[2] else None,
            "vehicle_count": 0
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.put("/api/vehicles/lists/{list_id}")
async def vehicles_lists_update(list_id: int, request: Request):
    """Edita uma lista de monitoramento."""
    try:
        data = await request.json()
        name = (data.get("name") or "").strip()
        description = (data.get("description") or "").strip()
        color = data.get("color") or "#000000"
        alarm_enabled = data.get("alarm_enabled", False)
        alarm_sound = data.get("alarm_sound")
        
        if not name:
            raise HTTPException(status_code=400, detail="name é obrigatório e não pode ser vazio")
        
        with _conn() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT id FROM vehicle_lists WHERE id = %s", (list_id,))
                if not cur.fetchone():
                    raise HTTPException(status_code=404, detail="Lista não encontrada")
                
                cur.execute("""
                    UPDATE vehicle_lists
                    SET name = %s, description = %s, color = %s, alarm_enabled = %s, 
                        alarm_sound = %s, updated_at = NOW()
                    WHERE id = %s
                    RETURNING id, name, description, color, alarm_enabled, alarm_sound, created_at, updated_at
                """, (name, description if description else None, color, alarm_enabled, 
                      alarm_sound, list_id))
                r = cur.fetchone()
                if not r:
                    raise HTTPException(status_code=404, detail="Lista não encontrada")
        
        return {
            "id": r[0],
            "name": r[1],
            "description": r[2],
            "color": r[3],
            "alarm_enabled": r[4],
            "alarm_sound": r[5],
            "created_at": r[6].isoformat() if r[6] else None,
            "updated_at": r[7].isoformat() if r[7] else None,
            "vehicle_count": 0
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.delete("/api/vehicles/lists/{list_id}")
def vehicles_lists_delete(list_id: int):
    """Deleta uma lista e todos seus veículos."""
    try:
        with _conn() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT id FROM vehicle_lists WHERE id = %s", (list_id,))
                if not cur.fetchone():
                    raise HTTPException(status_code=404, detail="Lista não encontrada")
                
                cur.execute("DELETE FROM vehicle_lists WHERE id = %s", (list_id,))
        
        return {"ok": True}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/vehicles")
def vehicles_query(list_id: int | None = None, plate: str | None = None):
    """Lista veículos com filtros opcionais."""
    try:
        query = """
            SELECT vli.id, vli.plate, vli.list_id, vl.name as list_name, vl.color as list_color, 
                   vli.notes, vli.created_at
            FROM vehicle_list_items vli
            JOIN vehicle_lists vl ON vl.id = vli.list_id
            WHERE 1=1
        """
        params = []
        
        if list_id is not None:
            query += " AND vli.list_id = %s"
            params.append(int(list_id))
        
        if plate and plate.strip():
            query += " AND vli.plate ILIKE %s"
            params.append(f"%{plate.strip()}%")
        
        query += " ORDER BY vli.created_at DESC LIMIT 1000"
        
        with _conn() as conn:
            with conn.cursor() as cur:
                cur.execute(query, params)
                rows = cur.fetchall()
        
        items = []
        for r in rows:
            items.append({
                "id": r[0],
                "plate": r[1],
                "list_id": r[2],
                "list_name": r[3],
                "list_color": r[4],
                "notes": r[5],
                "created_at": r[6].isoformat() if r[6] else None
            })
        
        return {"items": items, "total": len(items)}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/vehicles")
async def vehicles_create(request: Request):
    """Adiciona um veículo a uma lista."""
    try:
        data = await request.json()
        
        # Extrair e limpar cada campo individualmente com segurança
        plate_raw = data.get("plate")
        if plate_raw is None or plate_raw == "":
            raise HTTPException(status_code=400, detail="plate é obrigatório")
        plate = str(plate_raw).strip().upper()
        if not plate:
            raise HTTPException(status_code=400, detail="plate não pode ser vazio")
        
        list_id = data.get("list_id")
        if list_id is None:
            raise HTTPException(status_code=400, detail="list_id é obrigatório")
        # Converter para int se necessário
        if isinstance(list_id, str):
            try:
                list_id = int(list_id)
            except (ValueError, TypeError):
                raise HTTPException(status_code=400, detail="list_id deve ser um número")
        elif not isinstance(list_id, int):
            raise HTTPException(status_code=400, detail="list_id deve ser um número")
        
        notes_raw = data.get("notes")
        notes = None
        if notes_raw:
            notes = str(notes_raw).strip()
            if not notes:
                notes = None
        
        with _conn() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT id FROM vehicle_lists WHERE id = %s", (list_id,))
                if not cur.fetchone():
                    raise HTTPException(status_code=404, detail="Lista não encontrada")
                
                try:
                    cur.execute("""
                        INSERT INTO vehicle_list_items (list_id, plate, notes)
                        VALUES (%s, %s, %s)
                        RETURNING id, created_at
                    """, (list_id, plate, notes))
                    r = cur.fetchone()
                except psycopg2.IntegrityError:
                    conn.rollback()
                    raise HTTPException(status_code=409, detail="Placa já existe nesta lista")
        
        return {
            "id": r[0],
            "plate": plate,
            "list_id": list_id,
            "notes": notes,
            "created_at": r[1].isoformat() if r[1] else None
        }
    except HTTPException:
        raise
    except Exception as e:
        import traceback
        tb = traceback.format_exc()
        raise HTTPException(status_code=500, detail=f"Erro: {str(e)}. Traceback: {tb}")


@app.delete("/api/vehicles/{vid}")
def vehicles_delete(vid: int):
    """Remove um veículo de uma lista."""
    try:
        with _conn() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT id FROM vehicle_list_items WHERE id = %s", (vid,))
                if not cur.fetchone():
                    raise HTTPException(status_code=404, detail="Veículo não encontrado")
                
                cur.execute("DELETE FROM vehicle_list_items WHERE id = %s", (vid,))
        
        return {"ok": True}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/alvos")
def alvos_list():
    return {"items": []}


@app.post("/api/alvos")
async def alvos_create():
    return {"ok": True}


@app.delete("/api/alvos/{aid}")
def alvos_delete(aid: str):
    return {"ok": True}


@app.get("/api/alvos/recentes")
def alvos_recent():
    return {"items": []}


@app.get("/api/batedor/plate/{plate}")
def batedor_plate(plate: str, window_minutes: str = "180", limit: int = 200):
    """Retorna todos os eventos de uma placa dentro da janela de tempo."""
    limit = max(1, min(1000, int(limit)))
    wm = _parse_window_to_minutes(window_minutes)
    with _conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT e.id, e.plate, e.camera_id, e.channel_name, e.camera_ip, e.confidence,
                       e.image_path, COALESCE(e.occurred_at, e.ts) AS ts, c.direcao, c.nome AS cam_nome
                FROM lpr_events e
                LEFT JOIN cameras c ON c.id = (
                    SELECT id FROM cameras
                    WHERE camera_id = e.camera_id OR ip = e.camera_ip
                    ORDER BY (camera_id = e.camera_id) DESC
                    LIMIT 1
                )
                WHERE e.plate = %s
                  AND COALESCE(e.occurred_at, e.ts) >= NOW() - (%s * INTERVAL '1 minute')
                ORDER BY COALESCE(e.occurred_at, e.ts) DESC
                LIMIT %s
                """,
                (plate, wm, limit),
            )
            rows = cur.fetchall()
    items = []
    for r in rows:
        items.append({
            "id":           r[0],
            "plate":        r[1],
            "camera_id":    r[2],
            "channel_name": r[3],
            "camera_ip":    r[4],
            "confidence":   float(r[5] or 0.0),
            "image_path":   r[6],
            "occurred_at":  r[7].isoformat() if r[7] else None,
            "ts":           r[7].isoformat() if r[7] else None,
            "direcao":      r[8] or None,
            "cam_nome":     r[9] or None,
        })
    return {"items": items}


@app.get("/api/batedor/companions/{plate}")
def batedor_companions(plate: str):
    return {"items": []}


# ===========================
# BATEDOR — ENDPOINTS REAIS
# ===========================

def _parse_window_to_minutes(w: str) -> int:
    """Converte '2h', '24h', '7d', '90d' em minutos."""
    w = str(w).strip().lower()
    try:
        if w.endswith("d"):
            return int(w[:-1]) * 1440
        elif w.endswith("h"):
            return int(w[:-1]) * 60
        return int(w)
    except Exception:
        return 120


@app.get("/api/batedor/suspects")
def batedor_suspects(
    window_minutes: int = 180,
    min_passes: int = 3,
    min_cameras: int = 2,
    limit: int = 50,
    ts_from: str | None = None,
    ts_to: str | None = None,
):
    """Placas vistas muitas vezes em múltiplas câmeras na janela de tempo."""
    limit = max(1, min(500, int(limit)))
    extra: list[str] = [
        "plate IS NOT NULL",
        "plate != ''",
        "plate NOT IN ('unknown','UNKNOWN')",
    ]
    vals: list[Any] = []

    if ts_from and ts_to:
        f = _parse_dt(ts_from)
        t = _parse_dt(ts_to)
        if f:
            extra.append("COALESCE(occurred_at, ts) >= %s"); vals.append(f)
        if t:
            extra.append("COALESCE(occurred_at, ts) <= %s"); vals.append(t)
    else:
        extra.append(
            "COALESCE(occurred_at, ts) >= NOW() - INTERVAL '%d minutes'" % int(window_minutes)
        )

    wsql = " AND ".join(extra)
    vals += [int(min_passes), int(min_cameras), limit]

    with _conn() as conn:
        with conn.cursor() as cur:
            cur.execute(f"""
                SELECT
                    plate,
                    COUNT(*)                         AS passes,
                    COUNT(DISTINCT camera_id)        AS cameras,
                    MIN(COALESCE(occurred_at, ts))   AS first_seen,
                    MAX(COALESCE(occurred_at, ts))   AS last_seen
                FROM lpr_events
                WHERE {wsql}
                GROUP BY plate
                HAVING COUNT(*) >= %s AND COUNT(DISTINCT camera_id) >= %s
                ORDER BY COUNT(DISTINCT camera_id) DESC, COUNT(*) DESC
                LIMIT %s
            """, tuple(vals))
            rows = cur.fetchall()

    items = []
    for r in rows:
        passes  = int(r[1])
        cameras = int(r[2])
        score   = cameras * 10 + passes * 2
        items.append({
            "plate":      r[0],
            "score":      score,
            "passes":     passes,
            "cameras":    cameras,
            "first_seen": r[3].isoformat() if r[3] else None,
            "last_seen":  r[4].isoformat() if r[4] else None,
        })
    return {"items": items}


@app.get("/api/batedor/convoys")
def batedor_convoys(
    window: str = "2h",
    min_transitions: int = 2,
    dt_min: int = 40,
    dt_max: int = 180,
    type: str = "all",
    limit: int = 50,
    ts_from: str | None = None,
    ts_to: str | None = None,
):
    """Placas que transitam entre câmeras dentro do intervalo de tempo esperado (reconhecimento/escolta)."""
    import json as _json
    limit      = max(1, min(200, int(limit)))
    min_tr     = max(1, int(min_transitions))
    dt_min_s   = max(1, int(dt_min))
    dt_max_s   = max(dt_min_s + 1, int(dt_max))
    window_min = _parse_window_to_minutes(window)

    if ts_from and ts_to:
        t_from = _parse_dt(ts_from) or (_utcnow() - timedelta(minutes=window_min))
        t_to   = _parse_dt(ts_to)   or _utcnow()
    else:
        t_to   = _utcnow()
        t_from = t_to - timedelta(minutes=window_min)

    with _conn() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT
                    a.plate,
                    a.camera_id                                                           AS cam_a,
                    b.camera_id                                                           AS cam_b,
                    EXTRACT(EPOCH FROM (
                        COALESCE(b.occurred_at, b.ts) - COALESCE(a.occurred_at, a.ts)
                    ))::int                                                               AS delta_t,
                    COALESCE(a.occurred_at, a.ts)                                         AS ts_a,
                    COALESCE(b.occurred_at, b.ts)                                         AS ts_b,
                    a.image_path                                                          AS img_a,
                    b.image_path                                                          AS img_b
                FROM lpr_events a
                JOIN lpr_events b
                    ON  a.plate      = b.plate
                    AND a.camera_id != b.camera_id
                    AND COALESCE(b.occurred_at, b.ts) > COALESCE(a.occurred_at, a.ts)
                    AND EXTRACT(EPOCH FROM (
                            COALESCE(b.occurred_at, b.ts) - COALESCE(a.occurred_at, a.ts)
                        )) BETWEEN %s AND %s
                WHERE a.plate IS NOT NULL
                  AND a.plate NOT IN ('', 'unknown', 'UNKNOWN')
                  AND COALESCE(a.occurred_at, a.ts) BETWEEN %s AND %s
                ORDER BY a.plate, COALESCE(a.occurred_at, a.ts)
                LIMIT 5000
            """, (dt_min_s, dt_max_s, t_from, t_to))
            rows = cur.fetchall()

    from collections import defaultdict
    plate_data: dict[str, Any] = defaultdict(lambda: {
        "transitions": 0,
        "deltas": [],
        "first_seen": None,
        "last_seen": None,
        "evidence": [],
    })

    for r in rows:
        plate, cam_a, cam_b, delta_t, ts_a, ts_b, img_a, img_b = r
        pd = plate_data[plate]
        pd["transitions"] += 1
        pd["deltas"].append(int(delta_t))
        ts_a_iso = ts_a.isoformat() if ts_a else None
        ts_b_iso = ts_b.isoformat() if ts_b else None
        if not pd["first_seen"] or (ts_a_iso and ts_a_iso < pd["first_seen"]):
            pd["first_seen"] = ts_a_iso
        if not pd["last_seen"] or (ts_b_iso and ts_b_iso > pd["last_seen"]):
            pd["last_seen"] = ts_b_iso
        pd["evidence"].append({
            "cam_a":    cam_a,
            "cam_b":    cam_b,
            "delta_t":  int(delta_t),
            "ts_a":     ts_a_iso,
            "ts_b":     ts_b_iso,
            "img_a":    img_a,
            "img_b":    img_b,
            "yolo_vc_a": -1,
            "yolo_vc_b": -1,
        })

    # Contagem YOLO de multi-veículos por placa (dentro da mesma janela de tempo)
    yolo_multi_by_plate: dict = {}
    active_plates = list(plate_data.keys())
    if active_plates:
        try:
            with _conn() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        SELECT plate, COUNT(*)
                        FROM lpr_events
                        WHERE plate = ANY(%s)
                          AND yolo_result IS NOT NULL
                          AND (yolo_result->>'vehicle_count')::int > 1
                          AND COALESCE(occurred_at, ts) BETWEEN %s AND %s
                        GROUP BY plate
                        """,
                        (active_plates, t_from, t_to)
                    )
                    for pr in cur.fetchall():
                        yolo_multi_by_plate[pr[0]] = int(pr[1])
        except Exception:
            pass

    # Tipo de veículo dominante por placa (agregado do yolo_result)
    _TIPO_PT = {"car": "Carro", "truck": "Caminhão", "motorcycle": "Moto",
                "bus": "Ônibus", "van": "Van", "bicycle": "Bicicleta"}
    dominant_type_by_plate: dict = {}
    if active_plates:
        try:
            with _conn() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        SELECT plate, yolo_result->'vehicle_types'
                        FROM lpr_events
                        WHERE plate = ANY(%s)
                          AND yolo_result IS NOT NULL
                          AND COALESCE(occurred_at, ts) BETWEEN %s AND %s
                        """,
                        (active_plates, t_from, t_to)
                    )
                    type_counts_conv: dict = {}
                    for row in cur.fetchall():
                        vt = row[1]
                        if vt and isinstance(vt, dict):
                            tc = type_counts_conv.setdefault(row[0], {})
                            for k, v in vt.items():
                                tc[k] = tc.get(k, 0) + int(v)
            for pl, counts in type_counts_conv.items():
                best = max(counts, key=counts.get)
                dominant_type_by_plate[pl] = _TIPO_PT.get(best, best.capitalize())
        except Exception:
            pass

    # ── Resolve direção dominante por placa cruzando câmeras com tabela cameras ──
    all_cam_ids = list({ev["cam_a"] for pd in plate_data.values() for ev in pd["evidence"]} |
                       {ev["cam_b"] for pd in plate_data.values() for ev in pd["evidence"]})
    cam_dir_map: dict = {}
    if all_cam_ids:
        try:
            with _conn() as conn:
                with conn.cursor() as cur:
                    cur.execute("SELECT camera_id, ip, direcao FROM cameras WHERE direcao IS NOT NULL")
                    for row in cur.fetchall():
                        if row[2]:
                            cam_dir_map[row[0]] = row[2]  # por camera_id
                            if row[1]:
                                cam_dir_map[row[1].strip()] = row[2]  # por IP
        except Exception:
            pass

    def _dom_dir_convoys(pd_ev):
        nc, nd = 0, 0
        for ev in pd_ev:
            for cid in (ev.get("cam_a"), ev.get("cam_b")):
                d = cam_dir_map.get(cid)
                if d == "CRESCENTE": nc += 1
                elif d == "DECRESCENTE": nd += 1
        if nc == 0 and nd == 0: return None
        return "CRESCENTE" if nc >= nd else "DECRESCENTE"

    items = []
    for plate, pd in plate_data.items():
        if pd["transitions"] < min_tr:
            continue
        avg_delta = int(sum(pd["deltas"]) / len(pd["deltas"])) if pd["deltas"] else 0
        score     = pd["transitions"] * 5 + max(0, 30 - avg_delta // 10)
        items.append({
            "plate":             plate,
            "score":             score,
            "valid_transitions": pd["transitions"],
            "avg_delta_t_sec":   avg_delta,
            "dominant_direcao":  _dom_dir_convoys(pd["evidence"]),
            "dominant_type":     dominant_type_by_plate.get(plate),
            "yolo_multi_events": yolo_multi_by_plate.get(plate, 0),
            "first_seen":        pd["first_seen"],
            "last_seen":         pd["last_seen"],
            "evidence":          pd["evidence"][:10],
        })

    items.sort(key=lambda x: x["score"], reverse=True)
    return {"items": items[:limit]}


@app.get("/api/batedor/groups")
def batedor_groups(
    window: str = "2h",
    min_shared: int = 1,
    co_window: int = 120,
    limit: int = 50,
    ts_from: str | None = None,
    ts_to: str | None = None,
):
    """Pares de placas DIFERENTES vistas na mesma câmera com menos de co_window segundos de diferença."""
    limit      = max(1, min(200, int(limit)))
    min_sh     = max(1, int(min_shared))
    co_win_s   = max(10, int(co_window))
    window_min = _parse_window_to_minutes(window)

    if ts_from and ts_to:
        t_from = _parse_dt(ts_from) or (_utcnow() - timedelta(minutes=window_min))
        t_to   = _parse_dt(ts_to)   or _utcnow()
    else:
        t_to   = _utcnow()
        t_from = t_to - timedelta(minutes=window_min)

    with _conn() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT
                    LEAST(a.plate, b.plate)        AS plate_a,
                    GREATEST(a.plate, b.plate)     AS plate_b,
                    a.camera_id                    AS camera_id,
                    COALESCE(a.occurred_at, a.ts)  AS ts_a,
                    COALESCE(b.occurred_at, b.ts)  AS ts_b,
                    ABS(EXTRACT(EPOCH FROM (
                        COALESCE(b.occurred_at, b.ts) - COALESCE(a.occurred_at, a.ts)
                    )))::int                        AS co_delta,
                    a.image_path                   AS img_a,
                    b.image_path                   AS img_b
                FROM lpr_events a
                JOIN lpr_events b
                    ON  a.camera_id = b.camera_id
                    AND a.plate     < b.plate
                    AND a.id       != b.id
                    AND ABS(EXTRACT(EPOCH FROM (
                            COALESCE(b.occurred_at, b.ts) - COALESCE(a.occurred_at, a.ts)
                        ))) <= %s
                WHERE a.plate IS NOT NULL AND b.plate IS NOT NULL
                  AND a.plate NOT IN ('', 'unknown', 'UNKNOWN')
                  AND b.plate NOT IN ('', 'unknown', 'UNKNOWN')
                  AND COALESCE(a.occurred_at, a.ts) BETWEEN %s AND %s
                ORDER BY plate_a, plate_b
                LIMIT 5000
            """, (co_win_s, t_from, t_to))
            pair_rows = cur.fetchall()

    from collections import defaultdict
    pair_data: dict[tuple, Any] = defaultdict(lambda: {
        "cameras": set(),
        "co_deltas": [],
        "first_seen": None,
        "last_seen": None,
        "evidence": [],
    })

    for r in pair_rows:
        plate_a, plate_b, camera_id, ts_a, ts_b, co_delta, img_a, img_b = r
        pd = pair_data[(plate_a, plate_b)]
        pd["cameras"].add(camera_id)
        pd["co_deltas"].append(int(co_delta))
        ts_a_iso = ts_a.isoformat() if ts_a else None
        ts_b_iso = ts_b.isoformat() if ts_b else None
        if not pd["first_seen"] or (ts_a_iso and ts_a_iso < pd["first_seen"]):
            pd["first_seen"] = ts_a_iso
        if not pd["last_seen"] or (ts_b_iso and ts_b_iso > pd["last_seen"]):
            pd["last_seen"] = ts_b_iso
        pd["evidence"].append({
            "camera_id": camera_id,
            "ts_a":      ts_a_iso,
            "ts_b":      ts_b_iso,
            "co_delta":  int(co_delta),
            "img_a":     img_a,
            "img_b":     img_b,
        })

    # Contagem YOLO de multi-veículos por par de placas (dentro da mesma janela)
    yolo_multi_by_pair: dict = {}
    active_pairs = list(pair_data.keys())
    if active_pairs:
        try:
            all_plates = list({pl for pair in active_pairs for pl in pair})
            with _conn() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        SELECT plate, COUNT(*)
                        FROM lpr_events
                        WHERE plate = ANY(%s)
                          AND yolo_result IS NOT NULL
                          AND (yolo_result->>'vehicle_count')::int > 1
                          AND COALESCE(occurred_at, ts) BETWEEN %s AND %s
                        GROUP BY plate
                        """,
                        (all_plates, t_from, t_to)
                    )
                    per_plate = {r[0]: int(r[1]) for r in cur.fetchall()}
            for pa, pb in active_pairs:
                yolo_multi_by_pair[(pa, pb)] = per_plate.get(pa, 0) + per_plate.get(pb, 0)
        except Exception:
            pass

    # Tipo de veículo dominante por par (agregado do yolo_result)
    _TIPO_PT_GRP = {"car": "Carro", "truck": "Caminhão", "motorcycle": "Moto",
                    "bus": "Ônibus", "van": "Van", "bicycle": "Bicicleta"}
    dominant_type_by_pair: dict = {}
    if active_pairs:
        try:
            all_pl_grp = list({pl for pair in active_pairs for pl in pair})
            with _conn() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        SELECT plate, yolo_result->'vehicle_types'
                        FROM lpr_events
                        WHERE plate = ANY(%s)
                          AND yolo_result IS NOT NULL
                          AND COALESCE(occurred_at, ts) BETWEEN %s AND %s
                        """,
                        (all_pl_grp, t_from, t_to)
                    )
                    type_counts_grp: dict = {}
                    for row in cur.fetchall():
                        vt = row[1]
                        if vt and isinstance(vt, dict):
                            tc = type_counts_grp.setdefault(row[0], {})
                            for k, v in vt.items():
                                tc[k] = tc.get(k, 0) + int(v)
            for pa, pb in active_pairs:
                merged: dict = {}
                for pl in (pa, pb):
                    for k, v in type_counts_grp.get(pl, {}).items():
                        merged[k] = merged.get(k, 0) + v
                if merged:
                    best = max(merged, key=merged.get)
                    dominant_type_by_pair[(pa, pb)] = _TIPO_PT_GRP.get(best, best.capitalize())
        except Exception:
            pass

    # ── Resolve direção dominante por par cruzando câmeras com tabela cameras ──
    all_cam_ids_grp = list({ev["camera_id"] for pd in pair_data.values() for ev in pd["evidence"]})
    cam_dir_map_grp: dict = {}
    if all_cam_ids_grp:
        try:
            with _conn() as conn:
                with conn.cursor() as cur:
                    cur.execute("SELECT camera_id, ip, direcao FROM cameras WHERE direcao IS NOT NULL")
                    for row in cur.fetchall():
                        if row[2]:
                            cam_dir_map_grp[row[0]] = row[2]  # por camera_id
                            if row[1]:
                                cam_dir_map_grp[row[1].strip()] = row[2]  # por IP
        except Exception:
            pass

    def _dom_dir_groups(cameras_set):
        nc, nd = 0, 0
        for cid in cameras_set:
            d = cam_dir_map_grp.get(cid)
            if d == "CRESCENTE": nc += 1
            elif d == "DECRESCENTE": nd += 1
        if nc == 0 and nd == 0: return None
        return "CRESCENTE" if nc >= nd else "DECRESCENTE"

    items = []
    for (plate_a, plate_b), pd in pair_data.items():
        cameras_together = len(pd["cameras"])
        if cameras_together < min_sh:
            continue
        avg_co = int(sum(pd["co_deltas"]) / len(pd["co_deltas"])) if pd["co_deltas"] else 0
        score  = cameras_together * 10 + len(pd["co_deltas"]) * 2
        items.append({
            "plate_a":          plate_a,
            "plate_b":          plate_b,
            "score":            score,
            "cameras_together": cameras_together,
            "avg_co_delta_sec": avg_co,
            "yolo_multi_count": yolo_multi_by_pair.get((plate_a, plate_b), 0),
            "dominant_direcao": _dom_dir_groups(pd["cameras"]),
            "dominant_type":    dominant_type_by_pair.get((plate_a, plate_b)),
            "first_seen":       pd["first_seen"],
            "last_seen":        pd["last_seen"],
            "evidence":         pd["evidence"][:20],
        })

    items.sort(key=lambda x: x["score"], reverse=True)
    return {"items": items[:limit]}


# ===========================
# FIX: endpoint de thumbnail ✅ (sem 404 quando houver imagem)
# ===========================

@app.get("/api/events/{event_id}/thumbnail")
def api_event_thumbnail(event_id: int, w: int = 144, h: int = 96):
    event = get_event_by_id(event_id)
    if not event:
        raise HTTPException(status_code=404, detail="Evento não encontrado")

    thumb = event.get("thumb") or event.get("image") or event.get("image_path")
    if not thumb:
        raise HTTPException(status_code=404, detail="Imagem não disponível para este evento")

    return RedirectResponse(url=thumb, status_code=302)