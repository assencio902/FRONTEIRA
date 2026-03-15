# ===========================
# INGEST FASTAPI - BPFRON
# ===========================

import os
import re
import uuid
import logging
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

from jose import JWTError, ExpiredSignatureError, jwt as _jwt
from passlib.context import CryptContext
from starlette.middleware.base import BaseHTTPMiddleware

from services.fcm_service import (
    register_fcm_token,
    send_alert_for_detected_plate,
    send_alert_to_alarm_users,
    send_alert_to_user_tokens,
    get_fcm_credential_identity,
    FCMAlert,
    normalize_plate,
    is_likely_fake_token,
    MIN_PLATE_CONF,
    _is_valid_plate_format,
    _is_nonstandard_plate,
)

from cleanup_background import start_cleanup_background, stop_cleanup_background

# ============================================================
# RBAC - Role-Based Access Control
# ============================================================
from rbac import (
    VALID_ROLES,
    normalize_role,
    normalize_role_input,
    require_role,
    assert_admin,
    assert_admin_or_operator,
)

logger = logging.getLogger(__name__)

# ===========================
# CONFIG
# ===========================

UPLOAD_DIR = Path("uploads")

# Inicialização robusta: detecta se o path existe como arquivo (erro comum de
# bind mount incorreto no Docker, ex: host tem arquivo 'uploads' em vez de dir).
if UPLOAD_DIR.exists() and not UPLOAD_DIR.is_dir():
    raise RuntimeError(
        f"UPLOAD_DIR '{UPLOAD_DIR.resolve()}' existe mas é um arquivo regular, "
        "não um diretório. Remova ou renomeie o arquivo antes de iniciar o serviço. "
        "No host Docker verifique se './uploads' no docker-compose.yml aponta para "
        "um diretório, não para um arquivo."
    )
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
logger.info("UPLOAD_DIR inicializado: %s", UPLOAD_DIR.resolve())

MIN_LPR_CONFIDENCE = float(os.getenv("MIN_LPR_CONFIDENCE", "0.40"))

# ===========================
# AUTH / JWT
# ===========================
JWT_SECRET         = os.getenv("JWT_SECRET", "bpfron-change-me-in-production")
JWT_ALG            = "HS256"
JWT_EXPIRE         = int(os.getenv("JWT_EXPIRE_HOURS", "8"))   # horas
JWT_REFRESH_EXPIRE = int(os.getenv("JWT_REFRESH_EXPIRE_DAYS", "30"))  # dias

_pwd_ctx = CryptContext(schemes=["bcrypt"], deprecated="auto")

def _hash_pw(plain: str) -> str:
    return _pwd_ctx.hash(plain)

def _verify_pw(plain: str, hashed: str) -> bool:
    return _pwd_ctx.verify(plain, hashed)

def _make_token(sub: str, role: str, full_name: str) -> str:
    exp = datetime.now(timezone.utc) + timedelta(hours=JWT_EXPIRE)
    safe_role = normalize_role(role)
    return _jwt.encode({"sub": sub, "role": safe_role, "name": full_name, "exp": exp}, JWT_SECRET, algorithm=JWT_ALG)

def _make_refresh_token(sub: str) -> str:
    """Gera refresh token de longa duração (sem role — só para renovar access_token)."""
    exp = datetime.now(timezone.utc) + timedelta(days=JWT_REFRESH_EXPIRE)
    return _jwt.encode({"sub": sub, "type": "refresh", "exp": exp}, JWT_SECRET, algorithm=JWT_ALG)

def _decode_token(token: str) -> dict:
    return _jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALG])

# Paths públicos (não exigem JWT)
_PUBLIC_PREFIXES = ("/api/health", "/static", "/uploads", "/login", "/api/webhook", "/api/simple-webhook", "/webhook", "/api/ingest", "/api/catchall", "/catchall")
_PUBLIC_EXACT    = {"/", "/dashboard", "/favicon.ico", "/api/auth/login",
                    "/api/auth/refresh",
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
            logger.warning("[AUTH] Sem Bearer token em %s", path)
            return JSONResponse({"detail": "Não autenticado"}, status_code=401)
        token_str = auth.split(" ", 1)[1]
        try:
            payload = _decode_token(token_str)
            payload["role"] = normalize_role(payload.get("role"))
            request.state.user = payload
        except ExpiredSignatureError:
            logger.warning("[AUTH] Token expirado em %s (sub=%s)", path, _safe_sub(token_str))
            return JSONResponse({"detail": "Sessão expirada. Faça login novamente."}, status_code=401)
        except JWTError as e:
            logger.warning("[AUTH] Token inválido em %s: %s", path, e)
            return JSONResponse({"detail": "Token inválido ou expirado"}, status_code=401)
        return await call_next(request)

def _safe_sub(token_str: str) -> str:
    """Tenta extrair 'sub' do token sem validar, para logging."""
    try:
        payload = _jwt.decode(token_str, JWT_SECRET, algorithms=[JWT_ALG], options={"verify_exp": False})
        return payload.get("sub", "?")
    except Exception:
        return "?"


def _resolve_user_numeric_id_from_sub(sub: str | None) -> str | None:
    """Converte `sub` (username do JWT) para id numérico de `users`, se existir."""
    if not sub:
        return None
    try:
        with _conn() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT id FROM users WHERE username=%s LIMIT 1", (str(sub),))
                row = cur.fetchone()
        return str(row[0]) if row and row[0] is not None else None
    except Exception:
        return None

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
                    role TEXT DEFAULT 'visualizador',
                    ativa BOOLEAN DEFAULT TRUE,
                    created_at TIMESTAMPTZ DEFAULT NOW(),
                    updated_at TIMESTAMPTZ DEFAULT NOW()
                );
            """)
            # Migração RBAC: converte valores legados para os papéis oficiais.
            cur.execute("UPDATE users SET role='operador' WHERE role='operator';")
            cur.execute("UPDATE users SET role='visualizador' WHERE role IN ('viewer', 'visualizacao');")
            cur.execute("UPDATE users SET role='visualizador' WHERE role IS NULL OR TRIM(role)='';")
            cur.execute("ALTER TABLE users ALTER COLUMN role SET DEFAULT 'visualizador';")
            cur.execute("ALTER TABLE users DROP CONSTRAINT IF EXISTS users_role_check;")
            cur.execute(
                """
                ALTER TABLE users
                ADD CONSTRAINT users_role_check
                CHECK (role IN ('admin', 'operador', 'visualizador'))
                """
            )
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

            # Tokens FCM por dispositivo
            cur.execute("""
                CREATE TABLE IF NOT EXISTS fcm_device_tokens (
                    id SERIAL PRIMARY KEY,
                    user_id TEXT NOT NULL,
                    device_id TEXT NOT NULL,
                    fcm_token TEXT NOT NULL,
                    active BOOLEAN DEFAULT TRUE,
                    created_at TIMESTAMPTZ DEFAULT NOW(),
                    updated_at TIMESTAMPTZ DEFAULT NOW(),
                    last_seen_at TIMESTAMPTZ DEFAULT NOW(),
                    UNIQUE(user_id, device_id)
                );
            """)
            cur.execute("CREATE INDEX IF NOT EXISTS idx_fcm_tokens_user_active ON fcm_device_tokens(user_id, active);")

            # Log de alertas críticos enviados
            cur.execute("""
                CREATE TABLE IF NOT EXISTS alertas_criticos (
                    id SERIAL PRIMARY KEY,
                    usuario_id TEXT,
                    alvo_id INTEGER,
                    evento_id TEXT,
                    placa TEXT,
                    camera_name TEXT,
                    target_name TEXT,
                    detected_at TIMESTAMPTZ DEFAULT NOW(),
                    image_url TEXT,
                    city TEXT,
                    risk_level TEXT,
                    alert_type TEXT DEFAULT 'critical_alert',
                    criado_em TIMESTAMPTZ DEFAULT NOW(),
                    enviado_em TIMESTAMPTZ,
                    lido BOOLEAN DEFAULT FALSE,
                    error_message TEXT
                );
            """)
            cur.execute("CREATE INDEX IF NOT EXISTS idx_alertas_criticos_usuario ON alertas_criticos(usuario_id, criado_em DESC);")
            cur.execute("CREATE INDEX IF NOT EXISTS idx_alertas_criticos_evento ON alertas_criticos(evento_id);")

            # Alarmes configuráveis
            cur.execute("""
                CREATE TABLE IF NOT EXISTS alarmes (
                    id SERIAL PRIMARY KEY,
                    nome TEXT NOT NULL,
                    descricao TEXT,
                    tipo TEXT NOT NULL DEFAULT 'placa_monitorada',
                    prioridade TEXT NOT NULL DEFAULT 'media',
                    ativo BOOLEAN DEFAULT TRUE,
                    mensagem TEXT,
                    criado_em TIMESTAMPTZ DEFAULT NOW(),
                    atualizado_em TIMESTAMPTZ DEFAULT NOW()
                );
            """)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS alarme_listas (
                    alarme_id INTEGER NOT NULL REFERENCES alarmes(id) ON DELETE CASCADE,
                    lista_id INTEGER NOT NULL REFERENCES vehicle_lists(id) ON DELETE CASCADE,
                    PRIMARY KEY (alarme_id, lista_id)
                );
            """)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS alarme_usuarios (
                    alarme_id INTEGER NOT NULL REFERENCES alarmes(id) ON DELETE CASCADE,
                    usuario_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                    PRIMARY KEY (alarme_id, usuario_id)
                );
            """)

            # Cadastro Policial — Pessoas
            cur.execute("""
                CREATE TABLE IF NOT EXISTS pessoas (
                    id SERIAL PRIMARY KEY,
                    nome TEXT NOT NULL,
                    apelido TEXT,
                    contato TEXT,
                    profissao TEXT,
                    cpf TEXT,
                    rg TEXT,
                    data_nascimento DATE,
                    naturalidade TEXT,
                    estado_naturalidade TEXT,
                    nome_mae TEXT,
                    nome_pai TEXT,
                    data_cadastro TIMESTAMPTZ DEFAULT NOW()
                );
            """)
            cur.execute("CREATE INDEX IF NOT EXISTS idx_pessoas_nome ON pessoas(nome);")
            cur.execute("CREATE INDEX IF NOT EXISTS idx_pessoas_cpf  ON pessoas(cpf);")
            cur.execute("ALTER TABLE pessoas ADD COLUMN IF NOT EXISTS apelido TEXT;")
            cur.execute("ALTER TABLE pessoas ADD COLUMN IF NOT EXISTS contato TEXT;")
            cur.execute("ALTER TABLE pessoas ADD COLUMN IF NOT EXISTS profissao TEXT;")
            cur.execute("ALTER TABLE pessoas ADD COLUMN IF NOT EXISTS cpf TEXT;")
            cur.execute("ALTER TABLE pessoas ADD COLUMN IF NOT EXISTS rg TEXT;")
            cur.execute("ALTER TABLE pessoas ADD COLUMN IF NOT EXISTS data_nascimento DATE;")
            cur.execute("ALTER TABLE pessoas ADD COLUMN IF NOT EXISTS naturalidade TEXT;")
            cur.execute("ALTER TABLE pessoas ADD COLUMN IF NOT EXISTS estado_naturalidade TEXT;")
            cur.execute("ALTER TABLE pessoas ADD COLUMN IF NOT EXISTS nome_mae TEXT;")
            cur.execute("ALTER TABLE pessoas ADD COLUMN IF NOT EXISTS nome_pai TEXT;")


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
            # ORDER BY garante resultado determinístico: câmera cujo camera_id bate exatamente
            # tem prioridade sobre câmera cujo ip bate — evita retornar câmera errada quando
            # dois registros colidem (ex: CABIXIM com ip=.102 retornado para lookup de PRAINHA 1).
            cur.execute(
                """
                SELECT id, camera_id, nome, ativa, criticidade, peso, created_at, ip, direcao,
                       latitude, longitude, usuario, senha, modo_integracao
                FROM cameras
                WHERE camera_id=%s OR ip=%s
                ORDER BY (camera_id = %s) DESC, id DESC
                LIMIT 1
                """,
                (camera_id, camera_id, camera_id),
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
                "senha": row[12] or None,   # necessário para _fetch_snapshot_and_enqueue
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


def _normalize_plate(value: str | None) -> str:
    """Normalização única de placa para cadastro e comparação."""
    return normalize_plate(value)


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
    role = normalize_role(role)
    if not ativa:
        raise HTTPException(status_code=403, detail="Usuário inativo")
    if not _verify_pw(password, pw_hash):
        raise HTTPException(status_code=401, detail="Usuário ou senha inválidos")
    token         = _make_token(uname, role, full_name or uname)
    refresh_token = _make_refresh_token(uname)
    return {
        "access_token":  token,
        "refresh_token": refresh_token,
        "token_type":    "bearer",
        "expires_in":    JWT_EXPIRE * 3600,
        "role":          role,
        "full_name":     full_name or uname,
        "username":      uname,
    }

@app.get("/api/auth/me")
async def auth_me(request: Request):
    user = getattr(request.state, "user", None)
    if not user:
        raise HTTPException(status_code=401, detail="Não autenticado")
    return {
        "username": user.get("sub"),
        "role": normalize_role(user.get("role")),
        "full_name": user.get("name"),
    }

@app.post("/api/auth/refresh")
async def auth_refresh(request: Request):
    """Renova access_token usando um refresh_token válido (rota pública)."""
    data = await request.json()
    refresh_tk = str(data.get("refresh_token") or "").strip()
    if not refresh_tk:
        raise HTTPException(status_code=400, detail="refresh_token obrigatório")
    try:
        payload = _jwt.decode(refresh_tk, JWT_SECRET, algorithms=[JWT_ALG])
        if payload.get("type") != "refresh":
            raise HTTPException(status_code=401, detail="Token inválido (tipo incorreto)")
        sub = payload.get("sub")
        if not sub:
            raise HTTPException(status_code=401, detail="Token inválido")
    except ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Refresh token expirado. Faça login novamente.")
    except JWTError:
        raise HTTPException(status_code=401, detail="Refresh token inválido")
    with _conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT username, full_name, role, ativa FROM users WHERE username=%s LIMIT 1",
                (sub,),
            )
            row = cur.fetchone()
    if not row:
        raise HTTPException(status_code=401, detail="Usuário não encontrado")
    uname, full_name, role, ativa = row
    if not ativa:
        raise HTTPException(status_code=403, detail="Usuário inativo")
    role = normalize_role(role)
    new_access  = _make_token(uname, role, full_name or uname)
    new_refresh = _make_refresh_token(uname)
    logger.info("[AUTH] refresh bem-sucedido sub=%s", uname)
    return {
        "access_token":  new_access,
        "refresh_token": new_refresh,
        "token_type":    "bearer",
        "expires_in":    JWT_EXPIRE * 3600,
    }

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
    assert_admin(request, "Acesso restrito a administradores")
    with _conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT id, username, full_name, role, ativa, created_at FROM users ORDER BY id")
            rows = cur.fetchall()
    return {"items": [{"id": r[0], "username": r[1], "full_name": r[2], "role": r[3], "ativa": r[4], "created_at": r[5].isoformat() if r[5] else None} for r in rows]}

@app.post("/api/users", status_code=201)
async def create_user(request: Request):
    assert_admin(request, "Acesso restrito a administradores")
    data = await request.json()
    username  = str(data.get("username") or "").strip().lower()
    password  = str(data.get("password") or "").strip()
    full_name = str(data.get("full_name") or "").strip()
    role_raw  = data.get("role")
    role      = normalize_role_input(role_raw)
    ativa     = bool(data.get("ativa", True))
    if not username: raise HTTPException(status_code=400, detail="username obrigatório")
    if not password: raise HTTPException(status_code=400, detail="password obrigatório")
    if role not in VALID_ROLES:
        raise HTTPException(
            status_code=400,
            detail=f"role inválido: '{role_raw}'. Use apenas: admin, operador, visualizador",
        )
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
    # Apenas admin pode alterar dados de usuários
    assert_admin(request, "Apenas administradores podem alterar usuários")
    data = await request.json()
    sets, vals = [], []
    if "full_name" in data: sets.append("full_name=%s"); vals.append(str(data["full_name"]).strip())
    if "role" in data:
        role_raw = data["role"]
        role = normalize_role_input(role_raw)
        if role not in VALID_ROLES:
            raise HTTPException(
                status_code=400,
                detail=f"role inválido: '{role_raw}'. Use apenas: admin, operador, visualizacao",
            )
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
    assert_admin(request, "Acesso restrito a administradores")
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
    # Admin e operador podem criar câmeras
    assert_admin_or_operator(request, "Apenas administradores e operadores podem criar câmeras")
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
    # Admin e operador podem editar câmeras
    assert_admin_or_operator(request, "Apenas administradores e operadores podem editar câmeras")
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
def delete_camera(cam_id: int, request: Request):
    # Admin e operador podem deletar câmeras
    assert_admin_or_operator(request, "Apenas administradores e operadores podem deletar câmeras")
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


@app.get("/api/events/{event_id}")
def get_event_detail(event_id: int):
    """Retorna detalhes completos de um evento para visualização no modal de alerta."""
    with _conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
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
                WHERE e.id = %s
                LIMIT 1
                """,
                (event_id,),
            )
            r = cur.fetchone()
    if not r:
        raise HTTPException(status_code=404, detail="evento não encontrado")

    ts = r[7].isoformat() if r[7] else None
    raw_yolo = r[8]
    if raw_yolo is None:
        yolo = None
    elif isinstance(raw_yolo, dict):
        yolo = raw_yolo
    else:
        yolo = _json_lib.loads(raw_yolo)

    return {
        "id": r[0],
        "plate": r[1],
        "camera_id": r[2],
        "channel_name": r[3],
        "camera_ip": r[4],
        "confidence": float(r[5] or 0.0),
        "image_path": r[6],
        "occurred_at": ts,
        "camera": r[9] or r[3],
        "timestamp": ts,
        "image": r[6],
        "thumb": r[6],
        "yolo_result": yolo,
        "sem_placa_motivo": yolo.get("sem_placa_motivo") if yolo else None,
        "vehicle_details": yolo.get("vehicle_details") if yolo else None,
        "target_vehicle": yolo.get("target_vehicle") if yolo else None,
        "image_quality": yolo.get("image_quality") if yolo else None,
        "cam_nome": r[9] or r[3],
        "direcao": r[10] or None,
        "cam_meta": (_json_lib.loads(r[11]) if isinstance(r[11], str) else r[11]) if r[11] else None,
    }


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


def _parse_multipart_body(content_type: str, body: bytes) -> tuple["bytes | None", "list[tuple[str,bytes]]"]:
    """
    Analisa corpos multipart/form-data *e* multipart/mixed manualmente.
    Suporta:
      - XML com Content-Type: application/xml ou text/xml
      - XML sem content-type quando body começa com '<'
      - Partes de imagem (image/*)
    Retorna (xml_bytes, images).
    """
    xml_bytes: bytes | None = None
    images: list[tuple[str, bytes]] = []

    boundary: str | None = None
    for seg in content_type.split(";"):
        seg = seg.strip()
        if seg.lower().startswith("boundary="):
            boundary = seg[9:].strip().strip('"').strip("'")
            break
    if not boundary:
        logger.warning("[WEBHOOK-PARSE] multipart sem boundary em content_type=%s", content_type)
        return None, []

    delimiter = b"--" + boundary.encode("ascii", errors="replace")

    parts = body.split(delimiter)
    for raw_part in parts[1:]:
        # Delimitador final ("--") → stop
        stripped_head = raw_part[:8].strip()
        if stripped_head.startswith(b"--"):
            break

        # Separa headers do corpo da parte
        sep = b"\r\n\r\n" if b"\r\n\r\n" in raw_part else b"\n\n"
        if sep not in raw_part:
            continue
        headers_raw, part_body = raw_part.split(sep, 1)

        # Remove CRLF introduzido pelo boundary seguinte
        if part_body.endswith(b"\r\n"):
            part_body = part_body[:-2]
        elif part_body.endswith(b"\n"):
            part_body = part_body[:-1]

        # Faz parse mínimo dos headers da parte
        headers_text = headers_raw.decode("utf-8", errors="ignore")
        part_ct = ""
        part_filename = ""
        part_name = ""
        for line in headers_text.splitlines():
            lower_line = line.lower().strip()
            if lower_line.startswith("content-type:"):
                part_ct = line.split(":", 1)[1].strip().lower().split(";")[0].strip()
            elif lower_line.startswith("content-disposition:"):
                for piece in line.split(";"):
                    piece = piece.strip()
                    if piece.lower().startswith("filename="):
                        part_filename = piece[9:].strip('"').strip("'")
                    elif piece.lower().startswith("name="):
                        part_name = piece[5:].strip('"').strip("'")

        is_xml = (
            "xml" in part_ct
            or part_filename.lower().endswith(".xml")
            or (not part_body[:1].isdigit() and part_body.lstrip()[:1] == b"<")
        )
        is_image = part_ct.startswith("image/")

        if is_xml and xml_bytes is None:
            xml_bytes = part_body
            logger.info(
                "[WEBHOOK-PARSE] parte XML encontrada name=%s filename=%s ct=%s len=%d",
                part_name, part_filename, part_ct, len(part_body),
            )
        elif is_image and len(part_body) >= 10_000:
            images.append((part_filename or part_name or "image.jpg", part_body))
            logger.info(
                "[WEBHOOK-PARSE] parte imagem encontrada name=%s filename=%s ct=%s len=%d",
                part_name, part_filename, part_ct, len(part_body),
            )
        elif not is_xml and not is_image and xml_bytes is None and part_body.lstrip()[:1] == b"<":
            # Fallback: parte sem content-type, body parece XML
            xml_bytes = part_body
            logger.warning(
                "[WEBHOOK-PARSE] parte sem ct usada como XML (fallback) name=%s len=%d",
                part_name, len(part_body),
            )

    return xml_bytes, images


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

@app.post("/webhook")
@app.post("/api/simple-webhook")
async def simple_webhook(request: Request, background_tasks: BackgroundTasks):
    client_ip = _get_client_ip(request)
    content_type = request.headers.get("content-type", "")
    ct_lower = content_type.lower()

    xml_bytes: bytes | None = None
    images: list[tuple[str, bytes]] = []
    plate = ""
    camera_id = None
    xml_ip = None          # IP real da câmera (do XML <ipAddress>)
    channel_name_xml = None
    channel_name = None
    confidence = 0.0
    occurred_at = None
    xml_direction = None   # direção do veículo reportada pela câmera (forward/reverse)

    # ── Variáveis XML inicializadas aqui para evitar NameError após o bloco ──
    plate_rect: "dict | None" = None
    vehicle_rect: "dict | None" = None
    pic_width: "str | None" = None
    pic_height: "str | None" = None
    coord_type: str = "normalized"
    xml_vehicle_color: "str | None" = None
    xml_vehicle_type: "str | None" = None
    xml_plate_color: "str | None" = None
    xml_speed: "str | None" = None
    xml_speed_limit: "str | None" = None
    xml_illegal_code: "str | None" = None
    xml_illegal_name: "str | None" = None
    xml_plate_chars: "str | None" = None
    xml_license_bright: "str | None" = None

    _parser_used = "unknown"  # para logging de diagnóstico

    # ── Log de diagnóstico imediato ──────────────────────────────────────────
    logger.info(
        "[WEBHOOK-DIAG] POST /webhook ip=%s content_type=%r",
        client_ip, content_type,
    )

    if "multipart/" in ct_lower:
        # ── Formato Hikvision ISAPI: multipart/form-data OU multipart/mixed ──
        if "multipart/form-data" in ct_lower:
            # Starlette/python-multipart só processa multipart/form-data nativamente
            _parser_used = "multipart/form-data (form())"
            # Nomes de campo reconhecidos como placa (ordem de prioridade)
            _PLATE_FIELD_NAMES = (
                "licensePlate", "plate", "anprLicensePlate",
                "PlateNumber", "plateNumber", "ANPR.licensePlate", "ANPR_plate",
            )
            _form_text_fields: dict[str, str] = {}   # todos os campos texto recebidos
            try:
                form = await request.form()
            except ClientDisconnect:
                return JSONResponse({"ok": True})

            for field_name, v in form.multi_items():
                if isinstance(v, str):
                    _form_text_fields[field_name] = v
                    # XML enviado como campo de texto simples (sem filename)
                    if xml_bytes is None and v.strip().startswith("<"):
                        xml_bytes = v.encode("utf-8", errors="replace")
                        logger.info(
                            "[WEBHOOK-DIAG] XML recebido como campo texto name=%s len=%d",
                            field_name, len(xml_bytes),
                        )
                elif isinstance(v, UploadFile):
                    data = await v.read()
                    ct_part = (v.content_type or "").lower()
                    fname_lower = (v.filename or "").lower()
                    is_xml_part = (
                        fname_lower.endswith(".xml")
                        or "xml" in ct_part
                        or (xml_bytes is None and data.lstrip()[:1] == b"<")
                    )
                    if is_xml_part and xml_bytes is None:
                        xml_bytes = data
                        logger.info(
                            "[WEBHOOK-DIAG] XML recebido como UploadFile name=%s filename=%s ct=%s len=%d",
                            field_name, v.filename, v.content_type, len(data),
                        )
                    elif ct_part.startswith("image/") and len(data) >= 10_000:
                        images.append((v.filename or "image.jpg", data))
                    elif not is_xml_part and len(data) >= 10_000:
                        # Aceita como imagem independente de xml_bytes: câmeras podem enviar
                        # imagem antes do XML, ou só imagem (sem XML), com content-type binário
                        images.append((v.filename or "image.jpg", data))

            # ── Log de diagnóstico HTTP-escuta: campos recebidos no form ─────
            logger.info(
                "[WEBHOOK-HTTP-ESCUTA] ip=%s campos_form=%r xml_bytes=%s images=%d",
                client_ip,
                list(_form_text_fields.keys()),
                len(xml_bytes) if xml_bytes else 0,
                len(images),
            )
        else:
            _form_text_fields = {}
        if "multipart/mixed" in ct_lower or ("multipart/" in ct_lower and "form-data" not in ct_lower):
            # multipart/mixed ou outro subtipo — Starlette não processa; parse manual
            _parser_used = f"multipart/manual ({ct_lower.split(';')[0].strip()})"
            body_raw = await request.body()
            logger.info(
                "[WEBHOOK-DIAG] multipart/mixed ip=%s len=%d primeiros_500=%r",
                client_ip, len(body_raw), body_raw[:500].decode("utf-8", errors="replace"),
            )
            xml_bytes, images = _parse_multipart_body(content_type, body_raw)

    else:
        _form_text_fields = {}
        body = await request.body()

        # ── Log de corpo não-multipart ────────────────────────────────────────
        _body_preview = body[:500].decode("utf-8", errors="replace") if body else ""
        logger.info(
            "[WEBHOOK-DIAG] body não-multipart ip=%s len=%d ct=%r primeiros_500=%r",
            client_ip, len(body), content_type, _body_preview,
        )

        if "application/json" in ct_lower:
            _parser_used = "json"
            try:
                _json_input = await request.json()
            except Exception as e:
                logger.warning("[WEBHOOK-JSON] JSON inválido de %s: %s", client_ip, e)
                return JSONResponse({"ok": False, "detail": "JSON inválido"}, status_code=400)

            plate = normalize_plate((_json_input.get("plate") or "").strip())
            logger.info(
                "[WEBHOOK-DIAG] JSON campo plate=%r (normalizado=%r)",
                _json_input.get("plate"), plate,
            )

            try:
                confidence = float(_json_input.get("confidence") or 0)
            except Exception:
                confidence = 0.0

            if _json_input.get("camera_id"):
                camera_id = _json_input.get("camera_id")

            if _json_input.get("channel_name"):
                channel_name_xml = _json_input.get("channel_name")
                channel_name = _json_input.get("channel_name")

            if not occurred_at:
                occurred_at = datetime.now(timezone.utc)

            xml_bytes = None
            images = []

            logger.info(
                "[WEBHOOK-JSON] plate=%s confidence=%.3f camera_id=%s channel_name=%s",
                plate,
                confidence,
                camera_id,
                channel_name,
            )

        elif "xml" in ct_lower or body.lstrip()[:1] == b"<":
            # application/xml, text/xml OU body começa com '<' (XML sem content-type correto)
            _parser_used = "xml-direct"
            xml_bytes = body
            logger.info(
                "[WEBHOOK-DIAG] XML direto ip=%s len=%d ct=%r",
                client_ip, len(body), content_type,
            )

        else:
            # Body desconhecido — não processa como evento mas loga em detalhe
            logger.warning(
                "[WEBHOOK-DIAG] body ignorado ip=%s len=%d ct=%r — "
                "não é JSON, XML nem multipart. Verifique se a câmera usa HTTPS na porta HTTP "
                "(\"Invalid HTTP request received\" → TLS na porta 8000).",
                client_ip, len(body), content_type,
            )
            return JSONResponse({"ok": True, "bytes": len(body)})

    logger.info(
        "[WEBHOOK-DIAG] parser_usado=%s xml_bytes_len=%s images=%d",
        _parser_used, len(xml_bytes) if xml_bytes else 0, len(images),
    )

    if xml_bytes:
        try:
            root = ET.fromstring(xml_bytes)

            def x(tag):
                # Busca namespace-agnostic: suporta hikvision.com, isapi.org e sem namespace
                el = root.find(".//{*}" + tag)
                if el is None:
                    el = root.find(".//" + tag)  # fallback sem namespace
                return el.text.strip() if el is not None and el.text else None

            plate_raw        = (
                x("licensePlate")       # formato padrão ISAPI moderno
                or x("plateNumber")     # firmware antigo Hikvision
                or x("anprLicensePlate")
                or x("PlateNumber")
                or ""
            )
            plate            = _normalize_plate(plate_raw)

            # ── Log diagnóstico da extração da placa ───────────────────────────
            logger.info(
                "[WEBHOOK-DIAG] campo_xml=licensePlate bruta=%r normalizada=%r",
                plate_raw, plate,
            )
            if not plate:
                logger.warning(
                    "[WEBHOOK-DIAG] placa vazia após XML ip=%s — tag licensePlate=%r — "
                    "XML preview: %s",
                    client_ip, plate_raw,
                    xml_bytes[:300].decode("utf-8", errors="replace") if xml_bytes else "(none)",
                )

            xml_ip           = x("ipAddress")           # IP real: "172.21.151.16"
            channel_name_xml = x("channelName")         # nome do canal: "11_PRAINHA_1_CHACARAS"
            channel_id_xml   = x("channelID")           # fallback: "1"
            xml_event_type   = x("eventType")           # ex: "ANPR", "scenechangedetection"
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

            # camera_id = IP real da câmera extraído do XML.
            # channelName e channelID NÃO definem a identidade principal; servem como
            # nome/canal auxiliar apenas. A identidade final é resolvida abaixo,
            # priorizando X-Camera-IP > xml_ip > client_ip.
            camera_id = xml_ip or None   # None → resolvido após o bloco XML

            dt = x("dateTime")
            if dt:
                try:
                    occurred_at = datetime.fromisoformat(dt)
                    if not occurred_at.tzinfo:
                        occurred_at = occurred_at.replace(tzinfo=timezone.utc)
                except Exception:
                    occurred_at = None

            _confidence_raw = x("confidenceLevel")
            try:
                # Se a tag não existir, _confidence_raw é None → usamos -1 como sentinela
                # (significa "não informado"), para não confundir com confidence=0 explícito
                confidence = float(_confidence_raw) if _confidence_raw is not None else -1.0
            except Exception:
                confidence = -1.0

            # ── Filtra eventos que não são leituras ANPR reais ─────────────────
            _plate_raw_lower = (plate_raw or "").strip().lower()
            # Nota: confidence=0 explícito (câmera informou 0) descarta;
            #       confidence=-1 (tag ausente, câmera não informa) NÃO descarta
            _plate_is_empty_or_junk = (
                not _plate_raw_lower
                or _plate_raw_lower in ("unknown", "none", "null", "no_plate", "noplate")
            )
            _anpr_no_read = (
                _plate_is_empty_or_junk
                or (_confidence_raw is not None and confidence == 0.0)
                # confidence=0 SÓ descarta quando a tag estava presente no XML;
                # câmeras que omitem confidenceLevel recebem confidence=-1 e passam aqui
            )
            if xml_event_type and xml_event_type.lower() != "anpr":
                logger.info(
                    "[WEBHOOK-NOT-ANPR] ip=%s eventType=%r — evento não é ANPR, placa descartada",
                    client_ip, xml_event_type,
                )
                plate = ""
            elif _anpr_no_read:
                logger.info(
                    "[WEBHOOK-ANPR-UNKNOWN] ip=%s eventType=%r licensePlate=%r confidence=%.3f — sem leitura real",
                    client_ip, xml_event_type, plate_raw, confidence,
                )
                plate = ""

        except Exception as e:
            logger.exception(
                "[WEBHOOK] erro parse XML ip=%s bytes=%d: %s | xml_inicio=%r",
                client_ip, len(xml_bytes), e,
                xml_bytes[:200].decode("utf-8", errors="replace") if xml_bytes else "",
            )

    # ── Fallback HTTP-escuta: extrai placa dos campos do form se XML não a forneceu ──
    if not plate and _form_text_fields:
        _PLATE_FIELD_NAMES_FALLBACK = (
            "licensePlate", "plate", "anprLicensePlate",
            "PlateNumber", "plateNumber", "ANPR.licensePlate", "ANPR_plate",
        )
        for _pf in _PLATE_FIELD_NAMES_FALLBACK:
            _raw_val = _form_text_fields.get(_pf, "").strip()
            if _raw_val:
                _candidate = _normalize_plate(_raw_val)
                _candidate_lower = _raw_val.lower()
                if _candidate and _candidate_lower not in ("unknown", "none", "null", "no_plate", "noplate"):
                    plate = _candidate
                    logger.info(
                        "[WEBHOOK-HTTP-ESCUTA] placa extraída do campo form name=%r bruto=%r normalizado=%r",
                        _pf, _raw_val, plate,
                    )
                    break
        if not plate:
            logger.info(
                "[WEBHOOK-HTTP-ESCUTA] ip=%s — nenhuma placa encontrada nos campos do form %r — "
                "evento salvo sem placa (aguarda YOLO/OCR)",
                client_ip, list(_form_text_fields.keys()),
            )

    # ── Fallback query string: Hikvision HTTP-escuta que envia dados pela URL ────
    # Exemplo real capturado por pcap:
    # POST /api/simple-webhook?channelID=1&dateTime=20260315T112740-300
    #   &eventType=vehicleDetection&licensePlate=THJ2G50&direction=reverse&confidenceLevel=97
    _qs = request.query_params
    _qs_plate_raw = _qs.get("licensePlate", "").strip()
    if _qs_plate_raw:
        # Palavras-chave que indicam ausência de leitura real
        _QS_EMPTY_KEYWORDS = {"noplate", "no_plate", "unknown", "none", "null", ""}
        _qs_event_type   = _qs.get("eventType", "").strip()
        _qs_channel_id   = _qs.get("channelID", "").strip()
        _qs_datetime_raw = _qs.get("dateTime", "").strip()
        _qs_direction    = _qs.get("direction", "").strip().lower() or None
        _qs_country      = _qs.get("country", "").strip()
        _qs_lane         = _qs.get("lane", "").strip()
        try:
            _qs_confidence = float(_qs.get("confidenceLevel", "").strip())
        except (ValueError, AttributeError):
            _qs_confidence = -1.0  # não informado

        # Decide se a placa é válida ou deve ser tratada como vazia
        _qs_plate_lower = _qs_plate_raw.lower()
        _qs_plate_is_empty = (
            _qs_plate_lower in _QS_EMPTY_KEYWORDS
            or _qs_confidence == 0.0
        )
        # Normaliza para maiúsculas e valida 7 chars A-Z0-9
        _qs_plate_candidate = _normalize_plate(_qs_plate_raw) if not _qs_plate_is_empty else ""

        # Só sobrescreve a placa se o XML/form não a forneceu
        if not plate and _qs_plate_candidate:
            plate = _qs_plate_candidate

        # Parse do dateTime compacto Hikvision: 20260315T112740-300
        # Formato: YYYYMMDDTHHmmss[±][H]HMM  (sem separadores)
        def _parse_hikvision_qs_datetime(dt_str: str) -> "datetime | None":
            import re as _re
            _m = _re.match(
                r"^(\d{4})(\d{2})(\d{2})T(\d{2})(\d{2})(\d{2})([+-]\d{3,4})?$",
                dt_str,
            )
            if not _m:
                return None
            yr, mo, dy, hh, mi, ss, tz_raw = _m.groups()
            tz_info = timezone.utc
            if tz_raw:
                sign = 1 if tz_raw[0] == "+" else -1
                tz_digits = tz_raw[1:]          # "300" ou "0300"
                if len(tz_digits) <= 3:         # "300" → 3h00m | "30" → 0h30m
                    tz_h = int(tz_digits[:-2]) if len(tz_digits) > 2 else 0
                    tz_m = int(tz_digits[-2:])
                else:                            # "0300" → 3h00m
                    tz_h = int(tz_digits[:2])
                    tz_m = int(tz_digits[2:])
                from datetime import timedelta as _td
                tz_info = timezone(_td(hours=sign * tz_h, minutes=sign * tz_m))
            try:
                return datetime(int(yr), int(mo), int(dy), int(hh), int(mi), int(ss), tzinfo=tz_info)
            except Exception:
                return None

        # Preenche variáveis apenas quando XML não as forneceu
        if not occurred_at and _qs_datetime_raw:
            occurred_at = _parse_hikvision_qs_datetime(_qs_datetime_raw)

        if not xml_direction and _qs_direction:
            xml_direction = _qs_direction

        if confidence < 0.0 and _qs_confidence >= 0.0:
            confidence = _qs_confidence

        # camera_id a partir do channelID da query string (usado apenas se XML não forneceu)
        _qs_camera_id_candidate = (
            request.headers.get("X-Camera-IP", "").strip()
            or _qs_channel_id
            or None
        )
        if not camera_id and _qs_camera_id_candidate:
            camera_id = _qs_camera_id_candidate
            channel_name_xml = channel_name_xml or _qs_channel_id

        # Log obrigatório exigido por requisito
        logger.info(
            "[SIMPLE-WEBHOOK-QUERY] ip=%s plate=%s channelID=%s dateTime=%s "
            "direction=%s confidence=%s eventType=%s country=%s lane=%s "
            "plate_was_empty=%s",
            client_ip,
            _qs_plate_candidate or "(vazia)",
            _qs_channel_id or "-",
            _qs_datetime_raw or "-",
            _qs_direction or "-",
            _qs_confidence if _qs_confidence >= 0 else "-",
            _qs_event_type or "-",
            _qs_country or "-",
            _qs_lane or "-",
            _qs_plate_is_empty,
        )

    # Mantém placa vazia se não houver no XML nem no form — será preenchida pelo YOLO ou permanecerá null
    # NÃO usa "UNKNOWN" para evitar poluir alertas_criticos com placas falsas

    # ── WEBHOOK-NO-XML: chegou imagem mas sem XML útil ─────────────────────────
    if images and not xml_bytes:
        logger.info(
            "[WEBHOOK-NO-XML] ip=%s content_type=%r parser=%s images=%d — imagem recebida sem XML anexo",
            client_ip, content_type, _parser_used, len(images),
        )

    logger.info(
        "[WEBHOOK] Evento recebido ip=%s content_type=%r parser=%s images=%d xml_len=%s plate=%r",
        client_ip, content_type, _parser_used, len(images),
        len(xml_bytes) if xml_bytes else 0, plate or "(vazia)",
    )
    if not plate:
        logger.warning(
            "[WEBHOOK] PLACA NÃO EXTRAÍDA ip=%s content_type=%r parser=%s — "
            "possíveis causas: campo licensePlate ausente, XML malformado, "
            "multipart/mixed não tratado (atualizar câmera para /form-data), "
            "câmera enviando HTTPS em porta HTTP (\"Invalid HTTP request received\").",
            client_ip, content_type, _parser_used,
        )
        # ── [WEBHOOK-FORM-DEBUG] logs temporários para diagnóstico de câmera HTTP-escuta ──
        logger.warning("[WEBHOOK-FORM-DEBUG] ip=%s content_type=%r parser=%s", client_ip, content_type, _parser_used)
        if _form_text_fields:
            logger.warning("[WEBHOOK-FORM-DEBUG] campos_texto recebidos: %r", list(_form_text_fields.keys()))
            for _dbg_name, _dbg_val in _form_text_fields.items():
                _dbg_preview = _dbg_val[:200] if len(_dbg_val) > 200 else _dbg_val
                if _dbg_val.strip().startswith("<"):
                    logger.warning(
                        "[WEBHOOK-FORM-DEBUG] campo XML name=%r primeiros_300=%r",
                        _dbg_name, _dbg_val[:300],
                    )
                else:
                    logger.warning(
                        "[WEBHOOK-FORM-DEBUG] campo texto name=%r valor=%r",
                        _dbg_name, _dbg_preview,
                    )
        else:
            logger.warning("[WEBHOOK-FORM-DEBUG] nenhum campo de texto no form (form vazio ou não é form-data)")
        if images:
            for _dbg_i, (_dbg_fname, _dbg_data) in enumerate(images):
                logger.warning(
                    "[WEBHOOK-FORM-DEBUG] imagem[%d] filename=%r tamanho=%d bytes",
                    _dbg_i, _dbg_fname, len(_dbg_data),
                )
        else:
            logger.warning("[WEBHOOK-FORM-DEBUG] nenhuma imagem recebida no form")
        if xml_bytes:
            logger.warning(
                "[WEBHOOK-FORM-DEBUG] xml_bytes presente len=%d primeiros_300=%r",
                len(xml_bytes), xml_bytes[:300].decode("utf-8", errors="replace"),
            )
        else:
            logger.warning("[WEBHOOK-FORM-DEBUG] xml_bytes ausente")

    # ── Resolução final de camera_id ────────────────────────────────────────
    # Prioridade obrigatória: X-Camera-IP > xml_ip > client_ip
    # channelName e channelID NUNCA definem a identidade principal quando há IP disponível.
    _header_ip = request.headers.get("X-Camera-IP", "").strip()
    if _header_ip:
        # Câmera-poller enviou o IP real via header — prioridade máxima
        camera_id = _header_ip
        xml_ip    = xml_ip or _header_ip
    elif xml_ip:
        # IP veio no XML (<ipAddress>) — confiável
        camera_id = xml_ip
    else:
        # Sem IP no XML e sem header — usa IP de origem da conexão HTTP
        camera_id = client_ip
        xml_ip    = client_ip

    logger.info(
        "[WEBHOOK-CAM-RESOLVE] client_ip=%s header_ip=%s xml_ip=%s "
        "channel_name_xml=%r channel_id_xml=%r camera_id_final=%s",
        client_ip,
        _header_ip or "-",
        xml_ip or "-",
        channel_name_xml or "-",
        channel_id_xml   or "-",
        camera_id,
    )

    if camera_id:
        # nome padrão = channelName do XML; fallback = próprio camera_id
        default_nome = channel_name_xml or camera_id
        cam = ensure_camera_exists(camera_id, default_name=default_nome, ip=xml_ip)

        # Fallback: câmera não encontrada por IP — tenta pelo channelName do XML
        if not cam.get("id") and channel_name_xml:
            cam = _lookup_camera_by_channel(channel_name_xml) or cam

        # Rejeita evento se câmera não estiver cadastrada no banco
        if not cam.get("id"):
            logger.warning(
                "[WEBHOOK] câmera não cadastrada ignorada camera_id=%s ip=%s channel=%s",
                camera_id,
                xml_ip,
                channel_name_xml,
            )
            return JSONResponse({"ok": False, "detail": f"câmera '{camera_id}' não cadastrada"}, status_code=403)

        # Usa sempre o camera_id canônico do banco (não o IP bruto do XML)
        camera_id    = cam.get("camera_id") or camera_id
        channel_name = cam.get("nome") or default_nome

    image_path = None
    # Monta lpr_meta para o worker YOLO (antes do bloco de imagem, pois pode ser usado no snapshot)
    lpr_meta: dict = {"plate": plate or ""}
    if plate_rect:
        lpr_meta["plate_rect"]   = plate_rect
    if vehicle_rect:
        lpr_meta["vehicle_rect"] = vehicle_rect
    if pic_width and pic_height:
        lpr_meta["pic_size"] = {"w": int(pic_width), "h": int(pic_height)}
    lpr_meta["coord_type"] = coord_type
    if xml_vehicle_color and xml_vehicle_color.lower() not in ("unknown", ""):
        lpr_meta["xml_vehicle_color"] = xml_vehicle_color.lower()
    if xml_vehicle_type and xml_vehicle_type.lower() not in ("unknown", ""):
        lpr_meta["xml_vehicle_type"] = xml_vehicle_type.lower()

    # Monta cam_meta com dados extras do XML para exibição no modal
    cam_meta: dict | None = None
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

    # Se não houver placa mas houver imagem, solicita OCR automático no worker
    if not plate and images:
        lpr_meta["needs_ocr"] = True

    # ── Salva imagem enviada no POST (se houver) ──────────────────────────
    # Apenas salva o arquivo em disco aqui; o job YOLO é enfileirado DEPOIS
    # do INSERT para que event_id já exista no banco quando o worker rodar.
    _yolo_jobs_pending: list[tuple[str, str]] = []   # (abs_path, image_path)
    for _img_name, data in images:
        day   = (occurred_at or _utcnow()).strftime("%Y-%m-%d")
        d     = UPLOAD_DIR / day
        d.mkdir(parents=True, exist_ok=True)
        fname = f"{uuid.uuid4().hex}.jpg"
        try:
            (d / fname).write_bytes(data)
            image_path = f"/uploads/{day}/{fname}"
            abs_path   = f"/app/uploads/{day}/{fname}"
            _yolo_jobs_pending.append((abs_path, image_path))
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
                confidence if confidence >= 0.0 else None,  # -1.0 (tag ausente) → NULL no banco
                image_path,
                occurred_at,
                event_direcao,         # direção derivada: XML direction + direcao da câmera
                _json_lib.dumps(cam_meta) if cam_meta else None,
            ))
            event_id = cur.fetchone()[0]

            logger.info(
                "[WEBHOOK] evento persistido id=%s plate=%s camera_id=%s channel=%s",
                event_id,
                plate or "(vazia)",
                camera_id,
                channel_name,
            )
            if lpr_meta.get("needs_ocr"):
                logger.info(
                    "[WEBHOOK-OCR-FALLBACK] evento id=%s enfileirado sem placa — worker tentará OCR na imagem",
                    event_id,
                )

            # ── Enfileira YOLO agora que event_id é conhecido ──────────────
            # Enfileira APÓS o INSERT para que o worker encontre o evento no banco
            # ao executar UPDATE ... WHERE id = %s. Passa event_id junto com a imagem.
            for _yolo_abs_path, _yolo_img_path in _yolo_jobs_pending:
                try:
                    _get_rq_queue().enqueue(
                        "worker.job_analyze_event",
                        _yolo_abs_path,
                        plate or "",
                        lpr_meta,
                        event_id,          # ← event_id passado para o worker usar como chave de UPDATE
                        job_timeout=120,
                    )
                    logger.info(
                        "[WEBHOOK-YOLO] job enfileirado event_id=%s path=%s",
                        event_id, _yolo_img_path,
                    )
                except Exception as _rq_err:
                    print(f"[RQ] Falha ao enfileirar job YOLO event_id={event_id}: {_rq_err}")

            # -- Classificação de placa pós-persistência --
            _diag_plate_up = (plate or "").strip().upper()
            _is_missing    = not _diag_plate_up or _diag_plate_up in ("UNKNOWN", "NONE", "NULL", "NO_PLATE", "NOPLATE")
            _is_std        = not _is_missing and _is_valid_plate_format(_diag_plate_up)
            _is_nonstd     = not _is_missing and not _is_std and _is_nonstandard_plate(_diag_plate_up)
            _is_invalid    = not _is_missing and not _is_std and not _is_nonstd

            if _is_nonstd:
                logger.info(
                    "[WEBHOOK-PLATE-NONSTANDARD] remote=%s event_id=%s plate=%r "
                    "camera_id=%s channel=%s — formato fora do padrão DENATRAN, aceito",
                    client_ip, event_id, _diag_plate_up, camera_id, channel_name,
                )
            elif _is_missing or _is_invalid:
                logger.warning(
                    "[WEBHOOK-PLATE-INVALID] remote=%s content_type=%r parser=%s "
                    "event_id=%s plate=%r camera_id=%s channel=%s has_xml=%s images=%s",
                    client_ip,
                    content_type,
                    _parser_used,
                    event_id,
                    plate or "",
                    camera_id,
                    channel_name,
                    bool(xml_bytes),
                    len(images),
                )
                if xml_bytes:
                    _xml_snippet = xml_bytes[:1200].decode("utf-8", errors="replace")
                    logger.warning(
                        "[WEBHOOK-RAW-XML] remote=%s content_type=%r parser=%s "
                        "event_id=%s plate=%r xml=%s",
                        client_ip,
                        content_type,
                        _parser_used,
                        event_id,
                        plate or "",
                        _xml_snippet,
                    )

            # Disparo automático de push: aplicar validações rígidas para evitar falsos positivos
            plate_test = plate and plate.strip()
            plate_upper = plate.strip().upper() if plate_test else ""
            is_invalid_plate = plate_upper in ("UNKNOWN", "NONE", "NULL")
            logger.info(
                "[WEBHOOK] Validação alerta event_id=%s plate_test=%s plate_upper=%s is_invalid=%s",
                event_id,
                bool(plate_test),
                plate_upper,
                is_invalid_plate,
            )

            if not plate_test or is_invalid_plate:
                logger.warning(
                    "[WEBHOOK] Alerta NÃO disparado: placa vazia/inválida (event_id=%s plate=%s). Aguardando YOLO ou disparo manual.",
                    event_id,
                    plate or "(vazia)",
                )
            else:
                plate_normalized = normalize_plate(plate)

                # Classifica formato: padrão (AAA1234/AAA1A23), não-padrão (RAN001), inválido
                _plate_is_std    = _is_valid_plate_format(plate_normalized)
                _plate_is_nonstd = not _plate_is_std and _is_nonstandard_plate(plate_normalized)
                _plate_is_inv    = not _plate_is_std and not _plate_is_nonstd

                if _plate_is_inv:
                    logger.warning(
                        "[WEBHOOK-PLATE-INVALID] Alerta descartado: formato inválido "
                        "event_id=%s plate=%r",
                        event_id,
                        plate_normalized,
                    )
                else:
                    if _plate_is_nonstd:
                        logger.info(
                            "[WEBHOOK-PLATE-NONSTANDARD] Placa fora do padrão DENATRAN aceita "
                            "para alerta event_id=%s plate=%r",
                            event_id,
                            plate_normalized,
                        )
                    try:
                        conf_val = float(confidence) if confidence >= 0.0 else None
                    except Exception:
                        conf_val = None

                    # confidence=-1 significa "tag ausente na câmera" → não penaliza
                    if conf_val is not None and conf_val < MIN_PLATE_CONF:
                        logger.warning(
                            "[WEBHOOK] Alerta descartado por baixa confiança event_id=%s plate=%s conf=%.3f min_required=%.3f",
                            event_id,
                            plate_normalized,
                            conf_val,
                            MIN_PLATE_CONF,
                        )
                    else:
                        logger.info(
                            "[WEBHOOK] Chamando send_alert_for_detected_plate event_id=%s plate=%s",
                            event_id,
                            plate_normalized,
                        )
                        try:
                            alerta_enviado = await send_alert_for_detected_plate(
                                db_cur=cur,
                                plate=plate_normalized,
                                camera_name=(cam.get("nome") if isinstance(cam, dict) else None) or (camera_id or channel_name or "Camera"),
                                image_url=image_path or "",
                                confidence=float(confidence or 0),
                                event_id=str(event_id),
                                city="N/A",
                            )
                            logger.info(
                                "[WEBHOOK] send_alert_for_detected_plate retornou %s para event_id=%s",
                                alerta_enviado,
                                event_id,
                            )
                        except Exception as _fcm_err:
                            logger.exception("[FCM] EXCEÇÃO no auto-disparo do alerta event_id=%s: %s", event_id, _fcm_err)

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
    """Retorna todos os veículos cadastrados agrupados por placa com suas listas.
    Alarme é determinado pela tabela 'alarmes' (via alarme_listas), não por vehicle_lists."""
    try:
        with _conn() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT DISTINCT vli.plate, vl.id, vl.name
                    FROM vehicle_list_items vli
                    JOIN vehicle_lists vl ON vl.id = vli.list_id
                    ORDER BY vli.plate
                """)
                rows = cur.fetchall()

                # Buscar listas que possuem alarmes ativos (alarmes.ativo = TRUE)
                cur.execute("""
                    SELECT al.lista_id, a.prioridade
                    FROM alarme_listas al
                    JOIN alarmes a ON a.id = al.alarme_id
                    WHERE a.ativo = TRUE
                """)
                alarm_map = {}
                for lista_id, prioridade in cur.fetchall():
                    # Mapear prioridade para som
                    sound = {"critica": "urgent", "alta": "siren", "media": "beep", "baixa": "bell"}.get(prioridade, "beep")
                    # Manter a maior prioridade por lista
                    prio_order = {"critica": 4, "alta": 3, "media": 2, "baixa": 1}
                    existing = alarm_map.get(lista_id)
                    if not existing or prio_order.get(prioridade, 0) > prio_order.get(existing[0], 0):
                        alarm_map[lista_id] = (prioridade, sound)

        plates = {}
        for plate, list_id, list_name in rows:
            if plate not in plates:
                plates[plate] = []
            alarm_info = alarm_map.get(list_id)
            plates[plate].append({
                "list_id": list_id,
                "list_name": list_name,
                "alarm_enabled": alarm_info is not None,
                "alarm_sound": alarm_info[1] if alarm_info else "beep",
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
                    SELECT vl.id, vl.name,
                           vl.created_at, vl.updated_at,
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
                "created_at": r[2].isoformat() if r[2] else None,
                "updated_at": r[3].isoformat() if r[3] else None,
                "vehicle_count": int(r[4] or 0)
            })
        return {"items": items}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/vehicles/lists")
async def vehicles_lists_create(request: Request):
    """Cria uma nova lista de monitoramento."""
    # Admin e operador podem criar listas
    assert_admin_or_operator(request, "Apenas administradores e operadores podem criar listas")
    try:
        data = await request.json()
        name = (data.get("name") or "").strip()
        
        if not name:
            raise HTTPException(status_code=400, detail="name é obrigatório e não pode ser vazio")
        
        with _conn() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    INSERT INTO vehicle_lists (name)
                    VALUES (%s)
                    RETURNING id, created_at, updated_at
                """, (name,))
                r = cur.fetchone()
        
        return {
            "id": r[0],
            "name": name,
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
    # Admin e operador podem editar listas
    assert_admin_or_operator(request, "Apenas administradores e operadores podem editar listas")
    try:
        data = await request.json()
        name = (data.get("name") or "").strip()
        
        if not name:
            raise HTTPException(status_code=400, detail="name é obrigatório e não pode ser vazio")
        
        with _conn() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT id FROM vehicle_lists WHERE id = %s", (list_id,))
                if not cur.fetchone():
                    raise HTTPException(status_code=404, detail="Lista não encontrada")
                
                cur.execute("""
                    UPDATE vehicle_lists
                    SET name = %s, updated_at = NOW()
                    WHERE id = %s
                    RETURNING id, name, created_at, updated_at
                """, (name, list_id))
                r = cur.fetchone()
                if not r:
                    raise HTTPException(status_code=404, detail="Lista não encontrada")
        
        return {
            "id": r[0],
            "name": r[1],
            "created_at": r[2].isoformat() if r[2] else None,
            "updated_at": r[3].isoformat() if r[3] else None,
            "vehicle_count": 0
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.delete("/api/vehicles/lists/{list_id}")
def vehicles_lists_delete(list_id: int, request: Request):
    """Deleta uma lista e todos seus veículos."""
    # Admin e operador podem deletar listas
    assert_admin_or_operator(request, "Apenas administradores e operadores podem deletar listas")
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
            SELECT vli.id, vli.plate, vli.list_id, vl.name as list_name, 
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
                "notes": r[4],
                "created_at": r[5].isoformat() if r[5] else None
            })
        
        return {"items": items, "total": len(items)}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/vehicles")
async def vehicles_create(request: Request):
    """Adiciona um veículo a uma lista."""
    # Admin e operador podem criar/adicionar veículos
    assert_admin_or_operator(request, "Apenas administradores e operadores podem adicionar veículos")
    try:
        data = await request.json()
        
        # Extrair e limpar cada campo individualmente com segurança
        plate_raw = data.get("plate")
        if plate_raw is None or plate_raw == "":
            raise HTTPException(status_code=400, detail="plate é obrigatório")
        plate = _normalize_plate(str(plate_raw))
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


@app.put("/api/vehicles/{vid}")
async def vehicles_update(vid: int, request: Request):
    """Atualiza um veículo (placa e/ou notas)."""
    # Admin e operador podem atualizar veículos
    assert_admin_or_operator(request, "Apenas administradores e operadores podem atualizar veículos")
    try:
        data = await request.json()
        plate_raw = data.get("plate")
        notes_raw = data.get("notes")
        
        plate = None
        if plate_raw is not None:
            plate = _normalize_plate(str(plate_raw))
            if not plate:
                raise HTTPException(status_code=400, detail="plate não pode ser vazio")
        
        notes = None
        if notes_raw:
            notes = str(notes_raw).strip()
            if not notes:
                notes = None
        
        with _conn() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT id, list_id, plate FROM vehicle_list_items WHERE id = %s", (vid,))
                row = cur.fetchone()
                if not row:
                    raise HTTPException(status_code=404, detail="Veículo não encontrado")
                
                list_id, old_plate = row[1], row[2]
                
                # Se a placa mudou, verifica duplicação
                if plate and plate != old_plate:
                    cur.execute("SELECT id FROM vehicle_list_items WHERE list_id = %s AND plate = %s AND id != %s", 
                               (list_id, plate, vid))
                    if cur.fetchone():
                        raise HTTPException(status_code=409, detail="Placa já existe nesta lista")
                
                updates = []
                params = []
                if plate:
                    updates.append("plate = %s")
                    params.append(plate)
                if notes_raw is not None:
                    updates.append("notes = %s")
                    params.append(notes)
                
                if not updates:
                    raise HTTPException(status_code=400, detail="Nenhum campo para atualizar")
                
                params.append(vid)
                cur.execute(f"UPDATE vehicle_list_items SET {', '.join(updates)} WHERE id = %s", params)
        
        return {"ok": True, "id": vid}
    except HTTPException:
        raise
    except Exception as e:
        import traceback
        tb = traceback.format_exc()
        raise HTTPException(status_code=500, detail=f"Erro: {str(e)}. Traceback: {tb}")


@app.delete("/api/vehicles/{vid}")
def vehicles_delete(vid: int, request: Request):
    """Remove um veículo de uma lista."""
    # Admin e operador podem deletar veículos
    assert_admin_or_operator(request, "Apenas administradores e operadores podem deletar veículos")
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
    plate = _normalize_plate(plate)
    old_plate = _normalize_plate(old_plate) if old_plate else None
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
    plate = _normalize_plate(plate)
    cur.execute("SELECT id FROM vehicle_lists WHERE name = %s", (ALVOS_LIST_NAME,))
    row = cur.fetchone()
    if row:
        cur.execute(
            "DELETE FROM vehicle_list_items WHERE list_id = %s AND plate = %s",
            (row[0], plate)
        )


@app.post("/api/alvos")
async def alvos_create(request: Request):
    # Admin e operador podem criar alvos
    assert_admin_or_operator(request, "Apenas administradores e operadores podem criar alvos")
    data = await request.json()
    plate = _normalize_plate(data.get("plate") or "")
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
def alvos_delete(aid: int, request: Request):
    # Apenas admin pode deletar alvos
    assert_admin(request, "Apenas administradores podem deletar alvos")
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
    # Admin e operador podem editar alvos
    assert_admin_or_operator(request, "Apenas administradores e operadores podem editar alvos")
    body = await request.json()
    plate    = _normalize_plate(body.get("plate") or "")
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
def alvos_import_list(list_id: int, request: Request):
    """Importa todas as placas de uma lista de monitoramento como Alvos Rastreados."""
    # Admin e operador podem importar alvos
    assert_admin_or_operator(request, "Apenas administradores e operadores podem importar alvos")
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
                    (_normalize_plate(plate), desc),
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
    co_window: int = 300,
    min_cameras: int = 2,
    trip_max: int = 3600,
    limit: int = 20,
):
    """
    Retorna os acompanhantes detectados para a placa informada usando o
    algoritmo unificado de comboio (_detect_convoy_groups).

    Regras:
      - co_window (1..1000): janela de co-detecção por câmera
      - min_cameras (default 2): mínimo de câmeras distintas
      - trip_max (default 3600): viagem máxima em segundos

    Resposta:
      companions[].companion          – placa do acompanhante
      companions[].cameras_together   – qtd de câmeras distintas onde apareceram juntos
      companions[].trip_span_sec      – span da viagem (s)
      companions[].last_seen          – timestamp mais recente
      companions[].companion_leads    – nº de vezes que o acompanhante chegou ANTES
      companions[].target_leads       – nº de vezes que a placa alvo chegou antes
      companions[].evidence[]         – lista de passagens por câmera (cameras_confirmed)
    """
    co_win_s   = max(1, min(1000, int(co_window)))
    min_cam    = max(1, int(min_cameras))
    trip_max_s = max(1, int(trip_max))
    window_min = _parse_window_to_minutes(window)
    lim        = max(1, min(100, int(limit)))
    t_to       = _utcnow()
    t_from     = t_to - timedelta(minutes=window_min)
    plate      = (plate or "").strip().upper()
    if not plate:
        return {"companions": []}

    with _conn() as conn:
        with conn.cursor() as cur:
            groups = _detect_convoy_groups(
                cur, t_from, t_to,
                window_s=co_win_s,
                max_trip_gap_s=trip_max_s,
                min_cameras=min_cam,
                target_plate=plate,
            )

    # Transforma grupos em lista de companions (perspectiva do plate)
    result = []
    for g in groups:
        other_plates = [p for p in g["plates"] if p != plate]
        for comp in other_plates:
            # Calcular leads a partir de cameras_confirmed (plate_order)
            companion_leads = 0
            target_leads = 0
            evidence = []
            for cam in g.get("cameras_confirmed", []):
                order = cam.get("plate_order", [])
                if plate in order and comp in order:
                    idx_t = order.index(plate)
                    idx_c = order.index(comp)
                    if idx_c < idx_t:
                        companion_leads += 1
                    elif idx_t < idx_c:
                        target_leads += 1
                evidence.append({
                    "camera":       cam.get("cam_nome", cam.get("camera_id", "")),
                    "camera_id":    cam.get("camera_id", ""),
                    "ts_target":    cam.get("ts_min"),
                    "ts_companion": cam.get("ts_max"),
                    "co_delta_sec": cam.get("span_sec", 0),
                    "plate_order":  order,
                })

            result.append({
                "companion":        comp,
                "cameras_together": g["cameras_count"],
                "trip_span_sec":    g["trip_span_sec"],
                "avg_co_delta_sec": int(sum(e["co_delta_sec"] for e in evidence) / len(evidence)) if evidence else 0,
                "last_seen":        g["last_seen"],
                "companion_leads":  companion_leads,
                "target_leads":     target_leads,
                "evidence":         evidence[:20],
                "yolo_multi_events": 0,
            })

    result.sort(key=lambda x: x["cameras_together"], reverse=True)
    return {"companions": result[:lim]}


# ===========================
# BATEDOR — TRAJETO (percurso conjunto)
# ===========================

def _haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Distância em km entre dois pontos geográficos (Haversine)."""
    import math
    R = 6371.0
    dLat = math.radians(lat2 - lat1)
    dLon = math.radians(lon2 - lon1)
    a = (math.sin(dLat / 2) ** 2
         + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2))
         * math.sin(dLon / 2) ** 2)
    return R * 2 * math.asin(math.sqrt(a))


@app.get("/api/batedor/trajeto/{plate}")
def batedor_trajeto(
    plate: str,
    window: str = "24h",
    co_window: int = 600,
    min_cameras: int = 2,
    limit: int = 30,
    # ── Filtros do suspeito ──────────────────────────────────────────────────
    direcao: Optional[str] = None,         # CRESCENTE | DECRESCENTE | ENTRADA | SAÍDA
    vehicle_type: Optional[str] = None,    # car | motorcycle | pickup | truck | bus | van
    vehicle_color: Optional[str] = None,   # Preto | Branco | Prata | Cinza | Vermelho ...
    plate_prefix: Optional[str] = None,    # prefixo parcial da placa do suspeito (ex: ABC)
):
    """
    Identifica veículos que fizeram o mesmo percurso junto ao <plate>.

    Filtros do suspeito:
    - direcao: filtra câmeras com essa direção configurada (CRESCENTE/DECRESCENTE/ENTRADA/SAÍDA)
    - vehicle_type: tipo de veículo detectado pelo YOLO (car/motorcycle/pickup/truck/bus/van)
    - vehicle_color: cor detectada pelo YOLO (Preto/Branco/Prata/Cinza/Vermelho/Azul...)
    - plate_prefix: prefixo parcial da placa do suspeito (ex: "ABC" filtra ABC1234, ABC5E59...)
    """
    from collections import defaultdict

    co_win_s   = max(10, int(co_window))
    window_min = _parse_window_to_minutes(window)
    min_cam    = max(1, int(min_cameras))
    lim        = max(1, min(200, int(limit)))
    t_to       = _utcnow()
    t_from     = t_to - timedelta(minutes=window_min)
    plate      = (plate or "").strip().upper()
    if not plate:
        raise HTTPException(status_code=400, detail="Placa não informada")

    # ── Monta cláusulas extras de WHERE ─────────────────────────────────────
    extra_where: list[str] = []
    extra_vals:  list      = []

    if plate_prefix:
        prefix_clean = plate_prefix.strip().upper()
        extra_where.append("AND b.plate ILIKE %s")
        extra_vals.append(prefix_clean + "%")

    if direcao:
        extra_where.append("AND UPPER(COALESCE(NULLIF(c.direcao,''), '')) = UPPER(%s)")
        extra_vals.append(direcao.strip())

    extra_sql = "\n                  ".join(extra_where)

    with _conn() as conn:
        with conn.cursor() as cur:
            cur.execute(f"""
                SELECT
                    b.plate                                              AS companion,
                    a.camera_id                                          AS camera_id,
                    COALESCE(a.occurred_at, a.ts)                        AS ts_target,
                    COALESCE(b.occurred_at, b.ts)                        AS ts_companion,
                    ABS(EXTRACT(EPOCH FROM (
                        COALESCE(b.occurred_at, b.ts) - COALESCE(a.occurred_at, a.ts)
                    )))::int                                              AS delta_sec,
                    COALESCE(c.nome, a.camera_id)                        AS cam_nome,
                    c.latitude                                           AS lat,
                    c.longitude                                          AS lon,
                    b.image_path                                         AS companion_image,
                    COALESCE(b.confidence, 0.0)                          AS companion_confidence,
                    COALESCE(
                        NULLIF(b.yolo_result->'target_vehicle'->>'tipo_raw', ''),
                        NULLIF(b.cam_meta->>'vehicle_type', ''),
                        ''
                    )                                                    AS companion_vtype,
                    COALESCE(
                        NULLIF(b.yolo_result->'target_vehicle'->>'cor', ''),
                        ''
                    )                                                    AS companion_color
                FROM lpr_events a
                JOIN lpr_events b
                    ON  a.camera_id = b.camera_id
                    AND a.id        != b.id
                    AND b.plate     != a.plate
                    AND b.plate     IS NOT NULL
                    AND b.plate     NOT IN ('', 'unknown', 'UNKNOWN')
                    AND ABS(EXTRACT(EPOCH FROM (
                            COALESCE(b.occurred_at, b.ts) - COALESCE(a.occurred_at, a.ts)
                        ))) <= %s
                LEFT JOIN cameras c ON c.id = (
                    SELECT id FROM cameras
                    WHERE camera_id = a.camera_id
                       OR ip        = a.camera_id
                       OR ip        = a.camera_ip
                    ORDER BY (camera_id = a.camera_id) DESC
                    LIMIT 1
                )
                WHERE a.plate = %s
                  AND COALESCE(a.occurred_at, a.ts) BETWEEN %s AND %s
                  {extra_sql}
                ORDER BY COALESCE(a.occurred_at, a.ts) ASC
                LIMIT 10000
            """, [co_win_s, plate, t_from, t_to] + extra_vals)
            rows = cur.fetchall()

    # ── Agrupamento por companheiro ──────────────────────────────────────────
    comp: dict = defaultdict(lambda: {
        "passages":   [],
        "last_image": None,
        "max_conf":   0.0,
        "vtypes":     [],   # tipos coletados por passagem
        "colors":     [],   # cores coletadas por passagem
    })

    for row in rows:
        companion, camera_id, ts_t, ts_c, delta_sec, cam_nome, lat, lon, img, conf, vtype, color = row
        cd = comp[companion]
        cd["passages"].append({
            "camera_id":    camera_id,
            "cam_nome":     cam_nome or camera_id,
            "ts_target":    ts_t.isoformat() if ts_t else None,
            "ts_companion": ts_c.isoformat() if ts_c else None,
            "delta_sec":    int(delta_sec),
            "lat":          float(lat)   if lat   is not None else None,
            "lon":          float(lon)   if lon   is not None else None,
            "vtype":        vtype  or None,
            "color":        color  or None,
        })
        if img:
            cd["last_image"] = img
        if float(conf) > cd["max_conf"]:
            cd["max_conf"] = float(conf)
        if vtype:
            cd["vtypes"].append(vtype.lower())
        if color:
            cd["colors"].append(color)

    # ── Métricas e pós-filtros por companheiro ───────────────────────────────
    from collections import Counter
    result = []
    for companion, cd in comp.items():

        # ── Pós-filtro: tipo de veículo ──────────────────────────────────────
        if vehicle_type:
            vt_clean = vehicle_type.strip().lower()
            if not any(vt_clean in v for v in cd["vtypes"]):
                continue

        # ── Pós-filtro: cor do veículo ───────────────────────────────────────
        if vehicle_color:
            vc_lower = vehicle_color.strip().lower()
            if not any(vc_lower in c.lower() for c in cd["colors"]):
                continue

        # Deduplica câmeras — mantém a de menor delta_sec por câmera
        best: dict = {}
        for p in cd["passages"]:
            cid = p["camera_id"]
            if cid not in best or p["delta_sec"] < best[cid]["delta_sec"]:
                best[cid] = p
        deduped = sorted(best.values(), key=lambda x: x["ts_target"] or "")

        cameras_together = len(deduped)
        if cameras_together < min_cam:
            continue

        # Tipo e cor mais frequentes do suspeito
        dominant_vtype = Counter(cd["vtypes"]).most_common(1)[0][0] if cd["vtypes"] else None
        dominant_color = Counter(cd["colors"]).most_common(1)[0][0] if cd["colors"] else None

        # Distância total do percurso (Haversine, câmeras com coordenadas)
        route_distance_km = 0.0
        pts = [p for p in deduped if p["lat"] is not None and p["lon"] is not None]
        for i in range(1, len(pts)):
            route_distance_km += _haversine_km(pts[i-1]["lat"], pts[i-1]["lon"], pts[i]["lat"], pts[i]["lon"])

        # Delta médio entre os dois veículos
        deltas = [p["delta_sec"] for p in deduped]
        avg_delta_sec = int(sum(deltas) / len(deltas)) if deltas else 0

        # Tempo de percurso do alvo (primeira→última câmera)
        ts_target_list = [p["ts_target"] for p in deduped if p["ts_target"]]
        travel_time_target_sec = 0
        if len(ts_target_list) >= 2:
            t0 = datetime.fromisoformat(ts_target_list[0])
            t1 = datetime.fromisoformat(ts_target_list[-1])
            travel_time_target_sec = max(0, int((t1 - t0).total_seconds()))

        # Tempo de percurso do companheiro
        ts_comp_list = [p["ts_companion"] for p in deduped if p["ts_companion"]]
        travel_time_companion_sec = 0
        if len(ts_comp_list) >= 2:
            t0c = datetime.fromisoformat(ts_comp_list[0])
            t1c = datetime.fromisoformat(ts_comp_list[-1])
            travel_time_companion_sec = max(0, int((t1c - t0c).total_seconds()))

        # Score de suspeição
        suspicion_score = cameras_together * 100 - avg_delta_sec // 10

        result.append({
            "companion":                 companion,
            "cameras_together":          cameras_together,
            "route_distance_km":         round(route_distance_km, 2),
            "avg_delta_sec":             avg_delta_sec,
            "travel_time_target_sec":    travel_time_target_sec,
            "travel_time_companion_sec": travel_time_companion_sec,
            "suspicion_score":           suspicion_score,
            "vehicle_type":              dominant_vtype,
            "vehicle_color":             dominant_color,
            "first_seen":                deduped[0]["ts_target"]  if deduped else None,
            "last_seen":                 deduped[-1]["ts_target"] if deduped else None,
            "last_companion_image":      cd["last_image"],
            "last_confidence":           round(cd["max_conf"], 3),
            "evidence":                  deduped,
        })

    result.sort(key=lambda x: x["suspicion_score"], reverse=True)
    return {
        "plate":      plate,
        "window":     window,
        "co_window":  co_win_s,
        "companions": result[:lim],
        "total":      len(result),
    }


# ===========================
# BATEDOR — GRUPOS EM COMBOIO
# ===========================

@app.get("/api/batedor/grupos_comboio")
def batedor_grupos_comboio(
    window:              str   = "2h",
    co_window:           int   = 300,      # segundos: janela por câmera (1..1000)
    group_sizes:         str   = "2",      # "2" (exatamente 2) ou "3+" (3 ou mais)
    min_cameras:         int   = 2,        # mín câmeras p/ grupo (fixo >= 2)
    max_trip_gap:        int   = 3600,     # máx span viagem entre câmeras (s)
    order_mode:          str   = "any",    # "any" | "leader_front"
    leader_ratio:        float = 0.7,      # líder 1º em >= 70% das câmeras
    max_front_ratio_other: float = 0.3,    # outro membro 1º em <= 30%
    payload_max_front:   int   = 0,        # grupo=3: payload 1º em ≤ N câmeras
    limit:               int   = 100,
    request:             Request = None,
):
    """
    Detecta grupos de veículos em comboio.

    Regras:
      A) Co-detecção: TODOS do grupo na mesma câmera, span <= co_window.
      B) Comboio suspeito: válido em >= min_cameras câmeras E trip_span <= max_trip_gap.

    order_mode:
      - "any"           → aceita qualquer ordem entre câmeras
      - "leader_front"  → exige líder (batedor) consistente na frente
    """
    from collections import Counter

    # ── Valida parâmetros ──────────────────────────────────────────────────────
    allowed_params = {
        'window', 'co_window', 'group_sizes', 'min_cameras', 'max_trip_gap',
        'order_mode', 'leader_ratio', 'max_front_ratio_other',
        'payload_max_front', 'limit',
    }
    if request:
        unsupported = set(request.query_params.keys()) - allowed_params
        if unsupported:
            raise HTTPException(
                status_code=400,
                detail=f"Parâmetros não suportados: {', '.join(sorted(unsupported))}. "
                       f"Use apenas: {', '.join(sorted(allowed_params))}"
            )

    # ── Parseia group_sizes ────────────────────────────────────────────────────
    # Valores aceitos: "2" (exatamente 2), "3+" (3 ou mais), "3" (legacy → equivale a 3+)
    valid_sizes: set = set()
    allow_3plus = False
    for s in str(group_sizes).split(","):
        s = s.strip()
        if s == "2":
            valid_sizes.add(2)
        elif s in ("3+", "3"):
            allow_3plus = True
    if not valid_sizes and not allow_3plus:
        valid_sizes = {2}

    order = str(order_mode).strip().lower()
    if order not in ("any", "leader_front"):
        order = "any"

    lr           = max(0.0, min(1.0, float(leader_ratio)))
    mfr_other    = max(0.0, min(1.0, float(max_front_ratio_other)))
    p_max_front  = max(0, int(payload_max_front))

    window_min = _parse_window_to_minutes(window)
    co_win_s   = max(1, min(1000, int(co_window)))
    min_cam    = max(2, int(min_cameras))
    trip_gap   = max(1, int(max_trip_gap))
    lim        = max(1, min(500, int(limit)))
    t_to       = _utcnow()
    t_from     = t_to - timedelta(minutes=window_min)

    with _conn() as conn:
        with conn.cursor() as cur:
            raw_groups = _detect_convoy_groups(
                cur, t_from, t_to,
                window_s=co_win_s,
                max_trip_gap_s=trip_gap,
                min_cameras=min_cam,
            )

    # ── Filtra por group_sizes ─────────────────────────────────────────────
    # "2" = exatamente 2 veículos; "3+" = 3 ou mais veículos (quantidade_veiculos >= 3)
    if allow_3plus:
        raw_groups = [g for g in raw_groups if g["group_size"] in valid_sizes or g["group_size"] >= 3]
    else:
        raw_groups = [g for g in raw_groups if g["group_size"] in valid_sizes]

    # ── Aplica análise de liderança e filtro order_mode ────────────────────
    groups: list = []
    for g in raw_groups:
        cameras_confirmed = g["cameras_confirmed"]
        cameras_count = g["cameras_count"]
        plates_set = set(g["plates"])
        gs = g["group_size"]

        # Contagem de liderança (primeira placa em cada câmera)
        front_count: dict = Counter()
        for cam in cameras_confirmed:
            if cam["plate_order"]:
                front_count[cam["plate_order"][0]] += 1

        leader_plate = front_count.most_common(1)[0][0] if front_count else g["plates"][0]
        leader_front_cnt = front_count.get(leader_plate, 0)
        leader_ratio_val = leader_front_cnt / cameras_count if cameras_count else 0

        # Filtro leader_front
        if order == "leader_front":
            if leader_ratio_val < lr:
                continue
            skip = False
            for plate in plates_set:
                if plate == leader_plate:
                    continue
                other_ratio = front_count.get(plate, 0) / cameras_count if cameras_count else 0
                if other_ratio > mfr_other:
                    skip = True
                    break
            if skip:
                continue
            if gs == 3:
                payload_plate = min(
                    (p for p in plates_set if p != leader_plate),
                    key=lambda p: front_count.get(p, 0)
                )
                if front_count.get(payload_plate, 0) > p_max_front:
                    continue

        # Papéis
        roles = {}
        sorted_by_front = sorted(plates_set, key=lambda p: front_count.get(p, 0), reverse=True)
        roles[sorted_by_front[0]] = "leader"
        if gs == 2:
            roles[sorted_by_front[1]] = "follower"
        elif gs == 3:
            roles[sorted_by_front[-1]] = "payload"
            mid = [p for p in sorted_by_front if p not in (sorted_by_front[0], sorted_by_front[-1])]
            if mid:
                roles[mid[0]] = "middle"

        plate_stats = []
        for p in sorted(plates_set):
            plate_stats.append({
                "plate":       p,
                "front_count": front_count.get(p, 0),
                "front_ratio": round(front_count.get(p, 0) / cameras_count, 3) if cameras_count else 0,
                "role":        roles.get(p, "member"),
            })

        g["leader"] = leader_plate
        g["leader_front_count"] = leader_front_cnt
        g["leader_ratio"] = round(leader_ratio_val, 3)
        g["plate_stats"] = plate_stats
        groups.append(g)

    groups.sort(key=lambda g: (g["cameras_count"], g.get("leader_ratio", 0), g["group_size"]), reverse=True)
    # Monta echo do filtro de grupo para a resposta
    sizes_echo = sorted(str(s) for s in valid_sizes)
    if allow_3plus:
        sizes_echo.append("3+")
    return {
        "groups":       groups[:lim],
        "total":        len(groups),
        "window":       window,
        "co_window":    co_win_s,
        "group_sizes":  sizes_echo,
        "min_cameras":  min_cam,
        "max_trip_gap_s": trip_gap,
        "order_mode":   order,
        "leader_ratio_threshold": lr,
    }


# ===========================
# BATEDOR — ENDPOINTS REAIS
# ===========================

def _detect_convoy_groups(
    cur,
    t_from,
    t_to,
    window_s: int = 300,
    max_trip_gap_s: int = 3600,
    min_cameras: int = 2,
    target_plate: str | None = None,
    prefix_sql: str = "",
    prefix_vals: list | None = None,
    allow_sql: str = "",
    allow_vals: list | None = None,
    limit_events: int = 50000,
) -> list[dict]:
    """
    Algoritmo unificado de detecção de comboio.

    Regras:
      A) Co-detecção por câmera: TODOS os veículos do grupo devem ter eventos
         na mesma câmera e span(max_ts - min_ts) <= window_s.
      B) Comboio suspeito: grupo válido em >= min_cameras câmeras distintas,
         e trip_span (entre 1ª e última câmera confirmada) <= max_trip_gap_s.

    Parâmetros:
      - window_s: janela de co-detecção por câmera (1..1000, será clamped)
      - max_trip_gap_s: máximo span da viagem entre câmeras (default 3600 = 1h)
      - min_cameras: mínimo de câmeras distintas (default 2)
      - target_plate: se fornecido, retorna apenas grupos que contêm essa placa
      - prefix_sql/allow_sql: fragmentos SQL extras para filtro

    Retorna lista de dicts:
      [{
        "plates": ["A","B"], "group_size": 2,
        "cameras_count": 3, "cameras": [...],
        "cameras_confirmed": [{ "camera_id", "cam_nome", "ts_min", "ts_max",
                                "span_sec", "plate_order" }],
        "trip_span_sec": 1800,
        "first_seen": "...", "last_seen": "...",
      }]
    """
    from collections import defaultdict
    from itertools import combinations

    window_s = max(1, min(1000, int(window_s)))
    max_trip_gap_s = max(1, int(max_trip_gap_s))
    min_cameras = max(1, int(min_cameras))
    prefix_vals = prefix_vals or []
    allow_vals = allow_vals or []

    # ── 1. Buscar eventos ──────────────────────────────────────────────────
    target_sql = ""
    target_vals: list = []
    if target_plate:
        # Busca eventos da placa alvo + de qualquer placa na mesma câmera/período
        # Para eficiência, primeiro identifica as câmeras onde a placa alvo aparece
        pass  # Sem filtro de placa — precisamos de todos os veículos para formar clusters

    cur.execute(f"""
        SELECT
            e.camera_id,
            COALESCE(c.nome, e.camera_id)   AS cam_nome,
            e.plate,
            COALESCE(e.occurred_at, e.ts)   AS event_time
        FROM lpr_events e
        LEFT JOIN cameras c ON c.id = (
            SELECT id FROM cameras
            WHERE camera_id = e.camera_id
               OR ip        = e.camera_id
               OR ip        = e.camera_ip
            ORDER BY (camera_id = e.camera_id) DESC
            LIMIT 1
        )
        WHERE e.plate IS NOT NULL
          AND e.plate NOT IN ('', 'unknown', 'UNKNOWN')
          AND COALESCE(e.occurred_at, e.ts) BETWEEN %s AND %s
          {prefix_sql} {allow_sql}
        ORDER BY e.camera_id, COALESCE(e.occurred_at, e.ts)
        LIMIT {int(limit_events)}
    """, [t_from, t_to] + prefix_vals + allow_vals)
    rows = cur.fetchall()

    # ── 2. Agrupar por câmera ──────────────────────────────────────────────
    cam_events: dict = defaultdict(list)
    for cam_id, cam_nome, plate, event_time in rows:
        cam_events[cam_id].append((plate, event_time, cam_nome))

    # ── 3. Formar clusters por câmera (janela deslizante) ──────────────────
    # Para cada câmera, encontra conjuntos de placas onde span <= window_s
    # Resultado: cam_plate_sets[camera_id] = [{"plates": frozenset, "ts_min", "ts_max", "plate_times"}]
    cam_plate_sets: dict = defaultdict(list)

    for cam_id, events in cam_events.items():
        n = len(events)
        if n < 2:
            continue
        cam_nome = events[0][2]

        # Janela deslizante: i=início, j avança enquanto span <= window_s
        i = 0
        while i < n:
            j = i + 1
            while j < n and (events[j][1] - events[i][1]).total_seconds() <= window_s:
                j += 1
            # events[i..j-1] formam um cluster temporal
            # Extrair placas únicas e seus timestamps
            plate_times: dict = {}
            for k in range(i, j):
                p, t, _ = events[k]
                if p not in plate_times:
                    plate_times[p] = {"min": t, "max": t}
                else:
                    if t < plate_times[p]["min"]:
                        plate_times[p]["min"] = t
                    if t > plate_times[p]["max"]:
                        plate_times[p]["max"] = t

            unique_plates = set(plate_times.keys())
            if len(unique_plates) >= 2:
                all_ts = [t for k in range(i, j) for t in [events[k][1]]]
                ts_min = min(all_ts)
                ts_max = max(all_ts)
                cam_plate_sets[cam_id].append({
                    "plates": frozenset(unique_plates),
                    "ts_min": ts_min,
                    "ts_max": ts_max,
                    "span_sec": (ts_max - ts_min).total_seconds(),
                    "cam_nome": cam_nome,
                    "plate_times": plate_times,
                })
            i += 1

    # ── 4. Enumerar subconjuntos de >= 2 placas e contar câmeras ───────────
    # Para cada subconjunto de placas (tamanho >= 2) que aparece num cluster,
    # verificar em quantas câmeras distintas aparece.
    # group_cameras: { frozenset(plates) -> [{ "camera_id", "cam_nome", "ts_rep", ... }] }
    group_cameras: dict = defaultdict(list)

    for cam_id, clusters in cam_plate_sets.items():
        for cluster in clusters:
            all_plates = cluster["plates"]
            # Para eficiência, gerar subconjuntos de tamanho 2 e 3
            for size in (2, 3):
                if len(all_plates) < size:
                    continue
                for subset in combinations(sorted(all_plates), size):
                    subset_key = frozenset(subset)
                    # Verifica que TODOS os veículos do subset estão no cluster
                    # (já estão, pois vieram de all_plates)
                    # Calcula span apenas para o subset
                    sub_times = []
                    sub_plate_times = {}
                    for p in subset:
                        pt = cluster["plate_times"][p]
                        sub_times.append(pt["min"])
                        sub_times.append(pt["max"])
                        sub_plate_times[p] = pt
                    sub_ts_min = min(sub_times)
                    sub_ts_max = max(sub_times)
                    sub_span = (sub_ts_max - sub_ts_min).total_seconds()
                    if sub_span > window_s:
                        continue
                    # Ordena por primeiro timestamp
                    plate_order = sorted(subset, key=lambda p: sub_plate_times[p]["min"])
                    # Timestamp representativo do grupo nesta câmera = min(ts)
                    ts_rep = sub_ts_min
                    group_cameras[subset_key].append({
                        "camera_id": cam_id,
                        "cam_nome": cluster["cam_nome"],
                        "ts_min": sub_ts_min,
                        "ts_max": sub_ts_max,
                        "span_sec": int(sub_span),
                        "plate_order": plate_order,
                        "ts_rep": ts_rep,
                    })

    # ── 5. Deduplicar câmeras por grupo (manter melhor span por câmera) ────
    deduped: dict = {}
    for plates_key, cam_list in group_cameras.items():
        by_cam: dict = defaultdict(list)
        for entry in cam_list:
            by_cam[entry["camera_id"]].append(entry)
        best: list = []
        for cam_id, entries in by_cam.items():
            # Manter o com menor span (mais apertado)
            best.append(min(entries, key=lambda e: e["span_sec"]))
        deduped[plates_key] = best

    # ── 6. Filtrar por min_cameras e trip_span ─────────────────────────────
    result: list = []
    for plates_key, cam_list in deduped.items():
        if len(cam_list) < min_cameras:
            continue
        # Trip span: ordena câmeras por ts_rep, calcula (última - primeira)
        sorted_cams = sorted(cam_list, key=lambda c: c["ts_rep"])
        trip_span_sec = (sorted_cams[-1]["ts_rep"] - sorted_cams[0]["ts_rep"]).total_seconds()
        if trip_span_sec > max_trip_gap_s:
            continue
        # Se target_plate fornecido, filtrar
        if target_plate and target_plate not in plates_key:
            continue

        global_first = min(c["ts_min"] for c in cam_list)
        global_last = max(c["ts_max"] for c in cam_list)
        camera_names = [c["cam_nome"] for c in sorted_cams]
        cameras_confirmed = []
        for c in sorted_cams:
            cameras_confirmed.append({
                "camera_id": c["camera_id"],
                "cam_nome": c["cam_nome"],
                "ts_min": c["ts_min"].isoformat(),
                "ts_max": c["ts_max"].isoformat(),
                "span_sec": c["span_sec"],
                "plate_order": c["plate_order"],
            })

        result.append({
            "plates": sorted(list(plates_key)),
            "group_size": len(plates_key),
            "cameras_count": len(cam_list),
            "cameras": camera_names,
            "cameras_confirmed": cameras_confirmed,
            "trip_span_sec": int(trip_span_sec),
            "first_seen": global_first.isoformat(),
            "last_seen": global_last.isoformat(),
        })

    result.sort(key=lambda g: (g["cameras_count"], g["group_size"]), reverse=True)
    return result


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
    vehicle_type: Optional[str] = None,
    vehicle_color: Optional[str] = None,
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
    if vehicle_type:
        ev_extra.append("AND COALESCE(e.yolo_result->'target_vehicle'->>'tipo_raw', '') ILIKE %s")
        ev_extra_vals.append(vehicle_type)
    if vehicle_color:
        ev_extra.append("AND COALESCE(e.yolo_result->'target_vehicle'->>'cor', '') ILIKE %s")
        ev_extra_vals.append(vehicle_color)
    ev_extra_sql = "\n                  ".join(ev_extra)

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

            # ── 2. Parceiros de comboio (via algoritmo unificado) ──────────
            convoy_groups = _detect_convoy_groups(
                cur, t_from, t_to,
                window_s=300,
                max_trip_gap_s=3600,
                min_cameras=2,
                target_plate=plate,
            )

            # Extrai parceiros: placas que fazem parte de grupos suspeitos com a placa-alvo
            _partner_data: dict = {}
            for g in convoy_groups:
                others = [p for p in g["plates"] if p != plate]
                for op in others:
                    if op not in _partner_data or g["cameras_count"] > _partner_data[op]["cameras_together"]:
                        _partner_data[op] = {
                            "cameras_together": g["cameras_count"],
                            "cameras_confirmed": [c["camera_id"] for c in g["cameras_confirmed"]],
                            "trip_span_sec": g["trip_span_sec"],
                            "first_seen": g["first_seen"],
                            "last_seen": g["last_seen"],
                            "cameras_detail": g["cameras_confirmed"],
                        }

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
            partner_plates = list(_partner_data.keys())
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

    # ── Montar parceiros (somente de grupos suspeitos confirmados) ────
    partners: list[dict] = []
    for pplate, pd in _partner_data.items():
        partners.append({
            "plate":              pplate,
            "cameras_together":   pd["cameras_together"],
            "cameras_confirmed":  pd["cameras_confirmed"],
            "trip_span_sec":      pd["trip_span_sec"],
            "first_seen":         pd["first_seen"],
            "last_seen":          pd["last_seen"],
            "cameras_detail":     pd["cameras_detail"],
            "is_alvo":            pplate in alvo_partners,
        })

    partners.sort(key=lambda p: p["cameras_together"], reverse=True)

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
    _add("Parceiros em comboio",        len(partners),        15, "Parceiro confirmado (mesma câm ×2+, trip ≤1h) = +15 pts")
    alvo_partners_count = sum(1 for p in partners if p["is_alvo"])
    _add("Parceiros já cadastrados como alvo", alvo_partners_count, 30, "Parceiro alvo = +30 pts")
    if is_alvo:
        _add("Placa cadastrada como alvo", 1, 50, "Alvo registrado = +50 pts")

    # ── Badges ────────────────────────────────────────────────────────────
    badges: list[str] = []
    if is_alvo:                      badges.append("ALVO")
    if cameras_count >= 3:           badges.append("MULTI-CÂMERA")
    if len(partners) >= 1:           badges.append("COMBOIO")
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
    assert_admin_or_operator(
        request,
        "Apenas administradores e operadores podem registrar decisões operacionais",
    )
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


@app.get("/api/vehicles/{plate}/trajectory")
def vehicle_trajectory(
    plate: str,
    start: str,
    end: str,
    dedupe_seconds: int = 5,
):
    """
    Endpoint dedicado para trajetória de veículo.
    
    Retorna pontos ordenados cronologicamente com lat/lon enriquecidos das câmeras.
    
    Args:
        plate: Placa do veículo (exata, case-insensitive)
        start: Data/hora início (ISO 8601: YYYY-MM-DDTHH:mm:ss ou YYYY-MM-DD HH:mm:ss)
        end: Data/hora fim (ISO 8601)
        dedupe_seconds: Janela para deduplicar eventos repetidos na mesma câmera (padrão: 5s)
    
    Returns:
        {
            "plate": "ABC1234",
            "start": "2026-03-05T10:00:00-03:00",
            "end": "2026-03-05T18:00:00-03:00",
            "total_points": 42,
            "cameras_without_gps": ["CAM07", "CAM12"],
            "points": [
                {
                    "event_id": 123,
                    "ts": "2026-03-05T10:01:00-03:00",
                    "lat": -20.12345,
                    "lon": -63.45678,
                    "camera_id": "CAM01",
                    "camera_name": "BR-262 Km 10",
                    "direction": "CRESCENTE",
                    "confidence": 0.95,
                    "vehicle_type": "car"
                },
                ...
            ]
        }
    """
    # Normaliza placa: remove não-alfanuméricos e força maiúsculo
    import re as _re
    plate_raw = plate.strip().upper()
    plate_norm = _re.sub(r'[^A-Z0-9]', '', plate_raw)
    if not plate_norm:
        raise HTTPException(status_code=422, detail="plate é obrigatório")

    # Parse datas
    try:
        dt_start = datetime.fromisoformat(start.replace('Z', '').replace(' ', 'T'))
        dt_end   = datetime.fromisoformat(end.replace('Z', '').replace(' ', 'T'))
    except Exception as e:
        raise HTTPException(status_code=422, detail=f"Formato de data inválido: {e}")

    # Se não tiver tzinfo, assume fuso local -03:00 (Brasília)
    tz_brt = timezone(timedelta(hours=-3))
    if dt_start.tzinfo is None:
        dt_start = dt_start.replace(tzinfo=tz_brt)
    if dt_end.tzinfo is None:
        dt_end = dt_end.replace(tzinfo=tz_brt)

    dedupe_seconds = max(0, min(60, int(dedupe_seconds)))

    logging.info(
        "[trajectory] plate_raw=%r plate_norm=%r dt_start=%s dt_end=%s",
        plate_raw, plate_norm, dt_start.isoformat(), dt_end.isoformat()
    )

    with _conn() as conn:
        with conn.cursor() as cur:
            # Query com JOIN para enriquecer com lat/lon da câmera.
            # Comparação normalizada: remove traço/ponto/espaço antes de comparar.
            cur.execute("""
                SELECT
                    e.id                                                AS event_id,
                    COALESCE(e.occurred_at, e.ts)                       AS event_time,
                    e.plate,
                    e.camera_id,
                    e.camera_ip,
                    COALESCE(c.nome, e.channel_name, e.camera_id)      AS camera_name,
                    c.latitude,
                    c.longitude,
                    COALESCE(NULLIF(e.direcao,''), c.direcao)           AS direction,
                    COALESCE(e.confidence, 0.0)                         AS confidence,
                    COALESCE(e.yolo_result->'target_vehicle'->>'tipo_raw',
                             e.cam_meta->>'vehicle_type', '')            AS vehicle_type,
                    COALESCE(e.yolo_result->'target_vehicle'->>'cor', '') AS vehicle_color,
                    e.image_path
                FROM lpr_events e
                LEFT JOIN cameras c ON (
                    c.camera_id = e.camera_id
                    OR c.ip = e.camera_id
                    OR c.ip = e.camera_ip
                )
                WHERE regexp_replace(upper(coalesce(e.plate,'')), '[^A-Z0-9]', '', 'g')
                      = regexp_replace(upper(%s), '[^A-Z0-9]', '', 'g')
                  AND COALESCE(e.occurred_at, e.ts) BETWEEN %s AND %s
                ORDER BY COALESCE(e.occurred_at, e.ts) ASC
                LIMIT 2000
            """, (plate_norm, dt_start, dt_end))
            rows = cur.fetchall()

    logging.info("[trajectory] plate_norm=%r rows_returned=%d", plate_norm, len(rows))

    if not rows:
        return {
            "plate":             plate_norm,
            "start":             dt_start.isoformat(),
            "end":               dt_end.isoformat(),
            "total_events":      0,
            "total_points":      0,
            "cameras_without_gps": [],
            "points":            []
        }
    
    # Processa e deduplica
    points = []
    cameras_without_gps = set()
    last_camera_time = {}  # {camera_id: timestamp} para dedupe
    
    for r in rows:
        event_id      = r[0]
        event_time    = r[1]
        cam_id        = r[3] or r[4]  # camera_id ou camera_ip
        cam_name      = r[5]
        lat           = r[6]
        lon           = r[7]
        direction     = r[8]
        confidence    = float(r[9] or 0.0)
        vehicle_type  = r[10] or None
        vehicle_color = r[11] or None
        image_path    = r[12]
        
        # Pula se não tem GPS
        if lat is None or lon is None:
            if cam_name:
                cameras_without_gps.add(cam_name)
            continue
        
        # Dedupe: ignora se mesmo camera_id em janela de N segundos
        if dedupe_seconds > 0 and cam_id:
            last_ts = last_camera_time.get(cam_id)
            if last_ts:
                delta = (event_time - last_ts).total_seconds()
                if abs(delta) < dedupe_seconds:
                    continue  # Evento duplicado, pula
            last_camera_time[cam_id] = event_time
        
        points.append({
            "event_id":     event_id,
            "ts":           event_time.isoformat(),
            "lat":          float(lat),
            "lon":          float(lon),
            "camera_id":    cam_id,
            "camera_name":  cam_name,
            "direction":    direction,
            "confidence":   round(confidence, 2),
            "vehicle_type": vehicle_type,
            "vehicle_color": vehicle_color,
            "image_path":   image_path
        })
    
    return {
        "plate":                plate_norm,
        "start":                dt_start.isoformat(),
        "end":                  dt_end.isoformat(),
        "total_points":         len(points),
        "total_events":         len(rows),
        "cameras_without_gps":  sorted(list(cameras_without_gps)),
        "points":               points
    }


@app.get("/api/vehicles/{plate}/companions")
def get_companions(
    plate: str,
    start: str,
    end: str,
    delta_sec: int = 300,
    min_cameras: int = 2,
):
    """
    Encontra veículos que andavam em companhia com o {plate} especificado
    usando o algoritmo unificado de comboio (_detect_convoy_groups).

    Regras:
      - delta_sec (1..1000): janela de co-detecção por câmera
      - min_cameras = 2 (fixo mínimo)
      - trip_max = 3600s (1h)
    """
    plate = plate.strip().upper()
    if not plate:
        raise HTTPException(status_code=422, detail="plate é obrigatório")

    try:
        dt_start = datetime.fromisoformat(start.replace('Z', '').replace(' ', 'T'))
        dt_end   = datetime.fromisoformat(end.replace('Z', '').replace(' ', 'T'))
    except Exception as e:
        raise HTTPException(status_code=422, detail=f"Formato de data inválido: {e}")

    if dt_start.tzinfo is None:
        dt_start = dt_start.replace(tzinfo=timezone.utc)
    if dt_end.tzinfo is None:
        dt_end = dt_end.replace(tzinfo=timezone.utc)

    delta_sec = max(1, min(1000, int(delta_sec)))
    min_cameras = max(1, min(50, int(min_cameras)))

    with _conn() as conn:
        with conn.cursor() as cur:
            groups = _detect_convoy_groups(
                cur, dt_start, dt_end,
                window_s=delta_sec,
                max_trip_gap_s=3600,
                min_cameras=min_cameras,
                target_plate=plate,
            )

    final_companions = []
    for g in groups:
        other_plates = [p for p in g["plates"] if p != plate]
        for comp in other_plates:
            examples = []
            for cam in g.get("cameras_confirmed", []):
                examples.append({
                    "camera_id":    cam.get("camera_id", ""),
                    "camera_name":  cam.get("cam_nome", cam.get("camera_id", "")),
                    "t_a":          cam.get("ts_min"),
                    "t_b":          cam.get("ts_max"),
                    "dt_sec":       cam.get("span_sec", 0),
                })
            final_companions.append({
                "companion_plate": comp,
                "cameras_together": g["cameras_count"],
                "matches": len(examples),
                "first_seen": g["first_seen"],
                "last_seen": g["last_seen"],
                "trip_span_sec": g["trip_span_sec"],
                "examples": examples[:5],
            })

    final_companions.sort(
        key=lambda x: (x["cameras_together"], x["matches"]),
        reverse=True,
    )

    return {
        "plate": plate,
        "period": {"start": dt_start.isoformat(), "end": dt_end.isoformat()},
        "params": {"delta_sec": delta_sec, "min_cameras": min_cameras},
        "total_companions": len(final_companions),
        "companions": final_companions,
    }


# ===========================
# RELATÓRIO DE COMBOIO
# ===========================

@app.get("/api/comboio/report")
def comboio_report(
    target_plate: str,
    plates: str,
    window: str = "2h",
    window_s: int = 300,
    max_trip_gap_s: int = 3600,
    ts_from: str | None = None,
    ts_to: str | None = None,
):
    """
    Relatório detalhado de um grupo de comboio com:
    - imagens dos veículos
    - câmeras confirmadas (co-detecção)
    - métricas (avg gap por câmera + trip span)
    - pontos de trajetória com lat/lon
    - status de decisão operacional
    """
    target_plate = target_plate.strip().upper()
    group_plates = sorted(set(
        p.strip().upper() for p in plates.split(",") if p.strip()
    ))
    if target_plate not in group_plates:
        group_plates = sorted(set([target_plate] + group_plates))
    if len(group_plates) < 2:
        raise HTTPException(status_code=422, detail="Necessário pelo menos 2 placas")

    window_s = max(1, min(1000, int(window_s)))
    max_trip_gap_s = max(1, int(max_trip_gap_s))

    # Parse período
    minutes = _parse_window_to_minutes(window)
    now = _utcnow()
    t_to = now
    t_from = now - timedelta(minutes=minutes)
    if ts_from:
        try:
            t_from = datetime.fromisoformat(ts_from.replace("Z", "+00:00"))
        except Exception:
            pass
    if ts_to:
        try:
            t_to = datetime.fromisoformat(ts_to.replace("Z", "+00:00"))
        except Exception:
            pass

    with _conn() as conn:
        with conn.cursor() as cur:
            # ── 1. Detectar comboio para este grupo ──
            convoy = _detect_convoy_groups(
                cur, t_from, t_to,
                window_s=window_s,
                max_trip_gap_s=max_trip_gap_s,
                min_cameras=2,
            )
            # Encontrar o grupo que contém exatamente essas placas
            group_set = frozenset(group_plates)
            matched = None
            for g in convoy:
                if frozenset(g["plates"]) == group_set:
                    matched = g
                    break
            # Fallback: grupo contendo a target_plate e maior overlap
            if not matched:
                for g in convoy:
                    if target_plate in g["plates"] and set(g["plates"]) <= group_set:
                        matched = g
                        break

            # ── 2. Se não achou via _detect, construir dos dados brutos ──
            # Buscar todos os eventos do grupo no período
            placeholders = ",".join(["%s"] * len(group_plates))
            cur.execute(f"""
                SELECT e.id, UPPER(e.plate) AS plate, e.camera_id,
                       COALESCE(c.nome, e.channel_name, e.camera_id) AS camera_name,
                       COALESCE(e.occurred_at, e.ts) AS event_time,
                       e.image_path, e.confidence,
                       c.latitude, c.longitude,
                       COALESCE(NULLIF(e.direcao,''), c.direcao) AS direction,
                       COALESCE(e.yolo_result->'target_vehicle'->>'tipo_raw', '') AS vehicle_type,
                       COALESCE(e.yolo_result->'target_vehicle'->>'cor', '') AS vehicle_color
                FROM lpr_events e
                LEFT JOIN cameras c ON (
                    c.camera_id = e.camera_id
                    OR c.ip = e.camera_id
                    OR c.ip = e.camera_ip
                )
                WHERE UPPER(e.plate) IN ({placeholders})
                  AND COALESCE(e.occurred_at, e.ts) BETWEEN %s AND %s
                ORDER BY COALESCE(e.occurred_at, e.ts) ASC
                LIMIT 5000
            """, group_plates + [t_from, t_to])
            all_events = cur.fetchall()

            # ── 3. Imagem mais recente de cada placa ──
            vehicle_images: dict = {}
            for plate_i in group_plates:
                vehicle_images[plate_i] = None
            for row in reversed(all_events):
                p = row[1]
                if p in vehicle_images and vehicle_images[p] is None and row[5]:
                    vehicle_images[p] = f"/api/events/{row[0]}/thumbnail"

            # ── 4. Construir confirmed_events ──
            from collections import defaultdict as _dd
            cam_plate_events: dict = _dd(lambda: _dd(list))
            for row in all_events:
                cam_plate_events[row[2]][row[1]].append(row[4])  # cam_id -> plate -> [ts]

            confirmed_events = []
            if matched and matched.get("cameras_confirmed"):
                for cc in matched["cameras_confirmed"]:
                    cam_id = cc["camera_id"]
                    cam_name = cc["cam_nome"]
                    timestamps: dict = {}
                    for p in group_plates:
                        ts_list = cam_plate_events.get(cam_id, {}).get(p, [])
                        if ts_list:
                            # Pegar o timestamp mais próximo do ts_min/ts_max do cluster
                            cc_min = datetime.fromisoformat(cc["ts_min"]) if isinstance(cc["ts_min"], str) else cc["ts_min"]
                            best_ts = min(ts_list, key=lambda t: abs((t - cc_min).total_seconds()))
                            timestamps[p] = best_ts.isoformat()
                    if len(timestamps) >= 2:
                        ts_vals = [datetime.fromisoformat(v) if isinstance(v, str) else v for v in timestamps.values()]
                        sorted_ts = sorted(ts_vals)
                        delta_s = int((sorted_ts[-1] - sorted_ts[0]).total_seconds())
                        gaps = [(sorted_ts[i+1] - sorted_ts[i]).total_seconds() for i in range(len(sorted_ts)-1)]
                        avg_gap = round(sum(gaps) / len(gaps), 1) if gaps else 0
                        confirmed_events.append({
                            "camera_id": cam_id,
                            "camera_name": cam_name,
                            "timestamps": timestamps,
                            "delta_s": delta_s,
                            "avg_gap_s": avg_gap,
                        })
            else:
                # Fallback sem matched: buscar co-detecções brutas
                for cam_id, plate_ts_map in cam_plate_events.items():
                    present = [p for p in group_plates if p in plate_ts_map and plate_ts_map[p]]
                    if len(present) < 2:
                        continue
                    timestamps = {}
                    base_ts = min(plate_ts_map[present[0]])
                    for p in present:
                        best = min(plate_ts_map[p], key=lambda t: abs((t - base_ts).total_seconds()))
                        timestamps[p] = best.isoformat()
                    ts_vals = [datetime.fromisoformat(v) for v in timestamps.values()]
                    sorted_ts = sorted(ts_vals)
                    span = (sorted_ts[-1] - sorted_ts[0]).total_seconds()
                    if span > window_s:
                        continue
                    gaps = [(sorted_ts[i+1] - sorted_ts[i]).total_seconds() for i in range(len(sorted_ts)-1)]
                    avg_gap = round(sum(gaps) / len(gaps), 1) if gaps else 0
                    cam_name = None
                    for row in all_events:
                        if row[2] == cam_id:
                            cam_name = row[3]
                            break
                    confirmed_events.append({
                        "camera_id": cam_id,
                        "camera_name": cam_name or cam_id,
                        "timestamps": timestamps,
                        "delta_s": int(span),
                        "avg_gap_s": avg_gap,
                    })

            confirmed_events.sort(key=lambda e: min(e["timestamps"].values()))

            # ── 5. Métricas ──
            total_cameras = len(confirmed_events)
            if confirmed_events:
                first_ts_vals = [min(datetime.fromisoformat(v) if isinstance(v,str) else v for v in ce["timestamps"].values()) for ce in confirmed_events]
                trip_first = min(first_ts_vals)
                trip_last = max(first_ts_vals)
                trip_span_s = int((trip_last - trip_first).total_seconds())
                all_gaps = [ce["avg_gap_s"] for ce in confirmed_events if ce["avg_gap_s"] > 0]
                avg_gap_overall = round(sum(all_gaps) / len(all_gaps), 1) if all_gaps else 0
            else:
                trip_span_s = matched["trip_span_sec"] if matched else 0
                avg_gap_overall = 0

            trip_min = trip_span_s // 60
            trip_sec = trip_span_s % 60
            trip_human = f"{trip_min}m {trip_sec}s" if trip_min else f"{trip_sec}s"

            # ── 6. Trajetória com lat/lon ──
            traj: dict = {}
            for p in group_plates:
                traj[p] = []
            for row in all_events:
                p = row[1]
                if p in traj and row[7] is not None and row[8] is not None:
                    traj[p].append({
                        "ts": row[4].isoformat(),
                        "camera_id": row[2],
                        "camera_name": row[3],
                        "lat": float(row[7]),
                        "lon": float(row[8]),
                        "direction": row[9],
                        "image_path": row[5],
                        "event_id": row[0],
                    })

            target_traj = {"plate": target_plate, "points": traj.get(target_plate, [])}
            partner_trajs = [{"plate": p, "points": traj.get(p, [])} for p in group_plates if p != target_plate]

            # ── 7. Alvos ──
            cur.execute("SELECT plate FROM alvos WHERE UPPER(plate) IN ({})".format(
                ",".join(["%s"] * len(group_plates))
            ), group_plates)
            alvo_plates = set(r[0].upper() for r in cur.fetchall())

            # ── 8. Última decisão ──
            cur.execute("""
                SELECT id, decision, decision_note, operator, created_at
                FROM vehicle_report_decisions
                WHERE plate = %s
                ORDER BY created_at DESC
                LIMIT 1
            """, (target_plate,))
            dec_row = cur.fetchone()
            last_decision = None
            if dec_row:
                last_decision = {
                    "id": dec_row[0],
                    "decision": dec_row[1],
                    "note": dec_row[2],
                    "operator": dec_row[3],
                    "created_at": dec_row[4].isoformat() if dec_row[4] else None,
                }

    # ── Build response ──
    status = "pending"
    if last_decision:
        dm = {"confirmado": "confirmed", "falso_positivo": "false_positive", "ignorar": "pending"}
        status = dm.get(last_decision["decision"], "pending")

    return {
        "target_plate": target_plate,
        "period": {"start": t_from.isoformat(), "end": t_to.isoformat()},
        "params": {"window_s": window_s, "min_cameras": 2, "max_trip_gap_s": max_trip_gap_s},
        "group": {
            "plates": group_plates,
            "vehicle_images": vehicle_images,
            "status": status,
            "alvos": {p: (p in alvo_plates) for p in group_plates},
        },
        "confirmed_events": confirmed_events,
        "metrics": {
            "total_cameras_confirmed": total_cameras,
            "total_vehicles": len(group_plates),
            "trip_span_s": trip_span_s,
            "trip_span_human": trip_human,
            "avg_gap_overall_s": avg_gap_overall,
        },
        "trajectory": {
            "target": target_traj,
            "partners": partner_trajs,
        },
        "last_decision": last_decision,
    }


@app.post("/api/comboio/confirm", status_code=201)
async def comboio_confirm(request: Request):
    """Confirma suspeito de comboio — salva decisão + registra como alvo."""
    assert_admin_or_operator(
        request,
        "Apenas administradores e operadores podem confirmar comboio",
    )
    data = await request.json()
    plate = (data.get("target_plate") or "").strip().upper()
    if not plate:
        raise HTTPException(status_code=422, detail="target_plate obrigatório")
    note = str(data.get("note") or "")[:1000]
    group_plates = data.get("group_plates") or []
    params = data.get("params") or {}
    try:
        operator = request.state.user.get("sub", "") if isinstance(request.state.user, dict) else ""
    except Exception:
        operator = ""

    with _conn() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO vehicle_report_decisions
                    (plate, score_total, level, badges, sinais_principais, decision, decision_note, operator, report_window)
                VALUES (%s, 0, 'alerta', '["COMBOIO"]'::jsonb, %s::jsonb, 'confirmado', %s, %s, '2h')
                RETURNING id, created_at
            """, (
                plate,
                _json_lib.dumps({"comboio": group_plates, "params": params}),
                note, operator,
            ))
            row = cur.fetchone()
            # Cadastrar como alvo
            desc = note or f"Comboio confirmado — grupo: {', '.join(group_plates)}"
            cur.execute("""
                INSERT INTO alvos (plate, descricao)
                VALUES (%s, %s)
                ON CONFLICT (plate) DO UPDATE SET descricao = EXCLUDED.descricao
            """, (plate, desc))
    return {"ok": True, "id": row[0], "decision": "confirmado", "created_at": row[1].isoformat() if row[1] else None}


@app.post("/api/comboio/false_positive", status_code=201)
async def comboio_false_positive(request: Request):
    """Marca grupo de comboio como falso positivo."""
    assert_admin_or_operator(
        request,
        "Apenas administradores e operadores podem marcar falso positivo",
    )
    data = await request.json()
    plate = (data.get("target_plate") or "").strip().upper()
    if not plate:
        raise HTTPException(status_code=422, detail="target_plate obrigatório")
    note = str(data.get("note") or "")[:1000]
    group_plates = data.get("group_plates") or []
    params = data.get("params") or {}
    try:
        operator = request.state.user.get("sub", "") if isinstance(request.state.user, dict) else ""
    except Exception:
        operator = ""

    with _conn() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO vehicle_report_decisions
                    (plate, score_total, level, badges, sinais_principais, decision, decision_note, operator, report_window)
                VALUES (%s, 0, 'normal', '["COMBOIO"]'::jsonb, %s::jsonb, 'falso_positivo', %s, %s, '2h')
                RETURNING id, created_at
            """, (
                plate,
                _json_lib.dumps({"comboio": group_plates, "params": params}),
                note, operator,
            ))
            row = cur.fetchone()
    return {"ok": True, "id": row[0], "decision": "falso_positivo", "created_at": row[1].isoformat() if row[1] else None}


# ===========================
# CENTRAL DE AMEAÇAS — consolida suspeitos + comboio + grupos + alvos
# ===========================

@app.get("/api/batedor/central")
def batedor_central(
    window: str = "2h",
    limit: int = 150,
    ts_from: str | None = None,
    ts_to:   str | None = None,
    plate_prefix:  Optional[str] = None,   # prefixo parcial da placa (ex: ABC)
    direcao:       Optional[str] = None,   # CRESCENTE | DECRESCENTE | ENTRADA | SAÍDA
    vehicle_type:  Optional[str] = None,   # car | motorcycle | pickup | truck | bus | van
    vehicle_color: Optional[str] = None,   # Preto | Branco | Prata | Cinza | Vermelho ...
):
    """
    Visão unificada: cruza suspeitos, comboio, grupos e alvos cadastrados.
    Retorna por placa: de quais módulos ela consta, score total e metadados.
    """
    import logging as _log
    _log.info("[batedor_central] window=%s limit=%d ts_from=%s ts_to=%s plate_prefix=%s",
              window, limit, ts_from, ts_to, plate_prefix)
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

    # ── Pré-filtro: placas que atendem aos filtros de evento ─────────────────
    allowed_plates: set | None = None
    prefix_sql  = ""
    prefix_vals: list = []

    if plate_prefix:
        prefix_sql  = "AND plate ILIKE %s"
        prefix_vals = [plate_prefix.strip().upper() + "%"]

    with _conn() as conn:
        with conn.cursor() as cur:

            if direcao or vehicle_type or vehicle_color:
                ev_conds = ["COALESCE(e.occurred_at, e.ts) BETWEEN %s AND %s"]
                ev_vals  = [t_from, t_to]
                if direcao:
                    ev_conds.append("UPPER(COALESCE(c.direcao,'')) = UPPER(%s)")
                    ev_vals.append(direcao.strip())
                if vehicle_type:
                    ev_conds.append("e.yolo_result->'target_vehicle'->>'tipo_raw' = %s")
                    ev_vals.append(vehicle_type.strip())
                if vehicle_color:
                    ev_conds.append("LOWER(COALESCE(e.yolo_result->'target_vehicle'->>'cor','')) = LOWER(%s)")
                    ev_vals.append(vehicle_color.strip())
                ev_where = " AND ".join(ev_conds)
                cur.execute(f"""
                    SELECT DISTINCT e.plate
                    FROM lpr_events e
                    LEFT JOIN cameras c ON c.id = (
                        SELECT id FROM cameras
                        WHERE camera_id = e.camera_id OR ip = e.camera_id
                        ORDER BY (camera_id = e.camera_id) DESC LIMIT 1
                    )
                    WHERE {ev_where}
                      AND e.plate IS NOT NULL
                      AND e.plate NOT IN ('', 'unknown', 'UNKNOWN')
                      {prefix_sql}
                """, ev_vals + prefix_vals)
                allowed_plates = {row[0] for row in cur.fetchall()}

            allow_sql  = "AND plate = ANY(%s)" if allowed_plates is not None else ""
            allow_vals = [list(allowed_plates)]  if allowed_plates is not None else []

            # ── 1. SUSPEITOS ──────────────────────────────────────────────
            cur.execute(f"""
                SELECT plate,
                       COUNT(*)                       AS passes,
                       COUNT(DISTINCT camera_id)      AS cameras,
                       MIN(COALESCE(occurred_at, ts)) AS first_seen,
                       MAX(COALESCE(occurred_at, ts)) AS last_seen
                FROM lpr_events
                WHERE plate IS NOT NULL
                  AND plate NOT IN ('', 'unknown', 'UNKNOWN')
                  AND COALESCE(occurred_at, ts) BETWEEN %s AND %s
                  {prefix_sql} {allow_sql}
                GROUP BY plate
                HAVING COUNT(*) >= 2 AND COUNT(DISTINCT camera_id) >= 2
                ORDER BY COUNT(DISTINCT camera_id) DESC, COUNT(*) DESC
                LIMIT 300
            """, [t_from, t_to] + prefix_vals + allow_vals)
            for r in cur.fetchall():
                plate, passes, cameras, fs, ls = r[0], int(r[1]), int(r[2]), r[3], r[4]
                score = cameras * 10 + passes * 2
                intel[plate]["in_suspeitos"] = {"score": score, "passes": passes, "cameras": cameras}
                _upd(intel[plate], fs, ls)

            # ── 2+3. COMBOIO E GRUPOS (algoritmo unificado) ──────────────
            convoy_groups = _detect_convoy_groups(
                cur, t_from, t_to,
                window_s=300,
                max_trip_gap_s=3600,
                min_cameras=2,
                prefix_sql=prefix_sql,
                prefix_vals=prefix_vals,
                allow_sql=allow_sql,
                allow_vals=allow_vals,
            )
            # Marca cada placa que participa de grupo suspeito
            from datetime import datetime as _dt
            for g in convoy_groups:
                cams = g["cameras_count"]
                score = cams * 15
                fs_str = g["first_seen"]
                ls_str = g["last_seen"]
                try:
                    fs = _dt.fromisoformat(fs_str) if isinstance(fs_str, str) else fs_str
                    ls = _dt.fromisoformat(ls_str) if isinstance(ls_str, str) else ls_str
                except Exception:
                    fs = ls = None
                for plate in g["plates"]:
                    # in_comboio: marca como comboio suspeito
                    if not intel[plate]["in_comboio"] or cams > intel[plate]["in_comboio"].get("cameras", 0):
                        intel[plate]["in_comboio"] = {
                            "score": score,
                            "cameras": cams,
                            "trip_span_sec": g["trip_span_sec"],
                        }
                    # in_grupos: adiciona parceiros do grupo
                    others = [p for p in g["plates"] if p != plate]
                    for o in others:
                        intel[plate]["in_grupos"].append({
                            "plate": o,
                            "score": score,
                            "cameras_together": cams,
                        })
                    _upd(intel[plate], fs, ls)

            # ── 4. Enriquecimento: tipo/cor dominante por placa ───────────
            cur.execute("""
                SELECT DISTINCT ON (plate)
                    plate,
                    yolo_result->'target_vehicle'->>'tipo_raw' AS vtype,
                    yolo_result->'target_vehicle'->>'cor'       AS vcolor
                FROM lpr_events
                WHERE plate IS NOT NULL
                  AND COALESCE(occurred_at, ts) BETWEEN %s AND %s
                ORDER BY plate, COALESCE(occurred_at, ts) DESC
            """, (t_from, t_to))
            for row in cur.fetchall():
                if row[0] in intel:
                    intel[row[0]]["vehicle_type"]  = row[1] or None
                    intel[row[0]]["vehicle_color"] = row[2] or None

            # ── 5. ALVOS cadastrados ───────────────────────────────────────
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
            "vehicle_type":   d.get("vehicle_type"),
            "vehicle_color":  d.get("vehicle_color"),
        })

    items.sort(key=lambda x: (x["sinais"], x["score_total"]), reverse=True)
    _log.info("[batedor_central] resultado: %d itens (total=%d), window retornado=%s", len(items[:limit]), len(items), window)
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

    if method == "POST":
        logger.warning(
            "[CATCHALL] POST em %s não processa alerta real; use /api/simple-webhook para fluxo de alarme.",
            path,
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


# ===========================
# NOTIFICAÇÕES - FCM / ALERTAS CRÍTICOS
# ===========================

@app.post("/api/fcm/register-token")
async def fcm_register_token(request: Request):
    """
    Registrar token FCM do dispositivo mobile
    
    Payload esperado:
    {
        "fcm_token": "string",
        "device_id": "string (opcional)"
    }
    """
    try:
        user_sub = request.state.user.get("sub") if isinstance(request.state.user, dict) else None
        if not user_sub:
            raise HTTPException(status_code=401, detail="Não autenticado")

        # Tokens FCM devem ficar vinculados ao ID numérico do usuário (alarme_usuarios.usuario_id).
        user_id = _resolve_user_numeric_id_from_sub(str(user_sub))
        if not user_id:
            raise HTTPException(status_code=422, detail="Usuário do token não mapeado no cadastro")
        
        data = await request.json()
        fcm_token = (data.get("fcm_token") or "").strip()
        device_id = (data.get("device_id") or "default").strip()
        
        if not fcm_token:
            raise HTTPException(status_code=422, detail="fcm_token obrigatório")

        if is_likely_fake_token(fcm_token):
            logger.warning(
                "[FCM] register-token rejeitado (fake) user_sub=%s user_id=%s device_id=%s token_prefix=%s",
                user_sub,
                user_id,
                device_id,
                fcm_token[:16],
            )
            raise HTTPException(status_code=422, detail="fcm_token inválido para ambiente real")

        logger.info(
            "[FCM] register-token request user_sub=%s user_id=%s device_id=%s token_len=%d",
            user_sub,
            user_id,
            device_id,
            len(fcm_token),
        )
        
        with _conn() as conn:
            with conn.cursor() as cur:
                success = register_fcm_token(user_id, device_id, fcm_token, db_cur=cur)
                cur.execute(
                    "SELECT COUNT(*) FROM fcm_device_tokens WHERE user_id=%s AND active=TRUE",
                    (user_id,),
                )
                active_tokens = int(cur.fetchone()[0] or 0)
        
        if not success:
            raise HTTPException(status_code=500, detail="Erro ao registrar token")

        logger.info(
            "[FCM] register-token success user_sub=%s user_id=%s device_id=%s active_tokens=%d token_prefix=%s",
            user_sub,
            user_id,
            device_id,
            active_tokens,
            fcm_token[:16],
        )
        
        return {
            "ok": True,
            "message": "Token FCM registrado com sucesso",
            "user_id": user_id,
            "user_sub": user_sub,
            "device_id": device_id,
            "active_tokens": active_tokens,
        }
    
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[FCM] Erro ao registrar token: {e}")
        raise HTTPException(status_code=500, detail="Erro interno ao registrar token")


@app.get("/api/fcm/my-token-status")
async def fcm_my_token_status(request: Request):
    """Diagnóstico rápido dos tokens FCM do usuário autenticado."""
    try:
        user_sub = request.state.user.get("sub") if isinstance(request.state.user, dict) else None
        if not user_sub:
            raise HTTPException(status_code=401, detail="Não autenticado")

        user_id = _resolve_user_numeric_id_from_sub(str(user_sub))
        if not user_id:
            raise HTTPException(status_code=422, detail="Usuário do token não mapeado no cadastro")

        with _conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT
                        COUNT(*) AS total,
                        COUNT(*) FILTER (WHERE active = TRUE) AS active,
                        COUNT(*) FILTER (WHERE active = FALSE) AS inactive,
                        MAX(updated_at) AS last_update,
                        MAX(last_seen_at) AS last_seen
                    FROM fcm_device_tokens
                    WHERE user_id = %s
                    """,
                    (user_id,),
                )
                row = cur.fetchone()

                cur.execute(
                    """
                    SELECT device_id, active, updated_at, last_seen_at
                    FROM fcm_device_tokens
                    WHERE user_id = %s
                    ORDER BY updated_at DESC
                    """,
                    (user_id,),
                )
                devices = [
                    {
                        "device_id": d[0],
                        "active": bool(d[1]),
                        "updated_at": d[2].isoformat() if d[2] else None,
                        "last_seen_at": d[3].isoformat() if d[3] else None,
                    }
                    for d in cur.fetchall()
                ]

        total = int(row[0] or 0)
        active = int(row[1] or 0)
        inactive = int(row[2] or 0)
        last_update = row[3].isoformat() if row[3] else None
        last_seen = row[4].isoformat() if row[4] else None

        logger.info(
            "[FCM] my-token-status user_sub=%s user_id=%s total=%d active=%d inactive=%d",
            user_sub,
            user_id,
            total,
            active,
            inactive,
        )

        return {
            "ok": True,
            "user_sub": str(user_sub),
            "user_id": str(user_id),
            "total_tokens": total,
            "active_tokens": active,
            "inactive_tokens": inactive,
            "last_update": last_update,
            "last_seen": last_seen,
            "devices": devices,
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("[FCM] Erro em my-token-status: %s", e)
        raise HTTPException(status_code=500, detail="Erro ao consultar status dos tokens FCM")


@app.post("/api/fcm/send-alert")
async def fcm_send_alert(request: Request):
    """Endpoint manual para teste de push para usuários vinculados a um alarme."""
    assert_admin(request, "Apenas administradores podem enviar alerta manual")
    try:
        data = await request.json()
        alarme_id_raw = data.get("alarme_id")
        plate = str(data.get("plate") or "").strip().upper()
        target_name = str(data.get("target_name") or "Alvo monitorado").strip()
        camera_name = str(data.get("camera_name") or "Camera teste").strip()
        detected_at = str(data.get("detected_at") or datetime.now(timezone.utc).isoformat()).strip()
        image_url = str(data.get("image_url") or "").strip()
        event_id = str(data.get("event_id") or f"manual-{uuid.uuid4().hex[:12]}").strip()
        city = str(data.get("city") or "N/A").strip()
        risk_level = str(data.get("risk_level") or "high").strip().lower()
        alert_type = str(data.get("alert_type") or "critical_alert").strip().lower()

        if alarme_id_raw is None:
            raise HTTPException(status_code=422, detail="alarme_id é obrigatório")
        try:
            alarme_id = int(alarme_id_raw)
        except (TypeError, ValueError):
            raise HTTPException(status_code=422, detail="alarme_id inválido")
        if not plate:
            raise HTTPException(status_code=422, detail="plate é obrigatório")

        alert = FCMAlert(
            plate=plate,
            target_name=target_name,
            camera_name=camera_name,
            detected_at=detected_at,
            image_url=image_url,
            event_id=event_id,
            city=city,
            risk_level=risk_level,
            alert_type=alert_type,
        )

        with _conn() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT ativo FROM alarmes WHERE id=%s LIMIT 1", (alarme_id,))
                alarm_row = cur.fetchone()
                if not alarm_row:
                    raise HTTPException(status_code=404, detail="Alarme não encontrado")
                if not bool(alarm_row[0]):
                    raise HTTPException(status_code=422, detail="Alarme inativo")

                cur.execute("SELECT COUNT(*) FROM alarme_usuarios WHERE alarme_id=%s", (alarme_id,))
                linked_users = int(cur.fetchone()[0] or 0)
                if linked_users == 0:
                    raise HTTPException(status_code=422, detail="Alarme sem usuários vinculados")

                stats = await send_alert_to_alarm_users(cur, alarme_id, alert)
                if int(stats.get("users") or 0) == 0:
                    raise HTTPException(status_code=422, detail="Sem usuários elegíveis para envio")

        return {
            "ok": True,
            "linked_users": stats.get("linked_users", stats.get("users", 0)),
            "valid_tokens": stats.get("valid_tokens", 0),
            "sent": stats["sent"],
            "sent_success": stats["sent"],
            "failed": stats["failed"],
            "failures": stats["failed"],
            "invalid_tokens": stats["invalid"],
            "users": stats.get("users", 0),
            "users_with_tokens": stats.get("users_with_tokens", 0),
            "tokens_attempted": stats.get("tokens_attempted", stats.get("valid_tokens", 0)),
            "alarme_id": alarme_id,
            "event_id": event_id,
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("[FCM] Erro ao enviar alerta manual: %s", e)
        raise HTTPException(status_code=500, detail="Erro interno ao enviar alerta push")


@app.post("/api/fcm/test-self")
async def fcm_test_self(request: Request):
    """Teste direto de push para o usuário autenticado (opcionalmente para um device_id)."""
    try:
        user_sub = request.state.user.get("sub") if isinstance(request.state.user, dict) else None
        if not user_sub:
            raise HTTPException(status_code=401, detail="Não autenticado")

        user_id = _resolve_user_numeric_id_from_sub(str(user_sub))
        if not user_id:
            raise HTTPException(status_code=422, detail="Usuário do token não mapeado no cadastro")

        data = await request.json()
        device_id = (data.get("device_id") or "").strip() or None
        title = str(data.get("title") or "Teste Push BPFRON").strip()
        body = str(data.get("body") or "Mensagem de teste enviada pelo backend").strip()
        event_id = str(data.get("event_id") or f"self-test-{uuid.uuid4().hex[:12]}").strip()

        logger.info(
            "[FCM] test-self request user_sub=%s resolved_user_id=%s device_id=%s title=%s event_id=%s",
            user_sub,
            user_id,
            device_id or "*",
            title,
            event_id,
        )

        alert = FCMAlert(
            plate="TESTE-SELF",
            target_name=title,
            camera_name="Teste Direto",
            detected_at=datetime.now(timezone.utc).isoformat(),
            image_url="",
            event_id=event_id,
            city="N/A",
            risk_level="high",
            alert_type="critical_alert",
        )

        with _conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT id, user_id, device_id, LEFT(fcm_token, 16) AS token_prefix, active, updated_at
                    FROM fcm_device_tokens
                    WHERE user_id = %s
                    ORDER BY updated_at DESC
                    LIMIT 30
                    """,
                    (str(user_id),),
                )
                token_rows = cur.fetchall() or []

                active_rows = [r for r in token_rows if bool(r[4])]
                logger.info(
                    "[FCM] test-self token_snapshot user_sub=%s user_id=%s total_rows=%d active_rows=%d",
                    user_sub,
                    user_id,
                    len(token_rows),
                    len(active_rows),
                )
                for row in token_rows:
                    logger.info(
                        "[FCM] test-self token_row token_row_id=%s user_id=%s device_id=%s token_prefix=%s active=%s updated_at=%s",
                        row[0],
                        row[1],
                        row[2],
                        row[3],
                        row[4],
                        row[5],
                    )

                stats = await send_alert_to_user_tokens(cur, str(user_id), alert, device_id=device_id)

        if not isinstance(stats, dict):
            stats = {}

        def _safe_int(v):
            if v is None:
                return 0
            try:
                return int(v)
            except Exception:
                return 0

        sent = _safe_int(stats.get("sent", 0))
        failed = _safe_int(stats.get("failed", 0))
        invalid = _safe_int(stats.get("invalid", 0))
        valid_tokens = _safe_int(stats.get("valid_tokens", 0))

        logger.info(
            "[FCM] test-self user_sub=%s user_id=%s device_id=%s sent=%s failed=%s invalid=%s valid_tokens=%s",
            user_sub,
            user_id,
            device_id or "*",
            sent,
            failed,
            invalid,
            valid_tokens,
        )

        return {
            "ok": True,
            "user_sub": str(user_sub),
            "user_id": str(user_id),
            "device_id": device_id,
            "event_id": event_id,
            "valid_tokens": valid_tokens,
            "sent": sent,
            "failed": failed,
            "invalid_tokens": invalid,
            "payload": {
                "title": title,
                "body": body,
                "type": "critical_alert",
                "event_id": event_id,
                "click_action": "FLUTTER_NOTIFICATION_CLICK",
            },
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("[FCM] Erro no test-self: %s", e)
        raise HTTPException(status_code=500, detail="Erro interno no teste de push")


@app.get("/api/fcm/status")
async def fcm_status(request: Request):
    """Verificar status de alertas FCM"""
    assert_admin(request, "Apenas administradores podem acessar status FCM")
    try:
        user_sub = request.state.user.get("sub") if isinstance(request.state.user, dict) else None
        if not user_sub:
            raise HTTPException(status_code=401, detail="Não autenticado")

        user_id = _resolve_user_numeric_id_from_sub(str(user_sub))
        if not user_id:
            raise HTTPException(status_code=422, detail="Usuário do token não mapeado no cadastro")
        
        with _conn() as conn:
            with conn.cursor() as cur:
                # Contar alertas criticos não lidos
                cur.execute("""
                    SELECT COUNT(*) FROM alertas_criticos
                    WHERE usuario_id IN (%s, %s)
                    AND NOT lido
                    AND criado_em > NOW() - INTERVAL '24 hours'
                """, (user_id, str(user_sub)))
                count = cur.fetchone()[0]
        
        return {
            "ok": True,
            "unread_alerts": count,
            "timestamp": datetime.now().isoformat(),
        }
    
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[FCM] Erro ao verificar status: {e}")
        raise HTTPException(status_code=500, detail="Erro ao verificar status")


# ===========================
# ALARMES (CRUD)
# ===========================

@app.get("/api/alarmes")
async def list_alarmes(request: Request):
    """Listar todos os alarmes com listas e usuários vinculados."""
    # Admin, operador e visualizador podem listar alarmes
    require_role(request, "admin", "operador", "visualizador")
    try:
        with _conn() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT to_regclass('public.alarmes')")
                has_alarmes_table = bool(cur.fetchone()[0])
                if not has_alarmes_table:
                    logger.warning("[ALARMES] Tabela public.alarmes não encontrada; retornando lista vazia")
                    return {"items": []}

                cur.execute(
                    """
                    SELECT column_name
                    FROM information_schema.columns
                    WHERE table_schema='public' AND table_name='alarmes'
                    """
                )
                alarmes_cols = {row[0] for row in cur.fetchall()}

                if "id" not in alarmes_cols:
                    logger.error("[ALARMES] Coluna obrigatória 'id' ausente em public.alarmes")
                    return {"items": [], "detail": "Estrutura de alarmes inconsistente"}

                if "nome" not in alarmes_cols:
                    logger.error("[ALARMES] Coluna obrigatória 'nome' ausente em public.alarmes")
                    return {"items": [], "detail": "Estrutura de alarmes inconsistente"}

                select_parts = [
                    "a.id AS id",
                    "a.nome AS nome",
                    ("a.descricao" if "descricao" in alarmes_cols else "''::text") + " AS descricao",
                    ("a.tipo" if "tipo" in alarmes_cols else "'placa_monitorada'::text") + " AS tipo",
                    ("a.prioridade" if "prioridade" in alarmes_cols else "'media'::text") + " AS prioridade",
                    ("a.ativo" if "ativo" in alarmes_cols else "TRUE") + " AS ativo",
                    ("a.mensagem" if "mensagem" in alarmes_cols else "''::text") + " AS mensagem",
                    ("a.criado_em" if "criado_em" in alarmes_cols else "NULL::timestamptz") + " AS criado_em",
                    ("a.atualizado_em" if "atualizado_em" in alarmes_cols else "NULL::timestamptz") + " AS atualizado_em",
                ]
                cur.execute(f"SELECT {', '.join(select_parts)} FROM alarmes a ORDER BY a.id DESC")

                rows = cur.fetchall() or []
                if not rows:
                    return {"items": []}

                cur.execute("SELECT to_regclass('public.alarme_listas')")
                has_alarme_listas = bool(cur.fetchone()[0])
                cur.execute("SELECT to_regclass('public.alarme_usuarios')")
                has_alarme_usuarios = bool(cur.fetchone()[0])

                alarme_listas_ok = False
                alarme_usuarios_ok = False

                if has_alarme_listas:
                    cur.execute(
                        """
                        SELECT column_name
                        FROM information_schema.columns
                        WHERE table_schema='public' AND table_name='alarme_listas'
                        """
                    )
                    cols = {row[0] for row in cur.fetchall()}
                    alarme_listas_ok = {"alarme_id", "lista_id"}.issubset(cols)
                    if not alarme_listas_ok:
                        logger.warning("[ALARMES] Tabela alarme_listas sem colunas esperadas: %s", cols)

                if has_alarme_usuarios:
                    cur.execute(
                        """
                        SELECT column_name
                        FROM information_schema.columns
                        WHERE table_schema='public' AND table_name='alarme_usuarios'
                        """
                    )
                    cols = {row[0] for row in cur.fetchall()}
                    alarme_usuarios_ok = {"alarme_id", "usuario_id"}.issubset(cols)
                    if not alarme_usuarios_ok:
                        logger.warning("[ALARMES] Tabela alarme_usuarios sem colunas esperadas: %s", cols)

                alarmes = []
                for row in rows:
                    aid, nome, descricao, tipo, prioridade, ativo, mensagem, criado_em, atualizado_em = row

                    if aid is None:
                        logger.warning("[ALARMES] Registro ignorado por id nulo: %s", row)
                        continue

                    listas = []
                    usuarios = []

                    if alarme_listas_ok:
                        cur.execute("SELECT lista_id FROM alarme_listas WHERE alarme_id=%s", (aid,))
                        listas = [r[0] for r in (cur.fetchall() or []) if r and r[0] is not None]

                    if alarme_usuarios_ok:
                        cur.execute("SELECT usuario_id FROM alarme_usuarios WHERE alarme_id=%s", (aid,))
                        usuarios = [r[0] for r in (cur.fetchall() or []) if r and r[0] is not None]

                    alarmes.append({
                        "id": int(aid),
                        "nome": str(nome or ""),
                        "descricao": str(descricao or ""),
                        "tipo": str(tipo or "placa_monitorada"),
                        "prioridade": str(prioridade or "media"),
                        "ativo": bool(ativo),
                        "mensagem": str(mensagem or ""),
                        "criado_em": criado_em.isoformat() if isinstance(criado_em, datetime) else (str(criado_em) if criado_em else None),
                        "atualizado_em": atualizado_em.isoformat() if isinstance(atualizado_em, datetime) else (str(atualizado_em) if atualizado_em else None),
                        "listas": listas,
                        "usuarios": usuarios,
                    })

        return {"items": alarmes}

    except HTTPException:
        raise
    except Exception as e:
        logger.exception("[ALARMES] Erro em GET /api/alarmes: %s", e)
        return {"items": [], "detail": "Erro ao listar alarmes"}


@app.post("/api/alarmes", status_code=201)
async def create_alarme(request: Request):
    # Admin e operador podem criar alarmes
    assert_admin_or_operator(request, "Apenas administradores e operadores podem criar alarmes")
    data = await request.json()
    lista_id = data.get("lista_id")
    if not lista_id:
        raise HTTPException(status_code=400, detail="lista_id é obrigatório")
    lista_id = int(lista_id)
    prioridade = str(data.get("prioridade") or "media").strip()
    if prioridade not in ("baixa", "media", "alta", "critica"):
        raise HTTPException(status_code=400, detail="prioridade inválida")
    ativo = bool(data.get("ativo", True))
    usuarios = data.get("usuarios") or []
    with _conn() as conn:
        with conn.cursor() as cur:
            # Buscar nome da lista para usar como nome do alarme
            cur.execute("SELECT name FROM vehicle_lists WHERE id=%s", (lista_id,))
            row = cur.fetchone()
            if not row:
                raise HTTPException(status_code=400, detail="Lista não encontrada")
            nome = f"Alarme - {row[0]}"
            cur.execute(
                """INSERT INTO alarmes (nome, descricao, tipo, prioridade, ativo, mensagem)
                   VALUES (%s,%s,%s,%s,%s,%s) RETURNING id""",
                (nome, "", "placa_monitorada", prioridade, ativo, ""),
            )
            aid = cur.fetchone()[0]
            cur.execute("INSERT INTO alarme_listas (alarme_id, lista_id) VALUES (%s,%s) ON CONFLICT DO NOTHING", (aid, lista_id))
            for uid in usuarios:
                cur.execute("INSERT INTO alarme_usuarios (alarme_id, usuario_id) VALUES (%s,%s) ON CONFLICT DO NOTHING", (aid, int(uid)))
    return {"id": aid, "ok": True}


@app.put("/api/alarmes/{aid}")
async def update_alarme(aid: int, request: Request):
    # Admin e operador podem atualizar alarmes
    assert_admin_or_operator(request, "Apenas administradores e operadores podem atualizar alarmes")
    data = await request.json()
    sets, vals = [], []
    lista_id = data.get("lista_id")
    if lista_id:
        lista_id = int(lista_id)
    if "prioridade" in data:
        p = str(data["prioridade"]).strip()
        if p not in ("baixa", "media", "alta", "critica"):
            raise HTTPException(status_code=400, detail="prioridade inválida")
        sets.append("prioridade=%s"); vals.append(p)
    if "ativo" in data: sets.append("ativo=%s"); vals.append(bool(data["ativo"]))
    with _conn() as conn:
        with conn.cursor() as cur:
            # Atualizar nome automaticamente se a lista mudou
            if lista_id:
                cur.execute("SELECT name FROM vehicle_lists WHERE id=%s", (lista_id,))
                row = cur.fetchone()
                if not row:
                    raise HTTPException(status_code=400, detail="Lista não encontrada")
                sets.append("nome=%s"); vals.append(f"Alarme - {row[0]}")
            if sets:
                sets.append("atualizado_em=NOW()")
                vals.append(aid)
                cur.execute(f"UPDATE alarmes SET {', '.join(sets)} WHERE id=%s", tuple(vals))
                if cur.rowcount == 0:
                    raise HTTPException(status_code=404, detail="Alarme não encontrado")
            # Atualizar vínculo de lista
            if lista_id:
                cur.execute("DELETE FROM alarme_listas WHERE alarme_id=%s", (aid,))
                cur.execute("INSERT INTO alarme_listas (alarme_id, lista_id) VALUES (%s,%s) ON CONFLICT DO NOTHING", (aid, lista_id))
            # Atualizar vínculos de usuários
            if "usuarios" in data:
                cur.execute("DELETE FROM alarme_usuarios WHERE alarme_id=%s", (aid,))
                for uid in (data["usuarios"] or []):
                    cur.execute("INSERT INTO alarme_usuarios (alarme_id, usuario_id) VALUES (%s,%s) ON CONFLICT DO NOTHING", (aid, int(uid)))
    return {"ok": True}


@app.delete("/api/alarmes/{aid}", status_code=204)
async def delete_alarme(aid: int, request: Request):
    # Admin e operador podem deletar alarmes
    assert_admin_or_operator(request, "Apenas administradores e operadores podem deletar alarmes")
    with _conn() as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM alarmes WHERE id=%s", (aid,))
            if cur.rowcount == 0:
                raise HTTPException(status_code=404, detail="Alarme não encontrado")


@app.post("/api/alarmes/{aid}/test")
async def test_alarme(aid: int, request: Request):
    """Dispara um alerta de teste para os usuários vinculados ao alarme."""
    # Admin e operador podem testar alarmes
    assert_admin_or_operator(request, "Apenas administradores e operadores podem testar alarmes")
    with _conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT nome, tipo, prioridade, mensagem FROM alarmes WHERE id=%s", (aid,))
            row = cur.fetchone()
            if not row:
                raise HTTPException(status_code=404, detail="Alarme não encontrado")
            nome, tipo, prioridade, mensagem = row
            alert = FCMAlert(
                plate="TESTE-0000",
                target_name=nome,
                camera_name="Teste de alarme",
                detected_at=datetime.now(timezone.utc).isoformat(),
                image_url="",
                event_id=f"alarm-test-{aid}-{uuid.uuid4().hex[:8]}",
                city="N/A",
                risk_level=prioridade,
                alert_type=tipo,
            )
            stats = await send_alert_to_alarm_users(
                cur,
                aid,
                alert,
                deactivate_invalid_tokens=False,
                collect_results=True,
            )

    cred = get_fcm_credential_identity()
    resultados = list(stats.get("resultados", []))
    token_ids = list(stats.get("token_ids", []))
    ok = any(bool(item.get("sucesso")) for item in resultados)

    return {
        "ok": ok,
        "alarm_id": aid,
        "alarm_name": nome,
        "tokens_encontrados": int(stats.get("tokens_encontrados", len(token_ids))),
        "tokens_testados": token_ids,
        "project_id": cred.get("project_id", ""),
        "client_email": cred.get("client_email", ""),
        "credentials_path": cred.get("credentials_path", ""),
        "resultados": resultados,
        "linked_users": int(stats.get("linked_users", 0)),
        "users_with_tokens": int(stats.get("users_with_tokens", 0)),
        "sent": int(stats.get("sent", 0)),
        "failed": int(stats.get("failed", 0)),
        "invalid_tokens": int(stats.get("invalid", 0)),
    }


@app.get("/api/alarmes/historico")
async def alarmes_historico(request: Request):
    """Retorna últimos 200 registros de alertas enviados (tabela alertas_criticos)."""
    # Apenas admin pode acessar histórico de alarmes
    assert_admin(request, "Apenas administradores podem acessar histórico de alarmes")
    try:
        with _conn() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT to_regclass('public.alertas_criticos')")
                has_table = bool(cur.fetchone()[0])
                if not has_table:
                    logger.warning("[ALARMES] Tabela public.alertas_criticos não encontrada; retornando histórico vazio")
                    return {"items": []}

                cur.execute(
                    """
                    SELECT column_name
                    FROM information_schema.columns
                    WHERE table_schema='public' AND table_name='alertas_criticos'
                    """
                )
                cols = {row[0] for row in cur.fetchall()}

                if "id" not in cols:
                    logger.error("[ALARMES] Coluna obrigatória 'id' ausente em public.alertas_criticos")
                    return {"items": [], "detail": "Estrutura de histórico inconsistente"}

                select_parts = [
                    "id",
                    ("usuario_id" if "usuario_id" in cols else "NULL::integer") + " AS usuario_id",
                    ("evento_id" if "evento_id" in cols else "NULL::text") + " AS evento_id",
                    ("placa" if "placa" in cols else "''::text") + " AS placa",
                    ("camera_name" if "camera_name" in cols else "''::text") + " AS camera_name",
                    ("target_name" if "target_name" in cols else "''::text") + " AS target_name",
                    ("detected_at" if "detected_at" in cols else "NULL::timestamptz") + " AS detected_at",
                    ("risk_level" if "risk_level" in cols else "''::text") + " AS risk_level",
                    ("alert_type" if "alert_type" in cols else "''::text") + " AS alert_type",
                    ("criado_em" if "criado_em" in cols else "NULL::timestamptz") + " AS criado_em",
                    ("lido" if "lido" in cols else "FALSE") + " AS lido",
                    ("error_message" if "error_message" in cols else "''::text") + " AS error_message",
                ]

                order_col = "criado_em" if "criado_em" in cols else "id"
                cur.execute(f"SELECT {', '.join(select_parts)} FROM alertas_criticos ORDER BY {order_col} DESC LIMIT 200")

                rows = cur.fetchall() or []
                if not rows:
                    return {"items": []}

                items = []
                for r in rows:
                    items.append({
                        "id": int(r[0]) if r[0] is not None else None,
                        "usuario_id": r[1],
                        "event_id": r[2],
                        "placa": str(r[3] or ""),
                        "camera_name": str(r[4] or ""),
                        "target_name": str(r[5] or ""),
                        "detected_at": r[6].isoformat() if isinstance(r[6], datetime) else (str(r[6]) if r[6] else None),
                        "risk_level": str(r[7] or ""),
                        "alert_type": str(r[8] or ""),
                        "criado_em": r[9].isoformat() if isinstance(r[9], datetime) else (str(r[9]) if r[9] else None),
                        "lido": bool(r[10]),
                        "error_message": str(r[11] or ""),
                    })

        return {"items": items}

    except HTTPException:
        raise
    except Exception as e:
        logger.exception("[ALARMES] Erro em GET /api/alarmes/historico: %s", e)
        return {"items": [], "detail": "Erro ao carregar histórico de alarmes"}


@app.post("/api/alarmes/historico/{alert_id}/read")
async def alarmes_historico_mark_read(alert_id: int, request: Request):
    """Marca um alerta do histórico como lido (admin marca qualquer; usuário marca o próprio)."""
    # Admin, operador e visualizador podem marcar alertas como lidos
    require_role(request, "admin", "operador", "visualizador")

    with _conn() as conn:
        with conn.cursor() as cur:
            cur.execute("UPDATE alertas_criticos SET lido=TRUE WHERE id=%s", (alert_id,))
            if cur.rowcount == 0:
                raise HTTPException(status_code=404, detail="Alerta não encontrado")
    return {"ok": True, "id": alert_id, "lido": True}


# ===========================
# ROTAS / TRAJETÓRIA DE PLACA
# ===========================

@app.get("/api/rotas/{plate}")
def rotas_plate(plate: str, limit: int = 1000,
                dt_from: Optional[str] = None, dt_to: Optional[str] = None):
    """
    Retorna a trajetória completa de uma placa, com todos os eventos em ordem
    cronológica, incluindo coordenadas geográficas das câmeras.
    Parâmetros opcionais: dt_from e dt_to (ISO 8601) para filtrar por período.
    Resposta: { rotas: [ { seq, plate, camera_name, event_time, lat, lon,
                            camera_id, local, image_path } ] }
    """
    plate = (plate or "").strip().upper()
    if not plate:
        raise HTTPException(status_code=400, detail="Placa inválida")
    limit = max(1, min(5000, int(limit)))

    # Filtros de data opcionais
    _dt_from = None
    _dt_to   = None
    if dt_from:
        try:
            _dt_from = datetime.fromisoformat(dt_from.replace("Z", "+00:00"))
        except ValueError:
            pass
    if dt_to:
        try:
            _dt_to = datetime.fromisoformat(dt_to.replace("Z", "+00:00"))
        except ValueError:
            pass

    date_clause = ""
    date_params: list = []
    if _dt_from:
        date_clause += " AND COALESCE(e.occurred_at, e.ts) >= %s"
        date_params.append(_dt_from)
    if _dt_to:
        date_clause += " AND COALESCE(e.occurred_at, e.ts) <= %s"
        date_params.append(_dt_to)

    with _conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                f"""
                SELECT
                    e.id,
                    e.plate,
                    COALESCE(c.nome, e.channel_name, e.camera_id) AS camera_name,
                    COALESCE(e.occurred_at, e.ts)                  AS event_time,
                    c.latitude,
                    c.longitude,
                    e.camera_id,
                    COALESCE(c.nome, e.camera_id)                  AS local,
                    e.image_path
                FROM lpr_events e
                LEFT JOIN cameras c ON c.id = (
                    SELECT id FROM cameras
                    WHERE camera_id = e.camera_id
                       OR ip = e.camera_id
                       OR ip = e.camera_ip
                    ORDER BY (camera_id = e.camera_id) DESC
                    LIMIT 1
                )
                WHERE e.plate = %s{date_clause}
                ORDER BY COALESCE(e.occurred_at, e.ts) ASC
                LIMIT %s
                """,
                (plate, *date_params, limit),
            )
            rows = cur.fetchall()

    rotas = []
    for seq, r in enumerate(rows, start=1):
        rotas.append({
            "seq":         seq,
            "plate":       r[1],
            "camera_name": r[2] or "Câmera desconhecida",
            "event_time":  r[3].isoformat() if r[3] else None,
            "lat":         float(r[4]) if r[4] is not None else None,
            "lon":         float(r[5]) if r[5] is not None else None,
            "camera_id":   r[6],
            "local":       r[7] or "Local desconhecido",
            "image_path":  r[8],
        })

    return {"plate": plate, "total": len(rotas), "rotas": rotas}


# ===========================
# CADASTRO POLICIAL — PESSOAS
# ===========================

def _pessoa_row_to_dict(r) -> dict:
    return {
        "id":                  r[0],
        "nome":                r[1],
        "apelido":             r[2],
        "contato":             r[3],
        "profissao":           r[4],
        "cpf":                 r[5],
        "rg":                  r[6],
        "data_nascimento":     r[7].isoformat() if r[7] else None,
        "naturalidade":        r[8],
        "estado_naturalidade": r[9],
        "nome_mae":            r[10],
        "nome_pai":            r[11],
        "data_cadastro":       r[12].isoformat() if r[12] else None,
    }

_PESSOA_SELECT = """
    SELECT id, nome, apelido, contato, profissao, cpf, rg,
           data_nascimento, naturalidade, estado_naturalidade,
           nome_mae, nome_pai, data_cadastro
    FROM pessoas
"""

@app.get("/api/pessoas")
def listar_pessoas(q: Optional[str] = None, limit: int = 50, offset: int = 0):
    """Lista pessoas com busca opcional por nome, apelido ou CPF."""
    limit  = max(1, min(200, int(limit)))
    offset = max(0, int(offset))
    with _conn() as conn:
        with conn.cursor() as cur:
            if q and q.strip():
                term = f"%{q.strip()}%"
                cur.execute(
                    _PESSOA_SELECT +
                    " WHERE nome ILIKE %s OR apelido ILIKE %s OR cpf LIKE %s "
                    " ORDER BY nome ASC LIMIT %s OFFSET %s",
                    (term, term, term, limit, offset),
                )
            else:
                cur.execute(
                    _PESSOA_SELECT + " ORDER BY nome ASC LIMIT %s OFFSET %s",
                    (limit, offset),
                )
            rows = cur.fetchall()
            cur.execute(
                "SELECT COUNT(*) FROM pessoas"
                + (" WHERE nome ILIKE %s OR apelido ILIKE %s OR cpf LIKE %s" if q and q.strip() else ""),
                (f"%{q.strip()}%", f"%{q.strip()}%", f"%{q.strip()}%") if q and q.strip() else (),
            )
            total = cur.fetchone()[0]
    return {"total": total, "pessoas": [_pessoa_row_to_dict(r) for r in rows]}


@app.get("/api/pessoas/{pessoa_id}")
def buscar_pessoa_por_id(pessoa_id: int):
    """Retorna uma pessoa pelo id."""
    with _conn() as conn:
        with conn.cursor() as cur:
            cur.execute(_PESSOA_SELECT + " WHERE id = %s LIMIT 1", (pessoa_id,))
            row = cur.fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Pessoa não encontrada")
    return _pessoa_row_to_dict(row)


@app.post("/api/pessoas", status_code=201)
async def criar_pessoa(request: Request):
    """Cria uma nova pessoa no cadastro policial."""
    data = await request.json()
    nome = (data.get("nome") or "").strip()
    if not nome:
        raise HTTPException(status_code=400, detail="nome é obrigatório")
    cpf_raw = "".join(ch for ch in (data.get("cpf") or "") if ch.isdigit())
    if cpf_raw and len(cpf_raw) > 11:
        raise HTTPException(status_code=400, detail="CPF deve ter no máximo 11 dígitos")
    dn = data.get("data_nascimento") or None
    if dn:
        try:
            from datetime import date as _date
            _date.fromisoformat(dn)
        except ValueError:
            raise HTTPException(status_code=400, detail="data_nascimento inválida (use AAAA-MM-DD)")
    with _conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO pessoas
                    (nome, apelido, contato, profissao, cpf, rg,
                     data_nascimento, naturalidade, estado_naturalidade, nome_mae, nome_pai)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                RETURNING id
                """,
                (
                    nome,
                    (data.get("apelido") or "").strip() or None,
                    (data.get("contato") or "").strip() or None,
                    (data.get("profissao") or "").strip() or None,
                    cpf_raw or None,
                    (data.get("rg") or "").strip() or None,
                    dn or None,
                    (data.get("naturalidade") or "").strip() or None,
                    (data.get("estado_naturalidade") or "").strip() or None,
                    (data.get("nome_mae") or "").strip() or None,
                    (data.get("nome_pai") or "").strip() or None,
                ),
            )
            new_id = cur.fetchone()[0]
    return {"ok": True, "id": new_id}


@app.put("/api/pessoas/{pessoa_id}")
async def atualizar_pessoa(pessoa_id: int, request: Request):
    """Atualiza campos de uma pessoa existente."""
    data = await request.json()
    nome = (data.get("nome") or "").strip()
    if not nome:
        raise HTTPException(status_code=400, detail="nome é obrigatório")
    cpf_raw = "".join(ch for ch in (data.get("cpf") or "") if ch.isdigit())
    if cpf_raw and len(cpf_raw) > 11:
        raise HTTPException(status_code=400, detail="CPF deve ter no máximo 11 dígitos")
    dn = data.get("data_nascimento") or None
    if dn:
        try:
            from datetime import date as _date
            _date.fromisoformat(dn)
        except ValueError:
            raise HTTPException(status_code=400, detail="data_nascimento inválida (use AAAA-MM-DD)")
    with _conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE pessoas SET
                    nome = %s, apelido = %s, contato = %s, profissao = %s,
                    cpf = %s, rg = %s, data_nascimento = %s,
                    naturalidade = %s, estado_naturalidade = %s,
                    nome_mae = %s, nome_pai = %s
                WHERE id = %s
                """,
                (
                    nome,
                    (data.get("apelido") or "").strip() or None,
                    (data.get("contato") or "").strip() or None,
                    (data.get("profissao") or "").strip() or None,
                    cpf_raw or None,
                    (data.get("rg") or "").strip() or None,
                    dn or None,
                    (data.get("naturalidade") or "").strip() or None,
                    (data.get("estado_naturalidade") or "").strip() or None,
                    (data.get("nome_mae") or "").strip() or None,
                    (data.get("nome_pai") or "").strip() or None,
                    pessoa_id,
                ),
            )
            if cur.rowcount == 0:
                raise HTTPException(status_code=404, detail="Pessoa não encontrada")
    return {"ok": True}


@app.delete("/api/pessoas/{pessoa_id}", status_code=204)
def excluir_pessoa(pessoa_id: int):
    """Remove uma pessoa do cadastro."""
    with _conn() as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM pessoas WHERE id = %s", (pessoa_id,))
            if cur.rowcount == 0:
                raise HTTPException(status_code=404, detail="Pessoa não encontrada")
    return None


# ===========================
# ROTA CATCHALL
# ===========================

