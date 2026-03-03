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
from typing import Any, Optional

import psycopg2
import psycopg2.pool
from fastapi import FastAPI, Request, HTTPException, BackgroundTasks
from fastapi.responses import JSONResponse, FileResponse, PlainTextResponse
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

from cleanup_background import start_cleanup_background, stop_cleanup_background

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
_PUBLIC_PREFIXES = ("/api/health", "/static", "/uploads", "/login", "/api/webhook", "/api/simple-webhook", "/api/ingest", "/api/catchall", "/catchall")
_PUBLIC_EXACT    = {"/", "/dashboard", "/favicon.ico", "/api/auth/login",
                    "/docs", "/redoc", "/openapi.json"}

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
            cur.execute("ALTER TABLE cameras ADD COLUMN IF NOT EXISTS modo_integracao TEXT DEFAULT NULL;")
            cur.execute("ALTER TABLE cameras ADD COLUMN IF NOT EXISTS usuario TEXT DEFAULT NULL;")
            cur.execute("ALTER TABLE cameras ADD COLUMN IF NOT EXISTS senha TEXT DEFAULT NULL;")

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
            cur.execute("ALTER TABLE lpr_events ADD COLUMN IF NOT EXISTS cam_meta JSONB;")
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
            # Credenciais lidas do ambiente (defina ADMIN_USER e ADMIN_PASSWORD no .env)
            _seed_user = os.getenv("ADMIN_USER", "admin")
            _seed_pass = os.getenv("ADMIN_PASSWORD", "admin123")
            cur.execute("SELECT id FROM users WHERE username=%s LIMIT 1", (_seed_user,))
            if not cur.fetchone():
                cur.execute(
                    "INSERT INTO users (username, password_hash, full_name, role) VALUES (%s, %s, %s, %s)",
                    (_seed_user, _hash_pw(_seed_pass), "Administrador", "admin")
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

            # Alvos Rastreados
            cur.execute("""
                CREATE TABLE IF NOT EXISTS alvos (
                    id SERIAL PRIMARY KEY,
                    plate TEXT NOT NULL UNIQUE,
                    descricao TEXT,
                    created_at TIMESTAMPTZ DEFAULT NOW()
                );
            """)
            cur.execute("ALTER TABLE alvos ADD COLUMN IF NOT EXISTS list_id INTEGER REFERENCES vehicle_lists(id) ON DELETE SET NULL;")

            # Eventos LPR — campo direcao derivado da câmera
            cur.execute("ALTER TABLE lpr_events ADD COLUMN IF NOT EXISTS direcao TEXT DEFAULT NULL;")

            # Migração: preenche direcao nos eventos históricos que ainda têm NULL
            # (usa a câmera cadastrada para o camera_id ou camera_ip do evento)
            cur.execute("""
                UPDATE lpr_events e
                SET direcao = c.direcao
                FROM cameras c
                WHERE e.direcao IS NULL
                  AND c.direcao IS NOT NULL
                  AND (c.camera_id = e.camera_id OR c.ip = e.camera_id OR c.ip = e.camera_ip)
            """)

            # Decisões operacionais sobre relatórios de veículos
            cur.execute("""
                CREATE TABLE IF NOT EXISTS vehicle_report_decisions (
                    id SERIAL PRIMARY KEY,
                    plate TEXT NOT NULL,
                    score_total INTEGER NOT NULL DEFAULT 0,
                    level TEXT NOT NULL DEFAULT 'normal',
                    badges JSONB DEFAULT '[]',
                    sinais_principais JSONB DEFAULT '{}',
                    decision TEXT NOT NULL,
                    decision_note TEXT,
                    operator TEXT NOT NULL DEFAULT '',
                    report_window TEXT NOT NULL DEFAULT '2h',
                    created_at TIMESTAMPTZ DEFAULT NOW()
                );
            """)
            cur.execute("CREATE INDEX IF NOT EXISTS idx_vrd_plate ON vehicle_report_decisions(plate);")
            cur.execute("CREATE INDEX IF NOT EXISTS idx_vrd_created ON vehicle_report_decisions(created_at);")


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
                "SELECT id, camera_id, nome, ativa, criticidade, peso, created_at, ip, direcao, latitude, longitude, usuario, senha, modo_integracao FROM cameras WHERE camera_id=%s OR ip=%s LIMIT 1",
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
                "usuario": row[11] or None,
                "modo_integracao": row[13] or "push",
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


def _lookup_camera_by_channel(channel_name: str) -> dict | None:
    """
    Fallback: busca câmera pelo channelName do XML contra camera_id ou nome no banco.
    Útil quando o IP enviado no XML não está cadastrado mas o nome do canal casa.
    Compara de forma case-insensitive e ignora espaços/hífens/sublinhados extras.
    """
    if not channel_name:
        return None
    # normaliza: minúsculas, substitui separadores por espaço
    import re as _re
    def _norm(s: str) -> str:
        return _re.sub(r'[\s_\-]+', ' ', s.lower()).strip()
    needle = _norm(channel_name)
    try:
        with _conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT id, camera_id, nome, ativa, criticidade, peso, created_at, ip, direcao, latitude, longitude FROM cameras WHERE ativa = TRUE"
                )
                rows = cur.fetchall()
        for row in rows:
            cam_id_norm  = _norm(row[1] or "")
            cam_nome_norm = _norm(row[2] or "")
            if needle in cam_id_norm or cam_id_norm in needle or \
               needle in cam_nome_norm or cam_nome_norm in needle:
                return {
                    "id": row[0], "camera_id": row[1], "nome": row[2],
                    "ativa": row[3], "criticidade": (row[4] or "NORMAL").upper(),
                    "peso": float(row[5] or 1.0), "peso_score": float(row[5] or 1.0),
                    "ip": row[7], "direcao": row[8] or None,
                    "latitude":  float(row[9])  if row[9]  is not None else None,
                    "longitude": float(row[10]) if row[10] is not None else None,
                }
    except Exception as e:
        print(f"[CAMERA] _lookup_camera_by_channel erro: {e}")
    return None


def _derive_direcao(cam_direcao: str | None, xml_direction: str | None) -> str | None:
    """
    Deriva a direção absoluta do veículo combinando:
      cam_direcao  : direção configurada na câmera (CRESCENTE / DECRESCENTE)
      xml_direction: direção detectada no evento    (forward  / reverse)

    Lógica:
      CRESCENTE  + forward → CRESCENTE      (veículo vai no sentido crescente)
      CRESCENTE  + reverse → DECRESCENTE    (veículo vai contra o sentido crescente)
      DECRESCENTE + forward → DECRESCENTE   (veículo vai no sentido decrescente)
      DECRESCENTE + reverse → CRESCENTE     (veículo vai contra o sentido decrescente)

    Se um dos valores estiver ausente, retorna cam_direcao como fallback.
    """
    if not cam_direcao:
        return None
    if not xml_direction:
        return cam_direcao
    cd = cam_direcao.upper()
    xd = xml_direction.lower()
    if cd == "CRESCENTE":
        return "CRESCENTE" if xd == "forward" else "DECRESCENTE"
    if cd == "DECRESCENTE":
        return "DECRESCENTE" if xd == "forward" else "CRESCENTE"
    return cam_direcao


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
    # Inicia worker de limpeza/retencao de dados em background
    start_cleanup_background(_conn)
    try:
        yield
    finally:
        # Sinaliza o worker para encerrar graciosamente no shutdown
        stop_cleanup_background()


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
                       c.direcao, c.latitude, c.longitude, c.modo_integracao, c.usuario
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
            "id":              r[0],
            "camera_id":       r[1],
            "nome":            r[2],
            "ativa":           r[3],
            "criticidade":     (r[4] or "NORMAL").upper(),
            "peso_score":      float(r[5] or 1.0),
            "created_at":      r[6].isoformat() if r[6] else None,
            "ip":              r[7],
            "last_seen":       r[8].isoformat() if r[8] else None,
            "total_events":    int(r[9] or 0),
            "events_today":    int(r[10] or 0),
            "direcao":         r[11] or None,
            "latitude":        float(r[12]) if r[12] is not None else None,
            "longitude":       float(r[13]) if r[13] is not None else None,
            "modo_integracao": r[14] or "push",
            "usuario":         r[15] or None,
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
    ip              = (data.get("ip") or "").strip() or None
    direcao         = (data.get("direcao") or "").strip().upper() or None
    latitude        = float(data["latitude"])  if data.get("latitude")  not in (None, "") else None
    longitude       = float(data["longitude"]) if data.get("longitude") not in (None, "") else None
    modo_integracao = (data.get("modo_integracao") or "push").strip().lower()
    usuario         = (data.get("usuario") or "").strip() or None
    senha           = (data.get("senha") or "").strip() or None

    if modo_integracao not in ("push", "listen"):
        raise HTTPException(status_code=400, detail="modo_integracao deve ser 'push' ou 'listen'")
    if modo_integracao == "listen" and (not usuario or not senha):
        raise HTTPException(status_code=400, detail="usuario e senha são obrigatórios no modo 'listen'")

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
                INSERT INTO cameras (camera_id, nome, ativa, criticidade, peso, peso_score, ip, direcao, latitude, longitude, modo_integracao, usuario, senha)
                VALUES (%s, %s, TRUE, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (camera_id) DO UPDATE SET
                    nome = EXCLUDED.nome,
                    ativa = TRUE,
                    criticidade = EXCLUDED.criticidade,
                    peso = EXCLUDED.peso,
                    peso_score = EXCLUDED.peso_score,
                    ip = COALESCE(EXCLUDED.ip, cameras.ip),
                    direcao = EXCLUDED.direcao,
                    latitude  = COALESCE(EXCLUDED.latitude,  cameras.latitude),
                    longitude = COALESCE(EXCLUDED.longitude, cameras.longitude),
                    modo_integracao = EXCLUDED.modo_integracao,
                    usuario = COALESCE(EXCLUDED.usuario, cameras.usuario),
                    senha   = COALESCE(EXCLUDED.senha,   cameras.senha)
                """,
                (camera_id, nome, criticidade, peso, peso, ip, direcao, latitude, longitude, modo_integracao, usuario, senha),
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
            if "modo_integracao" in data:
                m_val = str(data["modo_integracao"]).strip().lower()
                if m_val not in ("push", "listen"):
                    raise HTTPException(status_code=400, detail="modo_integracao deve ser 'push' ou 'listen'")
                sets.append("modo_integracao=%s"); vals.append(m_val)
            if "usuario" in data:
                sets.append("usuario=%s"); vals.append(str(data["usuario"]).strip() or None)
            if "senha" in data:
                sets.append("senha=%s"); vals.append(str(data["senha"]).strip() or None)
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
                "SELECT id, camera_id, nome, ativa, criticidade, peso, created_at, ip, latitude, longitude, usuario, modo_integracao FROM cameras WHERE id=%s LIMIT 1",
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
        "usuario": row[10] or None,
        "modo_integracao": row[11] or "push",
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
        # camera_id em lpr_events pode ser o IP ou o nome do canal dependendo da origem;
        # camera_ip sempre contém o IP real — verificamos ambas as colunas para garantir o match
        _cid = camera_id.strip()
        where.append("(e.camera_id = %s OR e.camera_ip = %s OR e.camera_id IN (SELECT camera_id FROM cameras WHERE ip = %s))")
        vals.extend([_cid, _cid, _cid])

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
                       c.nome AS cam_nome,
                       COALESCE(NULLIF(e.direcao,''), c.direcao) AS direcao,
                       e.cam_meta
                FROM lpr_events e
                LEFT JOIN cameras c ON c.id = (
                    SELECT id FROM cameras
                    WHERE camera_id = e.camera_id
                       OR ip        = e.camera_id
                       OR ip        = e.camera_ip
                    ORDER BY (camera_id = e.camera_id) DESC
                    LIMIT 1
                )
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
        raw_yolo = r[8]
        if raw_yolo is None:
            yolo = None
        elif isinstance(raw_yolo, dict):
            yolo = raw_yolo
        else:
            yolo = _json_lib.loads(raw_yolo)
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
            "target_vehicle":   yolo.get("target_vehicle")   if yolo else None,
            "image_quality":    yolo.get("image_quality")    if yolo else None,
            "cam_nome": r[9] or r[3],
            "direcao": r[10] or None,
            "cam_meta": (_json_lib.loads(r[11]) if isinstance(r[11], str) else r[11]) if r[11] else None,
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


def _fetch_snapshot_and_enqueue(
    event_id: int,
    cam_ip: str,
    usuario: str,
    senha: str,
    plate: str,
    lpr_meta: dict,
) -> None:
    """
    Busca um snapshot da câmera (ISAPI) e associa ao evento.
    Executado em background após a resposta ao webhook.
    """
    import urllib.request
    import urllib.error

    urls = [
        f"http://{cam_ip}/ISAPI/Streaming/channels/101/picture",
        f"http://{cam_ip}/ISAPI/Streaming/channels/1/picture",
    ]
    img_data = None
    for url in urls:
        try:
            password_mgr = urllib.request.HTTPPasswordMgrWithDefaultRealm()
            password_mgr.add_password(None, url, usuario, senha)
            digest = urllib.request.HTTPDigestAuthHandler(password_mgr)
            basic  = urllib.request.HTTPBasicAuthHandler(password_mgr)
            opener = urllib.request.build_opener(digest, basic)
            with opener.open(url, timeout=5) as resp:
                data = resp.read()
            if len(data) > 5_000:   # imagem real (> 5 KB)
                img_data = data
                break
        except Exception as exc:
            print(f"[SNAPSHOT] {url} → {exc}")

    if not img_data:
        print(f"[SNAPSHOT] sem imagem para evento {event_id} (cam {cam_ip})")
        return

    day   = _utcnow().strftime("%Y-%m-%d")
    d     = UPLOAD_DIR / day
    d.mkdir(parents=True, exist_ok=True)
    fname = f"{uuid.uuid4().hex}.jpg"
    (d / fname).write_bytes(img_data)
    image_path = f"/uploads/{day}/{fname}"

    # Atualiza o evento no banco
    with _conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE lpr_events SET image_path=%s WHERE id=%s",
                (image_path, event_id),
            )

    # Enfileira análise YOLO
    abs_path = f"/app/uploads/{day}/{fname}"
    try:
        _get_rq_queue().enqueue(
            "worker.job_analyze_event",
            abs_path,
            plate or "",
            lpr_meta,
            job_timeout=120,
        )
    except Exception as e:
        print(f"[SNAPSHOT][RQ] {e}")

    print(f"[SNAPSHOT] evento {event_id} | cam {cam_ip} | {image_path}", flush=True)

@app.post("/api/simple-webhook")
async def simple_webhook(request: Request, background_tasks: BackgroundTasks):
    client_ip = _get_client_ip(request)
    content_type = request.headers.get("content-type", "")

    xml_bytes: bytes | None = None
    images: list[tuple[str, bytes]] = []

    if "multipart/form-data" in content_type:
        # ── Formato padrão Hikvision ISAPI / camera-poller ──────────────
        try:
            form = await request.form()
        except ClientDisconnect:
            return JSONResponse({"ok": True})

        for _, v in form.multi_items():
            if isinstance(v, UploadFile):
                data = await v.read()
                if v.filename and v.filename.lower().endswith(".xml"):
                    xml_bytes = data
                elif len(data) >= 10_000:
                    images.append((v.filename or "image.jpg", data))

    else:
        # ── Formato alternativo: câmeras Hikvision HTTP Upload (application/xml, text/xml) ─
        body = await request.body()
        ct_lower = content_type.lower()
        is_xml_ct = any(x in ct_lower for x in ("xml", "text/plain"))
        starts_with_xml = body.lstrip()[:1] == b"<"
        if (is_xml_ct or starts_with_xml) and body:
            xml_bytes = body
            print(f"[WEBHOOK] evento XML direto de {client_ip} ({len(body)} bytes, ct={content_type or 'none'})")
        else:
            # Conteúdo não-XML sem multipart — apenas registra (heartbeat, etc.)
            print(f"[WEBHOOK] body não-XML ignorado de {client_ip} ({len(body)} bytes, ct={content_type})")
            return JSONResponse({"ok": True, "bytes": len(body)})

    plate = "unknown"
    camera_id = None
    xml_ip = None          # IP real da câmera (do XML <ipAddress>)
    channel_name_xml = None
    confidence = 0.0
    occurred_at = None
    xml_direction = None   # direção do veículo reportada pela câmera (forward/reverse)

    if xml_bytes:
        try:
            root = ET.fromstring(xml_bytes)

            def x(tag):
                # Busca namespace-agnostic: suporta hikvision.com, isapi.org e sem namespace
                el = root.find(".//{*}" + tag)
                if el is None:
                    el = root.find(".//" + tag)  # fallback sem namespace
                return el.text.strip() if el is not None and el.text else None

            plate            = x("licensePlate") or "unknown"
            xml_ip           = x("ipAddress")           # IP real: "172.21.151.16"
            channel_name_xml = x("channelName")         # nome do canal: "11_PRAINHA_1_CHACARAS"
            channel_id_xml   = x("channelID")           # fallback: "1"
            xml_direction    = (x("direction") or "").lower() or None   # "forward" ou "reverse"

            # Cor e tipo do veículo já detectados pela câmera (vehicleInfo)
            xml_vehicle_color = x("color")       # ex: "black", "white", "silver"
            xml_vehicle_type  = x("vehicleType") # ex: "truck", "car", "bus"
            xml_plate_color   = x("plateColor")  # ex: "white", "yellow"
            xml_speed         = x("speed")        # velocidade do veículo
            xml_speed_limit   = x("speedLimit")   # limite de velocidade
            xml_illegal_code  = x("illegalCode")
            xml_illegal_name  = x("illegalName")  # ex: "Normal", "Excesso de velocidade"
            xml_plate_chars   = x("plateCharBelieve")  # ex: "99,99,93,99,99,99,99"
            xml_license_bright = x("licenseBright")

            # Coordenadas da placa/veículo no frame
            # Atenção: algumas câmeras Hikvision usam pixels reais (ex: 2688x1552)
            #          outras usam escala normalizada 0-10000
            # Detectamos o sistema pela tag detectionBackgroundImageResolution
            def _rect(parent_tag: str) -> "dict | None":
                try:
                    ns_any = "{*}"
                    el_parent = root.find(f".//{ns_any}{parent_tag}") or root.find(f".//{parent_tag}")
                    if el_parent is None:
                        return None
                    get = lambda t: next(
                        (el.text.strip() for el in el_parent.iter() if el.tag.split("}")[-1] == t and el.text),
                        None
                    )
                    rx, ry, rw, rh = get("X"), get("Y"), get("width"), get("height")
                    if all(v is not None for v in (rx, ry, rw, rh)):
                        return {"x": int(rx), "y": int(ry), "w": int(rw), "h": int(rh)}
                except Exception:
                    pass
                return None

            plate_rect   = _rect("plateRect")   or _rect("PlateRect")
            # Hikvision tem typo em firmware antigo: vehicelRect (sem 'l' depois de 'h')
            vehicle_rect = (_rect("vehicleRect") or _rect("VehicleRect")
                            or _rect("vehicelRect") or _rect("VehicelRect"))

            # Dimensões reais da imagem de detecção (usadas para normalização de coords)
            pic_width  = (x("picWidth")  or x("imageWidth")
                          or x("width")  if False else None)  # placeholder
            pic_height = (x("picHeight") or x("imageHeight")
                          or x("height") if False else None)
            # Tenta detectionBackgroundImageResolution (padrão ISAPI moderno)
            bg_res = root.find(".//{*}detectionBackgroundImageResolution") \
                     or root.find(".//detectionBackgroundImageResolution")
            if bg_res is not None:
                _bw = next((e.text for e in bg_res.iter() if e.tag.split("}")[-1] == "width"  and e.text), None)
                _bh = next((e.text for e in bg_res.iter() if e.tag.split("}")[-1] == "height" and e.text), None)
                if _bw and _bh:
                    pic_width, pic_height = _bw, _bh
            if not pic_width:  pic_width  = x("picWidth")  or x("imageWidth")
            if not pic_height: pic_height = x("picHeight") or x("imageHeight")

            # Sistema de coordenadas: "pixels" se temos dims reais E os rects cabem nelas
            # Câmeras ISAPI modernas enviam pixels; legado usa 0-10000
            coord_type = "normalized"   # padrão
            if pic_width and pic_height and plate_rect:
                pw, ph = int(pic_width), int(pic_height)
                if (plate_rect["x"] + plate_rect["w"]) <= pw * 1.1:
                    coord_type = "pixels"

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

    # Fallback: usa header X-Camera-IP enviado pelo camera-poller (modo listen)
    if not camera_id:
        header_ip = request.headers.get("X-Camera-IP", "").strip()
        if header_ip:
            camera_id = header_ip
            xml_ip    = xml_ip or header_ip
            print(f"[INGEST] camera_id resolvido via X-Camera-IP: {camera_id}")
        else:
            print(f"[INGEST] evento sem camera_id ignorado (ip cliente={client_ip})")
            return JSONResponse({"ok": False, "detail": "camera não identificada no XML"}, status_code=400)

    channel_name = None
    if camera_id:
        # nome padrão = channelName do XML; fallback = próprio camera_id
        default_nome = channel_name_xml or camera_id
        cam = ensure_camera_exists(camera_id, default_name=default_nome, ip=xml_ip)

        # Fallback: câmera não encontrada por IP — tenta pelo channelName do XML
        if not cam.get("id") and channel_name_xml:
            cam = _lookup_camera_by_channel(channel_name_xml) or cam

        # Rejeita evento se câmera não estiver cadastrada no banco
        if not cam.get("id"):
            print(f"[INGEST] câmera não cadastrada ignorada: camera_id={camera_id} ip={xml_ip} channel={channel_name_xml}")
            return JSONResponse({"ok": False, "detail": f"câmera '{camera_id}' não cadastrada"}, status_code=403)

        # Usa sempre o camera_id canônico do banco (não o IP bruto do XML)
        camera_id    = cam.get("camera_id") or camera_id
        channel_name = cam.get("nome") or default_nome

    image_path = None
    # Monta lpr_meta para o worker YOLO (antes do bloco de imagem, pois pode ser usado no snapshot)
    lpr_meta: dict = {"plate": plate or ""}
    try:
        if plate_rect:
            lpr_meta["plate_rect"]   = plate_rect
        if vehicle_rect:
            lpr_meta["vehicle_rect"] = vehicle_rect
        if pic_width and pic_height:
            lpr_meta["pic_size"] = {"w": int(pic_width), "h": int(pic_height)}
        # Sistema de coordenadas detectado
        lpr_meta["coord_type"] = coord_type
        # Cor e tipo já detectados pela câmera — usados como fallback no YOLO
        if xml_vehicle_color and xml_vehicle_color.lower() not in ("unknown", ""):
            lpr_meta["xml_vehicle_color"] = xml_vehicle_color.lower()
        if xml_vehicle_type and xml_vehicle_type.lower() not in ("unknown", ""):
            lpr_meta["xml_vehicle_type"] = xml_vehicle_type.lower()
    except (NameError, Exception):
        pass  # variáveis não definidas (sem XML)

    # Monta cam_meta com dados extras do XML para exibição no modal
    cam_meta: dict | None = None
    try:
        _cm: dict = {}
        if xml_plate_color   and xml_plate_color.lower()   not in ("unknown", ""):
            _cm["plate_color"]    = xml_plate_color
        if xml_vehicle_color and xml_vehicle_color.lower() not in ("unknown", ""):
            _cm["vehicle_color"]  = xml_vehicle_color
        if xml_vehicle_type  and xml_vehicle_type.lower()  not in ("unknown", ""):
            _cm["vehicle_type"]   = xml_vehicle_type
        if xml_speed is not None:
            try:
                _cm["speed"] = int(xml_speed)
            except Exception:
                pass
        if xml_speed_limit is not None:
            try:
                _cm["speed_limit"] = int(xml_speed_limit)
            except Exception:
                pass
        if xml_illegal_code is not None:
            try:
                _cm["illegal_code"] = int(xml_illegal_code)
            except Exception:
                pass
        if xml_illegal_name  and xml_illegal_name.lower()  not in ("unknown", ""):
            _cm["illegal_name"]   = xml_illegal_name
        if xml_plate_chars   and xml_plate_chars.strip():
            _cm["plate_char_confidence"] = xml_plate_chars.strip()
        if xml_license_bright is not None:
            try:
                _cm["license_bright"] = int(xml_license_bright)
            except Exception:
                pass
        if _cm:
            cam_meta = _cm
    except NameError:
        pass  # sem XML

    # ── Salva imagem enviada no POST (se houver) ──────────────────────────
    for _img_name, data in images:
        day   = (occurred_at or _utcnow()).strftime("%Y-%m-%d")
        d     = UPLOAD_DIR / day
        d.mkdir(parents=True, exist_ok=True)
        fname = f"{uuid.uuid4().hex}.jpg"
        try:
            (d / fname).write_bytes(data)
            image_path = f"/uploads/{day}/{fname}"
            # Enfileira análise YOLO para esta imagem
            try:
                abs_path = f"/app/uploads/{day}/{fname}"
                _get_rq_queue().enqueue(
                    "worker.job_analyze_event",
                    abs_path,
                    plate or "",
                    lpr_meta,
                    job_timeout=120,
                )
            except Exception as _rq_err:
                print(f"[RQ] Falha ao enfileirar job YOLO: {_rq_err}")
        except Exception as _img_err:
            print(f"[INGEST] Erro ao salvar imagem: {_img_err}")

    # Deriva direção real do veículo:
    # - Usa direction do XML (forward/reverse) + direcao configurada na câmera
    # - forward + CRESCENTE   → CRESCENTE  | forward + DECRESCENTE → DECRESCENTE
    # - reverse + CRESCENTE   → DECRESCENTE| reverse + DECRESCENTE → CRESCENTE
    cam_direcao  = cam.get("direcao") if camera_id else None
    event_direcao = _derive_direcao(cam_direcao, xml_direction)

    with _conn() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO lpr_events
                    (plate, camera_id, channel_name, camera_ip, confidence, image_path, occurred_at, direcao, cam_meta)
                VALUES
                    (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                RETURNING id
            """, (
                plate,
                camera_id,
                channel_name,
                xml_ip or client_ip,   # usa o IP real da câmera (do XML); fallback: IP do cliente HTTP
                confidence,
                image_path,
                occurred_at,
                event_direcao,         # direção derivada: XML direction + direcao da câmera
                _json_lib.dumps(cam_meta) if cam_meta else None,
            ))
            event_id = cur.fetchone()[0]

    # Se não chegou imagem pelo POST, tenta buscar snapshot da câmera via ISAPI
    if not image_path and cam.get("ip") and cam.get("usuario") and cam.get("senha"):
        background_tasks.add_task(
            _fetch_snapshot_and_enqueue,
            event_id,
            cam["ip"],
            cam["usuario"],
            cam["senha"],
            plate,
            lpr_meta,
        )

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
                    SELECT DISTINCT vli.plate, vl.id, vl.name, vl.color,
                                    vl.alarm_enabled, vl.alarm_sound
                    FROM vehicle_list_items vli
                    JOIN vehicle_lists vl ON vl.id = vli.list_id
                    ORDER BY vli.plate
                """)
                rows = cur.fetchall()
        
        plates = {}
        for plate, list_id, list_name, color, alarm_enabled, alarm_sound in rows:
            if plate not in plates:
                plates[plate] = []
            plates[plate].append({
                "list_id": list_id,
                "list_name": list_name,
                "color": color,
                "alarm_enabled": alarm_enabled or False,
                "alarm_sound": alarm_sound or "beep",
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
    with _conn() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT id, plate, descricao, created_at
                FROM alvos
                ORDER BY created_at DESC
            """)
            rows = cur.fetchall()
    alvos = [
        {"id": r[0], "plate": r[1], "descricao": r[2],
         "created_at": r[3].isoformat() if r[3] else None}
        for r in rows
    ]
    return {"alvos": alvos, "total": len(alvos)}


# ---------------------------------------------------------------------------
# Helper: sincroniza alvo com a lista de monitoramento (alarme ativo)
# ---------------------------------------------------------------------------
ALVOS_LIST_NAME = "Alvos Rastreados"

def _get_or_create_alvos_list_id(cur) -> int:
    """Retorna o id da lista 'Alvos Rastreados', criando-a com alarme ativo se não existir."""
    cur.execute("SELECT id FROM vehicle_lists WHERE name = %s", (ALVOS_LIST_NAME,))
    row = cur.fetchone()
    if row:
        cur.execute("UPDATE vehicle_lists SET alarm_enabled = TRUE WHERE id = %s", (row[0],))
        return row[0]
    cur.execute(
        """
        INSERT INTO vehicle_lists (name, description, color, alarm_enabled)
        VALUES (%s, %s, %s, TRUE)
        RETURNING id
        """,
        (ALVOS_LIST_NAME, "Gerada automaticamente pelo módulo Batedor/Alvos Rastreados", "#dc2626")
    )
    return cur.fetchone()[0]


def _sync_alvo_to_lista(cur, plate: str, descricao: str, old_plate: str = None):
    """Adiciona ou atualiza a placa na lista de monitoramento 'Alvos Rastreados'."""
    list_id = _get_or_create_alvos_list_id(cur)
    notes = descricao or "Alvo rastreado"
    if old_plate and old_plate != plate:
        cur.execute(
            "DELETE FROM vehicle_list_items WHERE list_id = %s AND plate = %s",
            (list_id, old_plate)
        )
    cur.execute(
        """
        INSERT INTO vehicle_list_items (list_id, plate, notes)
        VALUES (%s, %s, %s)
        ON CONFLICT (list_id, plate) DO UPDATE SET notes = EXCLUDED.notes
        """,
        (list_id, plate, notes)
    )


def _remove_alvo_from_lista(cur, plate: str):
    """Remove a placa da lista de monitoramento 'Alvos Rastreados'."""
    cur.execute("SELECT id FROM vehicle_lists WHERE name = %s", (ALVOS_LIST_NAME,))
    row = cur.fetchone()
    if row:
        cur.execute(
            "DELETE FROM vehicle_list_items WHERE list_id = %s AND plate = %s",
            (row[0], plate)
        )


@app.post("/api/alvos")
async def alvos_create(request: Request):
    data = await request.json()
    plate = (data.get("plate") or "").strip().upper()
    descricao = (data.get("descricao") or "").strip()
    if not plate:
        raise HTTPException(status_code=400, detail="Placa obrigatória")
    with _conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO alvos (plate, descricao)
                VALUES (%s, %s)
                ON CONFLICT (plate) DO UPDATE SET descricao = EXCLUDED.descricao
                RETURNING id, plate, descricao, created_at
                """,
                (plate, descricao),
            )
            r = cur.fetchone()
            _sync_alvo_to_lista(cur, plate, descricao)
    return {"ok": True, "alvo": {"id": r[0], "plate": r[1], "descricao": r[2],
                                  "created_at": r[3].isoformat() if r[3] else None}}


@app.delete("/api/alvos/{aid}")
def alvos_delete(aid: int):
    with _conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT plate FROM alvos WHERE id = %s", (aid,))
            row = cur.fetchone()
            if row:
                _remove_alvo_from_lista(cur, row[0])
            cur.execute("DELETE FROM alvos WHERE id = %s", (aid,))
    return {"ok": True}


@app.put("/api/alvos/{aid}")
async def alvos_update(aid: int, request: Request):
    body = await request.json()
    plate    = (body.get("plate") or "").strip().upper()
    descricao = (body.get("descricao") or "").strip()
    if not plate:
        from fastapi.responses import JSONResponse
        return JSONResponse(status_code=400, content={"error": "Placa obrigatoria"})
    with _conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT plate FROM alvos WHERE id = %s", (aid,))
            row = cur.fetchone()
            if not row:
                from fastapi.responses import JSONResponse
                return JSONResponse(status_code=404, content={"error": "Alvo nao encontrado"})
            old_plate = row[0]
            cur.execute(
                "UPDATE alvos SET plate = %s, descricao = %s WHERE id = %s RETURNING id, plate, descricao",
                (plate, descricao, aid)
            )
            r = cur.fetchone()
            _sync_alvo_to_lista(cur, plate, descricao, old_plate=old_plate)
    return {"ok": True, "alvo": {"id": r[0], "plate": r[1], "descricao": r[2]}}


@app.post("/api/alvos/import-list/{list_id}")
def alvos_import_list(list_id: int):
    """Importa todas as placas de uma lista de monitoramento como Alvos Rastreados."""
    with _conn() as conn:
        with conn.cursor() as cur:
            # Verifica se a lista existe
            cur.execute("SELECT name FROM vehicle_lists WHERE id = %s", (list_id,))
            row = cur.fetchone()
            if not row:
                raise HTTPException(status_code=404, detail="Lista não encontrada")
            list_name = row[0]
            # Busca todas as placas da lista
            cur.execute(
                "SELECT plate, notes FROM vehicle_list_items WHERE list_id = %s",
                (list_id,),
            )
            items = cur.fetchall()
            if not items:
                raise HTTPException(status_code=400, detail="Lista não tem veículos cadastrados")
            inserted = 0
            updated = 0
            for plate, notes in items:
                desc = f"Importado da lista: {list_name}" + (f" — {notes}" if notes else "")
                cur.execute(
                    """
                    INSERT INTO alvos (plate, descricao)
                    VALUES (%s, %s)
                    ON CONFLICT (plate) DO UPDATE SET descricao = EXCLUDED.descricao
                    """,
                    (plate.upper(), desc),
                )
                if cur.rowcount:
                    inserted += 1
                else:
                    updated += 1
    return {"ok": True, "list_name": list_name, "total": len(items), "inserted": inserted}


@app.get("/api/alvos/recentes")
def alvos_recent(window: str = "30m"):
    wm = _parse_window_to_minutes(window)
    with _conn() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT a.id, a.plate, a.descricao, MAX(COALESCE(e.occurred_at, e.ts)) AS ultimo
                FROM alvos a
                LEFT JOIN lpr_events e ON e.plate = a.plate
                  AND COALESCE(e.occurred_at, e.ts) >= NOW() - (%s * INTERVAL '1 minute')
                GROUP BY a.id, a.plate, a.descricao
                HAVING MAX(COALESCE(e.occurred_at, e.ts)) IS NOT NULL
                ORDER BY ultimo DESC
            """, (wm,))
            rows = cur.fetchall()
    return {"items": [
        {"id": r[0], "plate": r[1], "descricao": r[2],
         "ultimo": r[3].isoformat() if r[3] else None}
        for r in rows
    ]}


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
                       e.image_path, COALESCE(e.occurred_at, e.ts) AS ts,
                       COALESCE(NULLIF(e.direcao,''), c.direcao) AS direcao,
                       c.nome AS cam_nome
                FROM lpr_events e
                LEFT JOIN cameras c ON c.id = (
                    SELECT id FROM cameras
                    WHERE camera_id = e.camera_id OR ip = e.camera_id OR ip = e.camera_ip
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
def batedor_companions(
    plate: str,
    window: str = "24h",
    co_window: int = 600,
    limit: int = 20,
):
    """
    Retorna os acompanhantes detectados para a placa informada:
    placas vistas na mesma câmera em ≤ co_window segundos dentro da janela.

    Resposta:
      companions[].companion          – placa do acompanhante
      companions[].cameras_together   – qtd de câmeras distintas onde apareceram juntos
      companions[].avg_co_delta_sec   – intervalo médio (s)
      companions[].last_seen          – timestamp mais recente de co-passagem
      companions[].companion_leads    – nº de vezes que o acompanhante chegou ANTES
      companions[].target_leads       – nº de vezes que a placa alvo chegou antes
      companions[].evidence[]         – lista de passagens por câmera
      companions[].yolo_multi_events  – nº de frames com 2+ veículos (YOLO)
    """
    from collections import defaultdict

    co_win_s   = max(10, int(co_window))
    window_min = _parse_window_to_minutes(window)
    lim        = max(1, min(100, int(limit)))
    t_to       = _utcnow()
    t_from     = t_to - timedelta(minutes=window_min)
    plate      = (plate or "").strip()
    if not plate:
        return {"companions": []}

    with _conn() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT
                    b.plate                                              AS companion,
                    COALESCE(c.nome, a.camera_id)                        AS camera_name,
                    COALESCE(a.occurred_at, a.ts)                        AS ts_target,
                    COALESCE(b.occurred_at, b.ts)                        AS ts_companion,
                    ABS(EXTRACT(EPOCH FROM (
                        COALESCE(b.occurred_at, b.ts) - COALESCE(a.occurred_at, a.ts)
                    )))::int                                              AS co_delta_sec,
                    COALESCE((a.yolo_result->>'vehicle_count')::int, -1) AS yolo_vc_target,
                    COALESCE((b.yolo_result->>'vehicle_count')::int, -1) AS yolo_vc_companion,
                    COALESCE(NULLIF(a.direcao,''), c.direcao)            AS direcao,
                    a.camera_id                                          AS camera_id
                FROM lpr_events a
                LEFT JOIN cameras c ON c.id = (
                    SELECT id FROM cameras
                    WHERE camera_id = a.camera_id
                       OR ip        = a.camera_id
                       OR ip        = a.camera_ip
                    ORDER BY (camera_id = a.camera_id) DESC
                    LIMIT 1
                )
                JOIN lpr_events b
                    ON  a.camera_id = b.camera_id
                    AND a.id       != b.id
                    AND b.plate    != a.plate
                    AND ABS(EXTRACT(EPOCH FROM (
                            COALESCE(b.occurred_at, b.ts) - COALESCE(a.occurred_at, a.ts)
                        ))) <= %s
                WHERE a.plate = %s
                  AND b.plate IS NOT NULL
                  AND b.plate NOT IN ('', 'unknown', 'UNKNOWN')
                  AND COALESCE(a.occurred_at, a.ts) BETWEEN %s AND %s
                ORDER BY COALESCE(a.occurred_at, a.ts)
                LIMIT 5000
            """, (co_win_s, plate, t_from, t_to))
            rows = cur.fetchall()

    comp_data: dict = defaultdict(lambda: {
        "cameras":           set(),
        "co_deltas":         [],
        "last_seen":         None,
        "companion_leads":   0,
        "target_leads":      0,
        "evidence":          [],
        "yolo_multi_events": 0,
    })

    for row in rows:
        companion, camera_name, ts_target, ts_companion, co_delta_sec, yolo_vc_t, yolo_vc_c, direcao, camera_id = row
        cd               = comp_data[companion]
        cd["cameras"].add(camera_id)
        cd["co_deltas"].append(int(co_delta_sec))
        ts_t_iso = ts_target.isoformat()    if ts_target    else None
        ts_c_iso = ts_companion.isoformat() if ts_companion  else None
        if not cd["last_seen"] or (ts_t_iso and ts_t_iso > cd["last_seen"]):
            cd["last_seen"] = ts_t_iso
        if ts_target and ts_companion:
            if ts_companion < ts_target:
                cd["companion_leads"] += 1
            else:
                cd["target_leads"] += 1
        if int(yolo_vc_t) > 1 or int(yolo_vc_c) > 1:
            cd["yolo_multi_events"] += 1
        cd["evidence"].append({
            "camera":            camera_name,
            "camera_id":         camera_id,
            "direcao":           direcao or None,
            "ts_target":         ts_t_iso,
            "ts_companion":      ts_c_iso,
            "co_delta_sec":      int(co_delta_sec),
            "yolo_vc_target":    int(yolo_vc_t),
            "yolo_vc_companion": int(yolo_vc_c),
        })

    result = []
    for companion, cd in comp_data.items():
        ct  = len(cd["cameras"])
        avg = int(sum(cd["co_deltas"]) / len(cd["co_deltas"])) if cd["co_deltas"] else 0
        result.append({
            "companion":         companion,
            "cameras_together":  ct,
            "avg_co_delta_sec":  avg,
            "last_seen":         cd["last_seen"],
            "companion_leads":   cd["companion_leads"],
            "target_leads":      cd["target_leads"],
            "evidence":          cd["evidence"][:20],
            "yolo_multi_events": cd["yolo_multi_events"],
        })

    result.sort(key=lambda x: x["cameras_together"], reverse=True)
    return {"companions": result[:lim]}


# ===========================
# BATEDOR — ENDPOINTS REAIS
# ===========================

def _parse_window_to_minutes(w: str) -> int:
    """Converte '2h', '24h', '7d', '90d', '30m' em minutos."""
    w = str(w).strip().lower()
    try:
        if w.endswith("d"):
            return int(w[:-1]) * 1440
        elif w.endswith("h"):
            return int(w[:-1]) * 60
        elif w.endswith("m"):
            return max(1, int(w[:-1]))
        return int(w)
    except Exception:
        return 120


# ===========================
# RELATÓRIO UNIFICADO DE VEÍCULO
# ===========================


# ===========================
# RELATÓRIO UNIFICADO DE VEÍCULO
# ===========================

@app.get("/api/vehicle/report")
def vehicle_report(
    plate: str,
    window: str = "2h",
    ts_from: Optional[str] = None,
    ts_to: Optional[str] = None,
    filter_camera: Optional[str] = None,
    filter_direction: Optional[str] = None,
    min_confidence: float = 0.0,
    min_cameras: int = 0,
):
    """
    Relatório completo de veículo.

    Retorna:
      plate, window, level, is_alvo, alvo_descricao, alvo_list,
      score, score_breakdown[], badges[],
      summary{}, events[], convoy_partners[],
      last_decision{}
    """
    from collections import Counter

    plate = (plate or "").strip().upper()
    if not plate:
        raise HTTPException(status_code=422, detail="plate é obrigatório")

    # ── Período ──
    if ts_from and ts_to:
        try:
            t_from = datetime.fromisoformat(ts_from.replace('Z', '')).replace(tzinfo=timezone.utc)
            t_to   = datetime.fromisoformat(ts_to.replace('Z', '')).replace(tzinfo=timezone.utc)
        except Exception:
            window_min = _parse_window_to_minutes(window)
            t_to   = _utcnow()
            t_from = t_to - timedelta(minutes=window_min)
    else:
        window_min = _parse_window_to_minutes(window)
        t_to   = _utcnow()
        t_from = t_to - timedelta(minutes=window_min)

    # ── Filtros dinâmicos ──
    ev_extra: list = []
    ev_extra_vals: list = []
    if filter_camera:
        ev_extra.append("AND e.camera_id = %s")
        ev_extra_vals.append(filter_camera)
    if filter_direction:
        ev_extra.append("AND COALESCE(NULLIF(e.direcao,''), c.direcao) = %s")
        ev_extra_vals.append(filter_direction.upper())
    if min_confidence > 0:
        ev_extra.append("AND COALESCE(e.confidence, 0.0) >= %s")
        ev_extra_vals.append(float(min_confidence))
    ev_extra_sql = "\n                  ".join(ev_extra)

    pt_extra: list = []
    pt_extra_vals: list = []
    if filter_camera:
        pt_extra.append("AND a.camera_id = %s")
        pt_extra_vals.append(filter_camera)
    pt_extra_sql = "\n                  ".join(pt_extra)

    with _conn() as conn:
        with conn.cursor() as cur:

            # ── 1. Passagens da placa ──────────────────────────────────────
            #    BUG-FIX: JOIN por c.camera_id = e.camera_id (texto), c.nome (não c.name)
            #    DIRECAO: priorizamos e.direcao (quando gravado) senão herdamos c.direcao
            cur.execute(f"""
                SELECT
                    e.id,
                    e.plate,
                    e.camera_id,
                    COALESCE(c.nome, e.camera_id)                                AS camera_name,
                    COALESCE(e.occurred_at, e.ts)                                AS ts,
                    e.image_path,
                    COALESCE(NULLIF(e.direcao,''), c.direcao)                    AS direcao,
                    COALESCE((e.yolo_result->>'vehicle_type'), '')               AS vehicle_type,
                    COALESCE((e.yolo_result->>'vehicle_count')::int, 1)          AS vehicle_count,
                    COALESCE(e.confidence, 0.0)                                  AS confidence
                FROM lpr_events e
                LEFT JOIN cameras c ON c.id = (
                    SELECT id FROM cameras
                    WHERE camera_id = e.camera_id
                       OR ip        = e.camera_id
                       OR ip        = e.camera_ip
                    ORDER BY (camera_id = e.camera_id) DESC
                    LIMIT 1
                )
                WHERE e.plate = %s
                  AND COALESCE(e.occurred_at, e.ts) BETWEEN %s AND %s
                  {ev_extra_sql}
                ORDER BY ts DESC
                LIMIT 500
            """, (plate, t_from, t_to, *ev_extra_vals))
            ev_rows = cur.fetchall()

            # ── 2. Parceiros de co-aparecimento ────────────────────────────
            cur.execute(f"""
                SELECT
                    b.plate                                                      AS partner,
                    COUNT(DISTINCT a.camera_id)                                  AS cameras_together,
                    AVG(ABS(EXTRACT(EPOCH FROM (
                        COALESCE(b.occurred_at, b.ts) -
                        COALESCE(a.occurred_at, a.ts)
                    ))))::int                                                     AS avg_delta_sec,
                    MIN(COALESCE(b.occurred_at, b.ts))                           AS first_seen,
                    MAX(COALESCE(b.occurred_at, b.ts))                           AS last_seen,
                    COUNT(*)                                                      AS joint_events,
                    AVG(COALESCE(b.confidence, 0))::float                        AS avg_conf
                FROM lpr_events a
                JOIN lpr_events b
                    ON  a.camera_id = b.camera_id
                    AND a.id       != b.id
                    AND b.plate    != a.plate
                    AND ABS(EXTRACT(EPOCH FROM (
                            COALESCE(b.occurred_at, b.ts) -
                            COALESCE(a.occurred_at, a.ts)
                        ))) <= 300
                WHERE a.plate = %s
                  AND COALESCE(a.occurred_at, a.ts) BETWEEN %s AND %s
                  AND b.plate IS NOT NULL
                  AND b.plate != ''
                  AND b.plate NOT IN ('unknown','UNKNOWN')
                  {pt_extra_sql}
                GROUP BY b.plate
                ORDER BY cameras_together DESC, joint_events DESC
                LIMIT 30
            """, (plate, t_from, t_to, *pt_extra_vals))
            partner_rows = cur.fetchall()

            # ── 3. Status alvo ─────────────────────────────────────────────
            #    BUG-FIX: list_id pode não existir — consulta segura
            cur.execute("""
                SELECT a.plate, a.descricao,
                       vl.name AS list_name
                FROM alvos a
                LEFT JOIN vehicle_lists vl ON vl.id = a.list_id
                WHERE a.plate = %s
                LIMIT 1
            """, (plate,))
            alvo_row = cur.fetchone()

            # ── 4. Alvos entre parceiros ───────────────────────────────────
            partner_plates = [r[0] for r in partner_rows] if partner_rows else []
            alvo_partners: set[str] = set()
            if partner_plates:
                ph = ",".join(["%s"] * len(partner_plates))
                cur.execute(f"SELECT plate FROM alvos WHERE plate IN ({ph})", partner_plates)
                alvo_partners = {r[0] for r in cur.fetchall()}

            # ── 5. Última decisão operacional ──────────────────────────────
            cur.execute("""
                SELECT id, decision, decision_note, operator, created_at
                FROM vehicle_report_decisions
                WHERE plate = %s
                ORDER BY created_at DESC
                LIMIT 1
            """, (plate,))
            dec_row = cur.fetchone()

    # ── Montar eventos ─────────────────────────────────────────────────────
    events: list[dict] = []
    cameras_set: set[str] = set()
    direcoes: list[str] = []
    confidences: list[float] = []
    for r in ev_rows:
        cam = str(r[2]) if r[2] else ""
        cameras_set.add(cam)
        d = r[6] or ""
        if d:
            direcoes.append(d)
        conf = float(r[9]) if r[9] else 0.0
        if conf > 0:
            confidences.append(conf)
        events.append({
            "id":            r[0],
            "plate":         r[1],
            "camera_id":     cam,
            "camera_name":   r[3] or cam,
            "ts":            r[4].isoformat() if r[4] else None,
            "image_path":    r[5],
            "direcao":       d,
            "vehicle_type":  r[7],
            "vehicle_count": r[8],
            "confidence":    round(conf, 2),
        })

    total_passes  = len(events)
    cameras_count = len(cameras_set)
    avg_conf = round(sum(confidences) / len(confidences), 2) if confidences else 0.0

    # ── Montar parceiros ───────────────────────────────────────────────────
    partners: list[dict] = []
    for r in partner_rows:
        partners.append({
            "plate":            r[0],
            "cameras_together": int(r[1]),
            "avg_delta_sec":    int(r[2]) if r[2] else 0,
            "first_seen":       r[3].isoformat() if r[3] else None,
            "last_seen":        r[4].isoformat() if r[4] else None,
            "joint_events":     int(r[5]),
            "avg_conf":         round(float(r[6]) if r[6] else 0.0, 2),
            "is_alvo":          r[0] in alvo_partners,
        })

    # ── Filtro pós-processamento: mínimo de câmeras juntos ──
    if min_cameras > 1:
        partners = [p for p in partners if p["cameras_together"] >= min_cameras]

    is_alvo        = alvo_row is not None
    alvo_descricao = alvo_row[1] if alvo_row else None
    alvo_list      = alvo_row[2] if alvo_row else None

    # ── Score breakdown ────────────────────────────────────────────────────
    breakdown: list[dict] = []
    score = 0

    def _add(label: str, value: int, multiplier: int, reason: str = "") -> None:
        nonlocal score
        pts = value * multiplier
        if pts > 0:
            breakdown.append({
                "label":      label,
                "value":      value,
                "multiplier": multiplier,
                "points":     pts,
                "reason":     reason,
            })
            score += pts

    _add("Câmeras distintas",           cameras_count,        10, "Cada câmera única = +10 pts")
    _add("Total de passagens",          total_passes,          2, "Cada passagem = +2 pts")
    _add("Parceiros co-detectados",     len(partners),        15, "Cada parceiro simultâneo = +15 pts")
    alvo_partners_count = sum(1 for p in partners if p["is_alvo"])
    _add("Parceiros já cadastrados como alvo", alvo_partners_count, 30, "Parceiro alvo = +30 pts")
    if is_alvo:
        _add("Placa cadastrada como alvo", 1, 50, "Alvo registrado = +50 pts")

    # ── Badges ────────────────────────────────────────────────────────────
    badges: list[str] = []
    if is_alvo:                      badges.append("ALVO")
    if cameras_count >= 3:           badges.append("MULTI-CÂMERA")
    if len(partners) >= 2:           badges.append("COMBOIO")
    if alvo_partners_count > 0:      badges.append("PARCEIRO-ALVO")
    if total_passes >= 5:            badges.append("REINCIDENTE")

    # ── Level ─────────────────────────────────────────────────────────────
    if score >= 80 or is_alvo:
        level = "alerta"
    elif score >= 40:
        level = "suspeito"
    else:
        level = "normal"

    # ── Direção dominante ─────────────────────────────────────────────────
    dom_dir = Counter(direcoes).most_common(1)[0][0] if direcoes else None

    # ── Última decisão ────────────────────────────────────────────────────
    last_decision: dict | None = None
    if dec_row:
        last_decision = {
            "id":        dec_row[0],
            "decision":  dec_row[1],
            "note":      dec_row[2],
            "operator":  dec_row[3],
            "created_at": dec_row[4].isoformat() if dec_row[4] else None,
        }

    return {
        "plate":           plate,
        "window":          window,
        "level":           level,
        "is_alvo":         is_alvo,
        "alvo_descricao":  alvo_descricao,
        "alvo_list":       alvo_list,
        "score":           score,
        "score_breakdown": breakdown,
        "badges":          badges,
        "summary": {
            "total_passes":   total_passes,
            "cameras_count":  cameras_count,
            "partners_count": len(partners),
            "avg_confidence": avg_conf,
            "first_seen":     events[-1]["ts"] if events else None,
            "last_seen":      events[0]["ts"]  if events else None,
            "dom_direction":  dom_dir,
        },
        "events":          events,
        "convoy_partners": partners,
        "last_decision":   last_decision,
        "filters_applied": {
            "window":         window if not (ts_from and ts_to) else None,
            "ts_from":        ts_from,
            "ts_to":          ts_to,
            "camera":         filter_camera,
            "direction":      filter_direction,
            "min_confidence": min_confidence if min_confidence > 0 else None,
            "min_cameras":    min_cameras    if min_cameras > 1   else None,
        },
    }


@app.post("/api/vehicle/report/decision", status_code=201)
async def vehicle_report_decision(request: Request):
    """
    Salva uma decisão operacional sobre um veículo.

    Body JSON:
      plate        (str, obrigatório)
      decision     (str: 'confirmado'|'falso_positivo'|'ignorar')
      score_total  (int, opcional)
      level        (str, opcional)
      badges       (list, opcional)
      sinais_principais (dict, opcional)
      note         (str, opcional — observação livre)
      window       (str, opcional)
    """
    data = await request.json()
    plate    = (data.get("plate") or "").strip().upper()
    decision = (data.get("decision") or "").strip().lower()
    if not plate:
        raise HTTPException(status_code=422, detail="plate é obrigatório")
    allowed = {"confirmado", "falso_positivo", "ignorar"}
    if decision not in allowed:
        raise HTTPException(status_code=422, detail=f"decision deve ser um de: {allowed}")

    score_total = int(data.get("score_total") or 0)
    level       = str(data.get("level") or "normal")
    badges      = data.get("badges") or []
    sinais      = data.get("sinais_principais") or {}
    note        = str(data.get("note") or "")[:1000]
    window      = str(data.get("window") or "2h")
    try:
        operator = request.state.user.get("sub", "") if isinstance(request.state.user, dict) else ""
    except Exception:
        operator = ""

    with _conn() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO vehicle_report_decisions
                    (plate, score_total, level, badges, sinais_principais, decision, decision_note, operator, report_window)
                VALUES (%s, %s, %s, %s::jsonb, %s::jsonb, %s, %s, %s, %s)
                RETURNING id, created_at
            """, (
                plate, score_total, level,
                _json_lib.dumps(badges), _json_lib.dumps(sinais),
                decision, note, operator, window,
            ))
            row = cur.fetchone()

    return {
        "ok":         True,
        "id":         row[0],
        "plate":      plate,
        "decision":   decision,
        "created_at": row[1].isoformat() if row[1] else None,
    }


@app.get("/api/vehicle/report/decisions")
def vehicle_report_decisions(
    plate: str | None = None,
    limit: int = 50,
    offset: int = 0,
):
    """Lista decisões operacionais. Filtra por placa se fornecida."""
    limit = max(1, min(200, int(limit)))
    with _conn() as conn:
        with conn.cursor() as cur:
            if plate:
                plate = plate.strip().upper()
                cur.execute("""
                    SELECT id, plate, score_total, level, badges, decision,
                           decision_note, operator, report_window, created_at
                    FROM vehicle_report_decisions
                    WHERE plate = %s
                    ORDER BY created_at DESC
                    LIMIT %s OFFSET %s
                """, (plate, limit, offset))
            else:
                cur.execute("""
                    SELECT id, plate, score_total, level, badges, decision,
                           decision_note, operator, report_window, created_at
                    FROM vehicle_report_decisions
                    ORDER BY created_at DESC
                    LIMIT %s OFFSET %s
                """, (limit, offset))
            rows = cur.fetchall()

    items = []
    for r in rows:
        items.append({
            "id":           r[0],
            "plate":        r[1],
            "score_total":  r[2],
            "level":        r[3],
            "badges":       r[4] if isinstance(r[4], list) else [],
            "decision":     r[5],
            "note":         r[6],
            "operator":     r[7],
            "window":       r[8],
            "created_at":   r[9].isoformat() if r[9] else None,
        })
    return {"items": items, "count": len(items)}


# ===========================
# CENTRAL DE AMEAÇAS — consolida suspeitos + comboio + grupos + alvos
# ===========================

@app.get("/api/batedor/central")
def batedor_central(
    window: str = "2h",
    limit: int = 150,
    ts_from: str | None = None,
    ts_to:   str | None = None,
):
    """
    Visão unificada: cruza suspeitos, comboio, grupos e alvos cadastrados.
    Retorna por placa: de quais módulos ela consta, score total e metadados.
    """
    from collections import defaultdict

    window_min = _parse_window_to_minutes(window)
    if ts_from and ts_to:
        t_from = _parse_dt(ts_from) or (_utcnow() - timedelta(minutes=window_min))
        t_to   = _parse_dt(ts_to)   or _utcnow()
    else:
        t_to   = _utcnow()
        t_from = t_to - timedelta(minutes=window_min)

    # acumulador por placa
    def _new():
        return {
            "in_suspeitos":   None,
            "in_comboio":     None,
            "in_grupos":      [],
            "is_alvo":        False,
            "alvo_descricao": None,
            "first_seen":     None,
            "last_seen":      None,
        }

    intel: dict = defaultdict(_new)

    def _upd(d, fs, ls):
        if fs and (d["first_seen"] is None or fs < d["first_seen"]):
            d["first_seen"] = fs
        if ls and (d["last_seen"]  is None or ls > d["last_seen"]):
            d["last_seen"]  = ls

    with _conn() as conn:
        with conn.cursor() as cur:

            # ── 1. SUSPEITOS ──────────────────────────────────────────────
            cur.execute("""
                SELECT plate,
                       COUNT(*)                       AS passes,
                       COUNT(DISTINCT camera_id)      AS cameras,
                       MIN(COALESCE(occurred_at, ts)) AS first_seen,
                       MAX(COALESCE(occurred_at, ts)) AS last_seen
                FROM lpr_events
                WHERE plate IS NOT NULL
                  AND plate NOT IN ('', 'unknown', 'UNKNOWN')
                  AND COALESCE(occurred_at, ts) BETWEEN %s AND %s
                GROUP BY plate
                HAVING COUNT(*) >= 2 AND COUNT(DISTINCT camera_id) >= 2
                ORDER BY COUNT(DISTINCT camera_id) DESC, COUNT(*) DESC
                LIMIT 300
            """, (t_from, t_to))
            for r in cur.fetchall():
                plate, passes, cameras, fs, ls = r[0], int(r[1]), int(r[2]), r[3], r[4]
                score = cameras * 10 + passes * 2
                intel[plate]["in_suspeitos"] = {"score": score, "passes": passes, "cameras": cameras}
                _upd(intel[plate], fs, ls)

            # ── 2. COMBOIO (transições entre câmeras dentro de 10–300 s) ──
            cur.execute("""
                SELECT a.plate,
                       COUNT(DISTINCT a.camera_id)      AS transitions,
                       MIN(COALESCE(a.occurred_at, a.ts)) AS first_seen,
                       MAX(COALESCE(a.occurred_at, a.ts)) AS last_seen
                FROM lpr_events a
                JOIN lpr_events b
                    ON  a.plate     = b.plate
                    AND a.camera_id != b.camera_id
                    AND a.id        != b.id
                    AND ABS(EXTRACT(EPOCH FROM (
                            COALESCE(b.occurred_at, b.ts) - COALESCE(a.occurred_at, a.ts)
                        ))) BETWEEN 10 AND 300
                WHERE a.plate IS NOT NULL
                  AND a.plate NOT IN ('', 'unknown', 'UNKNOWN')
                  AND COALESCE(a.occurred_at, a.ts) BETWEEN %s AND %s
                GROUP BY a.plate
                HAVING COUNT(DISTINCT a.camera_id) >= 2
                ORDER BY COUNT(DISTINCT a.camera_id) DESC
                LIMIT 300
            """, (t_from, t_to))
            for r in cur.fetchall():
                plate, transitions, fs, ls = r[0], int(r[1]), r[2], r[3]
                score = transitions * 5
                intel[plate]["in_comboio"] = {"score": score, "transitions": transitions}
                _upd(intel[plate], fs, ls)

            # ── 3. GRUPOS (pares vistos na mesma câmera em ≤120 s) ────────
            cur.execute("""
                SELECT LEAST(a.plate, b.plate)             AS plate_a,
                       GREATEST(a.plate, b.plate)          AS plate_b,
                       COUNT(DISTINCT a.camera_id)         AS cameras_together,
                       MIN(COALESCE(a.occurred_at, a.ts))  AS first_seen,
                       MAX(COALESCE(b.occurred_at, b.ts))  AS last_seen
                FROM lpr_events a
                JOIN lpr_events b
                    ON  a.camera_id = b.camera_id
                    AND a.plate     < b.plate
                    AND a.id       != b.id
                    AND ABS(EXTRACT(EPOCH FROM (
                            COALESCE(b.occurred_at, b.ts) - COALESCE(a.occurred_at, a.ts)
                        ))) <= 120
                WHERE a.plate IS NOT NULL AND b.plate IS NOT NULL
                  AND a.plate NOT IN ('', 'unknown', 'UNKNOWN')
                  AND b.plate NOT IN ('', 'unknown', 'UNKNOWN')
                  AND COALESCE(a.occurred_at, a.ts) BETWEEN %s AND %s
                GROUP BY plate_a, plate_b
                HAVING COUNT(DISTINCT a.camera_id) >= 1
                ORDER BY cameras_together DESC
                LIMIT 300
            """, (t_from, t_to))
            for r in cur.fetchall():
                pa, pb, ct, fs, ls = r[0], r[1], int(r[2]), r[3], r[4]
                score = ct * 10
                intel[pa]["in_grupos"].append({"plate": pb, "score": score, "cameras_together": ct})
                intel[pb]["in_grupos"].append({"plate": pa, "score": score, "cameras_together": ct})
                _upd(intel[pa], fs, ls)
                _upd(intel[pb], fs, ls)

            # ── 4. ALVOS cadastrados ───────────────────────────────────────
            cur.execute("SELECT plate, descricao FROM alvos")
            for row in cur.fetchall():
                # marca mesmo que não tenha aparecido na janela (para exibir na central)
                d = intel[row[0]]
                d["is_alvo"]        = True
                d["alvo_descricao"] = row[1] or ""

    # ── Monta itens ──────────────────────────────────────────────────────────
    items = []
    for plate, d in intel.items():
        sinais = sum([
            1 if d["in_suspeitos"] else 0,
            1 if d["in_comboio"]   else 0,
            1 if d["in_grupos"]    else 0,
            1 if d["is_alvo"]      else 0,
        ])
        s_score = (d["in_suspeitos"] or {}).get("score", 0)
        c_score = (d["in_comboio"]   or {}).get("score", 0)
        g_score = max((g["score"] for g in d["in_grupos"]), default=0)
        a_bonus = 50 if d["is_alvo"] else 0

        score_total = int(s_score + c_score * 1.5 + g_score * 1.2 + a_bonus)
        if   sinais >= 3: score_total = int(score_total * 1.5)
        elif sinais >= 2: score_total = int(score_total * 1.2)

        items.append({
            "plate":          plate,
            "score_total":    score_total,
            "sinais":         sinais,
            "in_suspeitos":   d["in_suspeitos"],
            "in_comboio":     d["in_comboio"],
            "in_grupos":      sorted(d["in_grupos"], key=lambda x: x["cameras_together"], reverse=True)[:5],
            "is_alvo":        d["is_alvo"],
            "alvo_descricao": d["alvo_descricao"],
            "first_seen":     d["first_seen"].isoformat() if d["first_seen"] else None,
            "last_seen":      d["last_seen"].isoformat()  if d["last_seen"]  else None,
        })

    items.sort(key=lambda x: (x["sinais"], x["score_total"]), reverse=True)
    return {"items": items[:limit], "total": len(items), "window": window}


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


# ===========================
# CATCH-ALL — debug / câmeras desconhecidas
# Público (sem JWT). Responde em /catchall E /api/catchall.
# Aceita GET/POST/PUT/PATCH/DELETE, qualquer Content-Type.
# Loga método, path, ip, content-type, tamanho e primeiros 2000 bytes do body.
# ===========================

async def _catchall_handler(request: Request) -> PlainTextResponse:
    """Handler público: loga a requisição e retorna 200 OK sem exigir JWT."""
    client_ip    = request.client.host if request.client else "unknown"
    method       = request.method
    path         = request.url.path
    content_type = request.headers.get("content-type", "-")

    body_raw  = await request.body()
    body_size = len(body_raw)
    try:
        body_preview = body_raw[:2000].decode("utf-8", errors="replace")
    except Exception:
        body_preview = body_raw[:2000].hex()

    print(
        f"[CATCHALL] {method} {path}\n"
        f"  ip           : {client_ip}\n"
        f"  content-type : {content_type}\n"
        f"  body_size    : {body_size} bytes\n"
        f"  body_2kb     : {body_preview[:500]}"
    )

    return PlainTextResponse("OK", status_code=200)


# Rota raiz /catchall (sem prefixo /api) — usada por câmeras e testes diretos
@app.api_route(
    "/catchall",
    methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
    include_in_schema=True,
    tags=["debug"],
    summary="Catch-all público (sem /api)",
)
async def catchall_root(request: Request):
    return await _catchall_handler(request)


# Rota /api/catchall — mantida por compatibilidade
@app.api_route(
    "/api/catchall",
    methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
    include_in_schema=True,
    tags=["debug"],
    summary="Catch-all público (com prefixo /api)",
)
async def catchall_api(request: Request):
    return await _catchall_handler(request)