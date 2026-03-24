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
from starlette.requests import ClientDisconnect
from starlette.responses import RedirectResponse

import json as _json_lib
import redis as _redis_lib
from rq import Queue as _RQ_Queue

from auth_core import (
    ADMIN_BOOTSTRAP_PASSWORD,
    ADMIN_BOOTSTRAP_USER,
    AuthMiddleware,
    hash_password,
    verify_password,
)
from api.abordagens_router import build_abordagens_router
from api.alarmes_router import build_alarmes_router
from api.admin_activity_router import build_admin_activity_router
from api.auth_router import build_auth_router
from api.alvos_router import build_alvos_router
from api.camera_router import build_camera_router
from api.central_router import build_central_router
from api.comboio_router import build_comboio_router
from api.consulta_router import build_consulta_router
from api.core_router import build_core_router
from api.events_stats_router import build_events_stats_router
from api.fcm_router import build_fcm_router
from api.pessoas_router import build_pessoas_router
from api.produtividade_router import build_produtividade_router
from api.storage_router import build_storage_router
from api.trajetoria_router import build_trajetoria_router
from api.users_router import build_users_router
from api.vehicle_report_router import build_vehicle_report_router
from api.veiculos_abordagem_router import build_veiculos_abordagem_router
from api.vehicles_router import build_vehicles_router
from api.webhook_router import build_webhook_router
from cadastro_support import (
    _clean_cpf,
    _PESSOA_SELECT,
    _VEICULO_SELECT,
    _pessoa_row_to_dict,
    _veiculo_row_to_dict,
)
from watchlist_sync import _sync_alvo_to_lista

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


def _get_int_env(name: str, default: int) -> int:
    try:
        v = (os.getenv(name) or "").strip()
        return int(v) if v else default
    except Exception:
        return default


WEBHOOK_MAX_BODY_BYTES = _get_int_env("WEBHOOK_MAX_BODY_BYTES", 8 * 1024 * 1024)  # 8 MiB
WEBHOOK_REQUIRE_CONTENT_LENGTH = (os.getenv("WEBHOOK_REQUIRE_CONTENT_LENGTH") or "false").strip().lower() in (
    "1",
    "true",
    "yes",
    "on",
)
SNAPSHOT_FALLBACK_ENABLED = (os.getenv("SNAPSHOT_FALLBACK_ENABLED") or "false").strip().lower() in (
    "1",
    "true",
    "yes",
    "on",
)
WEBHOOK_MAX_IMAGES_PER_EVENT = max(1, _get_int_env("WEBHOOK_MAX_IMAGES_PER_EVENT", 1))
YOLO_ENQUEUE_ENABLED = (os.getenv("YOLO_ENQUEUE_ENABLED") or "true").strip().lower() in (
    "1",
    "true",
    "yes",
    "on",
)
YOLO_OCR_FALLBACK_ENABLED = (os.getenv("YOLO_OCR_FALLBACK_ENABLED") or "false").strip().lower() in (
    "1",
    "true",
    "yes",
    "on",
)


def _enforce_webhook_body_limits(request: Request) -> None:
    """
    Protege endpoints de webhook contra payloads grandes.

    Importante: `request.form()` e `request.body()` tendem a carregar o payload todo em RAM.
    Aqui tentamos barrar cedo via `Content-Length`.
    """
    content_length_hdr = (request.headers.get("content-length") or "").strip()
    if content_length_hdr:
        try:
            content_length = int(content_length_hdr)
        except Exception:
            content_length = -1
        if content_length >= 0 and content_length > WEBHOOK_MAX_BODY_BYTES:
            raise HTTPException(status_code=413, detail="Request body too large")
    elif WEBHOOK_REQUIRE_CONTENT_LENGTH:
        raise HTTPException(status_code=411, detail="Content-Length required")


async def _read_body_limited(request: Request, max_bytes: int) -> bytes:
    """
    Lê o body em streaming com limite rígido para evitar explosão de RAM em bursts.
    """
    buf = bytearray()
    total = 0
    async for chunk in request.stream():
        if not chunk:
            continue
        total += len(chunk)
        if total > max_bytes:
            raise HTTPException(status_code=413, detail="Request body too large")
        buf.extend(chunk)
    return bytes(buf)

# ============================================================
# RBAC - Role-Based Access Control
# ============================================================
from rbac import (
    normalize_role,
    require_auth,
    require_role,
    assert_admin,
    assert_admin_or_operator,
    assert_authenticated,
    usuario_eh_admin,
    usuario_pode_editar,
    usuario_pode_cadastrar,
    usuario_somente_visualiza,
)

logger = logging.getLogger(__name__)

# ===========================
# CONFIG
# ===========================

STATIC_DIR = Path("static")
UPLOAD_DIR = Path(os.getenv("UPLOADS_DIR", "uploads"))
ABORDADOS_DIR = Path(os.getenv("ABORDADO_IMAGES_DIR", "abordados"))
METADATA_DIR = Path(os.getenv("METADATA_DIR", "metadata"))
_STORAGE_SETTINGS_CACHE: dict[str, Any] = {"expires_at": 0.0, "values": None}
_STORAGE_SETTINGS_TTL_SECONDS = 10


def _resolve_storage_path(raw_value: str | Path | None, fallback: Path) -> Path:
    raw_text = str(raw_value or "").strip()
    candidate = Path(raw_text) if raw_text else fallback
    if not candidate.is_absolute():
        candidate = (Path.cwd() / candidate).resolve()
    else:
        candidate = candidate.resolve()
    return candidate


def _ensure_storage_dir(path: Path, label: str) -> None:
    if path.exists() and not path.is_dir():
        raise RuntimeError(
            f"{label} '{path.resolve()}' existe mas e um arquivo regular, nao um diretorio."
        )
    path.mkdir(parents=True, exist_ok=True)


def _default_storage_paths() -> dict[str, Path]:
    return {
        "event_images_dir": _resolve_storage_path(UPLOAD_DIR, Path("uploads")),
        "abordagem_images_dir": _resolve_storage_path(ABORDADOS_DIR, Path("abordados")),
        "metadata_dir": _resolve_storage_path(METADATA_DIR, Path("metadata")),
    }

# Inicialização robusta: detecta se o path existe como arquivo (erro comum de
# bind mount incorreto no Docker, ex: host tem arquivo 'uploads' em vez de dir).
for _storage_key, _storage_path in _default_storage_paths().items():
    _ensure_storage_dir(_storage_path, _storage_key)
    logger.info("%s inicializado: %s", _storage_key, _storage_path.resolve())

MIN_LPR_CONFIDENCE = float(os.getenv("MIN_LPR_CONFIDENCE", "0.40"))


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


def _load_storage_settings(force: bool = False) -> dict[str, str]:
    now_ts = datetime.now(timezone.utc).timestamp()
    cached_values = _STORAGE_SETTINGS_CACHE.get("values")
    if not force and cached_values and now_ts < float(_STORAGE_SETTINGS_CACHE.get("expires_at") or 0):
        return dict(cached_values)

    values = {key: str(path) for key, path in _default_storage_paths().items()}
    try:
        with _conn() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT key, path FROM storage_settings")
                for key, path in cur.fetchall():
                    if key in values and path:
                        values[key] = str(_resolve_storage_path(path, Path(values[key])))
    except Exception:
        values = {key: str(path) for key, path in _default_storage_paths().items()}

    _STORAGE_SETTINGS_CACHE["values"] = dict(values)
    _STORAGE_SETTINGS_CACHE["expires_at"] = now_ts + _STORAGE_SETTINGS_TTL_SECONDS
    return values


def _get_storage_dir(key: str) -> Path:
    defaults = _default_storage_paths()
    raw_value = _load_storage_settings().get(key)
    resolved = _resolve_storage_path(raw_value, defaults[key])
    _ensure_storage_dir(resolved, key)
    return resolved


def _set_storage_settings_cache(values: dict[str, str]) -> None:
    _STORAGE_SETTINGS_CACHE["values"] = dict(values)
    _STORAGE_SETTINGS_CACHE["expires_at"] = datetime.now(timezone.utc).timestamp() + _STORAGE_SETTINGS_TTL_SECONDS


def _init_db():
    with _conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS storage_settings (
                    key TEXT PRIMARY KEY,
                    path TEXT NOT NULL,
                    updated_at TIMESTAMPTZ DEFAULT NOW()
                )
                """
            )
            for _storage_key, _storage_path in _default_storage_paths().items():
                cur.execute(
                    """
                    INSERT INTO storage_settings (key, path)
                    VALUES (%s, %s)
                    ON CONFLICT (key) DO NOTHING
                    """,
                    (_storage_key, str(_storage_path)),
                )

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
            # Inserir admin bootstrap se não existir.
            # As credenciais precisam vir do ambiente; não aceitamos defaults inseguros.
            cur.execute("SELECT id FROM users WHERE username=%s LIMIT 1", (ADMIN_BOOTSTRAP_USER,))
            if not cur.fetchone():
                cur.execute(
                    "INSERT INTO users (username, password_hash, full_name, role) VALUES (%s, %s, %s, %s)",
                    (ADMIN_BOOTSTRAP_USER, hash_password(ADMIN_BOOTSTRAP_PASSWORD), "Administrador", "admin")
                )

            # Auditoria administrativa de acessos e presenca online
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS admin_user_sessions (
                    id SERIAL PRIMARY KEY,
                    session_id TEXT UNIQUE NOT NULL,
                    username TEXT NOT NULL,
                    full_name TEXT DEFAULT '',
                    role TEXT DEFAULT 'visualizador',
                    login_at TIMESTAMPTZ DEFAULT NOW(),
                    last_seen_at TIMESTAMPTZ DEFAULT NOW(),
                    logout_at TIMESTAMPTZ,
                    last_page_key TEXT,
                    last_page_label TEXT,
                    last_page_path TEXT,
                    ip_address TEXT,
                    user_agent TEXT,
                    is_online BOOLEAN DEFAULT TRUE
                );
                """
            )
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS admin_user_activity_log (
                    id BIGSERIAL PRIMARY KEY,
                    session_id TEXT,
                    username TEXT NOT NULL,
                    full_name TEXT DEFAULT '',
                    role TEXT DEFAULT 'visualizador',
                    activity_type TEXT NOT NULL,
                    page_key TEXT,
                    page_label TEXT,
                    page_path TEXT,
                    details JSONB DEFAULT '{}'::jsonb,
                    ip_address TEXT,
                    user_agent TEXT,
                    created_at TIMESTAMPTZ DEFAULT NOW()
                );
                """
            )
            cur.execute(
                "CREATE INDEX IF NOT EXISTS idx_admin_user_sessions_online ON admin_user_sessions(is_online, last_seen_at DESC);"
            )
            cur.execute(
                "CREATE INDEX IF NOT EXISTS idx_admin_user_sessions_username ON admin_user_sessions(username, last_seen_at DESC);"
            )
            cur.execute(
                "CREATE INDEX IF NOT EXISTS idx_admin_user_activity_user_time ON admin_user_activity_log(username, created_at DESC);"
            )
            cur.execute(
                "CREATE INDEX IF NOT EXISTS idx_admin_user_activity_type_time ON admin_user_activity_log(activity_type, created_at DESC);"
            )

            # Indicadores de produtividade operacional do painel
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS painel_produtividade (
                    id INTEGER PRIMARY KEY,
                    armas_apreendidas INTEGER NOT NULL DEFAULT 0,
                    drogas_apreendidas_kg NUMERIC(14,2) NOT NULL DEFAULT 0,
                    peso_kg NUMERIC(14,2) NOT NULL DEFAULT 0,
                    drogas_toneladas NUMERIC(14,3) NOT NULL DEFAULT 0,
                    veiculos_recuperados INTEGER NOT NULL DEFAULT 0,
                    updated_at TIMESTAMPTZ DEFAULT NOW(),
                    updated_by TEXT DEFAULT ''
                );
                """
            )
            cur.execute("ALTER TABLE painel_produtividade ADD COLUMN IF NOT EXISTS armas_apreendidas INTEGER NOT NULL DEFAULT 0;")
            cur.execute("ALTER TABLE painel_produtividade ADD COLUMN IF NOT EXISTS drogas_apreendidas_kg NUMERIC(14,2) NOT NULL DEFAULT 0;")
            cur.execute("ALTER TABLE painel_produtividade ADD COLUMN IF NOT EXISTS peso_kg NUMERIC(14,2) NOT NULL DEFAULT 0;")
            cur.execute("ALTER TABLE painel_produtividade ADD COLUMN IF NOT EXISTS drogas_toneladas NUMERIC(14,3) NOT NULL DEFAULT 0;")
            cur.execute("ALTER TABLE painel_produtividade ADD COLUMN IF NOT EXISTS veiculos_recuperados INTEGER NOT NULL DEFAULT 0;")
            cur.execute("ALTER TABLE painel_produtividade ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ DEFAULT NOW();")
            cur.execute("ALTER TABLE painel_produtividade ADD COLUMN IF NOT EXISTS updated_by TEXT DEFAULT '';")
            cur.execute("INSERT INTO painel_produtividade (id) VALUES (1) ON CONFLICT (id) DO NOTHING;")
            cur.execute(
                """
                UPDATE painel_produtividade
                SET drogas_apreendidas_kg = CASE
                    WHEN COALESCE(drogas_apreendidas_kg, 0) > 0 THEN drogas_apreendidas_kg
                    WHEN COALESCE(peso_kg, 0) > 0 THEN peso_kg
                    WHEN COALESCE(drogas_toneladas, 0) > 0 THEN drogas_toneladas * 1000
                    ELSE 0
                END
                WHERE COALESCE(drogas_apreendidas_kg, 0) = 0;
                """
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
            # Sincronização veículo ↔ alvos rastreados
            cur.execute("ALTER TABLE vehicle_list_items ADD COLUMN IF NOT EXISTS is_alvo BOOLEAN NOT NULL DEFAULT FALSE;")

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
                    foto_path TEXT,
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
            cur.execute("ALTER TABLE pessoas ADD COLUMN IF NOT EXISTS foto_path TEXT;")
            # Colunas legadas (mantidas para compatibilidade durante migração — NÃO remover ainda)
            cur.execute("ALTER TABLE pessoas ADD COLUMN IF NOT EXISTS relatorio_abordagem TEXT;")
            cur.execute("ALTER TABLE pessoas ADD COLUMN IF NOT EXISTS veiculo_placa TEXT;")
            cur.execute("ALTER TABLE pessoas ADD COLUMN IF NOT EXISTS veiculo_modelo TEXT;")
            cur.execute("ALTER TABLE pessoas ADD COLUMN IF NOT EXISTS veiculo_cor TEXT;")
            cur.execute("ALTER TABLE pessoas ADD COLUMN IF NOT EXISTS ocupantes TEXT;")
            # Novo campo de endereço
            cur.execute("ALTER TABLE pessoas ADD COLUMN IF NOT EXISTS endereco TEXT;")
            cur.execute("CREATE INDEX IF NOT EXISTS idx_pessoas_rg ON pessoas(rg);")

            # ==================================================
            # MÓDULO ABORDAGENS — novas tabelas relacionais
            # ==================================================

            # Veículos de abordagem (entidade própria)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS veiculos_abordagem (
                    id            SERIAL PRIMARY KEY,
                    placa         TEXT,
                    marca         TEXT,
                    modelo        TEXT,
                    cor           TEXT,
                    ano           INT,
                    tipo          TEXT,
                    foto_path     TEXT,
                    observacoes   TEXT,
                    data_cadastro TIMESTAMPTZ DEFAULT NOW()
                );
            """)
            cur.execute("ALTER TABLE veiculos_abordagem ADD COLUMN IF NOT EXISTS foto_path TEXT;")
            cur.execute("CREATE INDEX IF NOT EXISTS idx_veiculo_abord_placa ON veiculos_abordagem(placa);")

            # Abordagem — entidade principal
            cur.execute("""
                CREATE TABLE IF NOT EXISTS abordagens (
                    id            SERIAL PRIMARY KEY,
                    data_hora     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    local         TEXT,
                    equipe        TEXT,
                    tipo_motivo   TEXT,
                    observacoes   TEXT,
                    veiculo_id    INT REFERENCES veiculos_abordagem(id) ON DELETE SET NULL,
                    data_cadastro TIMESTAMPTZ DEFAULT NOW()
                );
            """)
            cur.execute("CREATE INDEX IF NOT EXISTS idx_abordagens_data ON abordagens(data_hora);")
            cur.execute("CREATE INDEX IF NOT EXISTS idx_abordagens_veiculo ON abordagens(veiculo_id);")

            # Vínculo N:N abordagem ↔ pessoa com papel
            cur.execute("""
                CREATE TABLE IF NOT EXISTS abordagem_pessoas (
                    id                  SERIAL PRIMARY KEY,
                    abordagem_id        INT NOT NULL REFERENCES abordagens(id) ON DELETE CASCADE,
                    pessoa_id           INT NOT NULL REFERENCES pessoas(id) ON DELETE CASCADE,
                    papel               TEXT NOT NULL DEFAULT 'outro',
                    observacao_pessoal  TEXT,
                    data_cadastro       TIMESTAMPTZ DEFAULT NOW(),
                    UNIQUE(abordagem_id, pessoa_id)
                );
            """)
            cur.execute("CREATE INDEX IF NOT EXISTS idx_abord_pess_abord ON abordagem_pessoas(abordagem_id);")
            cur.execute("CREATE INDEX IF NOT EXISTS idx_abord_pess_pess  ON abordagem_pessoas(pessoa_id);")

            # ==================================================
            # MIGRAÇÃO SEGURA — dados legados de pessoas
            # Migra registros antigos que têm veiculo_placa preenchida
            # para veiculos_abordagem + abordagens + abordagem_pessoas.
            # Executa somente se ainda não migrado (flag _migracao_legado).
            # ==================================================
            cur.execute("""
                DO $$
                BEGIN
                    -- Garante idempotência: só roda se coluna legada existir e migração não foi feita
                    IF EXISTS (
                        SELECT 1 FROM information_schema.columns
                        WHERE table_name='pessoas' AND column_name='veiculo_placa'
                    ) THEN
                        -- Para cada pessoa antiga com veiculo e sem abordagem relacional
                        INSERT INTO veiculos_abordagem (placa, marca, modelo, cor)
                        SELECT DISTINCT
                            UPPER(TRIM(veiculo_placa)),
                            NULL,
                            veiculo_modelo,
                            veiculo_cor
                        FROM pessoas
                        WHERE veiculo_placa IS NOT NULL AND TRIM(veiculo_placa) <> ''
                          AND NOT EXISTS (
                            SELECT 1 FROM veiculos_abordagem v
                             WHERE v.placa = UPPER(TRIM(pessoas.veiculo_placa))
                          );

                        -- Cria uma abordagem por pessoa que tinha veiculo/relatorio e não tem abordagem vinculada
                        INSERT INTO abordagens (data_hora, local, tipo_motivo, observacoes, veiculo_id, data_cadastro)
                        SELECT
                            COALESCE(p.data_cadastro, NOW()),
                            NULL,
                            'Legado (migrado)',
                            p.relatorio_abordagem,
                            va.id,
                            COALESCE(p.data_cadastro, NOW())
                        FROM pessoas p
                        LEFT JOIN veiculos_abordagem va
                            ON va.placa = UPPER(TRIM(p.veiculo_placa))
                        WHERE (p.veiculo_placa IS NOT NULL OR p.relatorio_abordagem IS NOT NULL)
                          AND NOT EXISTS (
                            SELECT 1 FROM abordagem_pessoas ap
                             JOIN abordagens ab ON ab.id = ap.abordagem_id
                            WHERE ap.pessoa_id = p.id AND ab.tipo_motivo = 'Legado (migrado)'
                          );

                        -- Vincula pessoa → abordagem legada criada acima
                        INSERT INTO abordagem_pessoas (abordagem_id, pessoa_id, papel)
                        SELECT
                            ab.id,
                            p.id,
                            'outro'
                        FROM pessoas p
                        JOIN abordagens ab
                            ON ab.tipo_motivo = 'Legado (migrado)'
                           AND ab.data_hora = COALESCE(p.data_cadastro, NOW())
                        WHERE (p.veiculo_placa IS NOT NULL OR p.relatorio_abordagem IS NOT NULL)
                          AND NOT EXISTS (
                            SELECT 1 FROM abordagem_pessoas ap2
                             WHERE ap2.abordagem_id = ab.id AND ap2.pessoa_id = p.id
                          );
                    END IF;
                END $$;
            """)


# ===========================
# HELPERS
# ===========================

def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


# ---------------------------------------------------------------------------
# Central de Ameaças — Fase 1: vínculo direto com alvos cadastrados
# ---------------------------------------------------------------------------

def _normalize_plate(plate: str) -> str:
    """Normaliza placa: uppercase, sem espaços, sem hífen."""
    return (plate or "").upper().replace(" ", "").replace("-", "")


def compute_threat_center_phase1(
    plates: list,
    alvo_map: dict,
    leader: str = None,
) -> dict:
    """
    Fase 1 da Central de Ameaças: detecção de vínculo direto com alvos cadastrados.

    Parâmetros:
      plates    – lista de placas do grupo/companhia
      alvo_map  – {plate_raw: descricao} como vem do BD
      leader    – placa do líder/batedor (opcional)

    Retorna bloco threat_center:
      matched_target   – bool
      match_type       – "plate" | "leader" | "both" | null
      matched_plates   – placas do grupo que são alvos
      leader_is_target – bool (líder é alvo cadastrado)
      threat_badges    – ["ALVO_NO_GRUPO", "LÍDER_É_ALVO"]
      score_delta      – incremento de score sugerido (20 por placa alvo)
    """
    norm_map = {_normalize_plate(k): v for k, v in alvo_map.items()}

    matched = [p for p in plates if _normalize_plate(p) in norm_map]
    leader_is_target = bool(leader and _normalize_plate(leader) in norm_map)

    badges: list = []
    if matched:
        badges.append("ALVO_NO_GRUPO")
    if leader_is_target:
        badges.append("LÍDER_É_ALVO")

    if matched and leader_is_target:
        match_type = "both"
    elif leader_is_target:
        match_type = "leader"
    elif matched:
        match_type = "plate"
    else:
        match_type = None

    return {
        "matched_target":   bool(matched) or leader_is_target,
        "match_type":       match_type,
        "matched_plates":   matched,
        "leader_is_target": leader_is_target,
        "threat_badges":    badges,
        "score_delta":      20 * len(matched),
    }


# ---------------------------------------------------------------------------
# Central de Ameaças — Fase 2: similaridade de rota com alvos cadastrados
# ---------------------------------------------------------------------------

def compute_threat_center_phase2_route_similarity(
    group_cameras: list,
    group_cities:  list,
    alvo_routes:   dict,
    threshold:     float = 0.30,
) -> dict:
    """
    Fase 2 da Central de Ameaças: compara a rota do grupo suspeito com as
    rotas históricas de alvos cadastrados.

    Parâmetros:
      group_cameras – lista de camera_id que o grupo percorreu (ordenada)
      group_cities  – lista de cam_nome/localidade (ordenada, pode ter dups)
      alvo_routes   – {plate_norm: {"cameras": [...], "cities": [...]}}
                      rotas dos alvos (pre-fetchadas do BD, 30 dias)
      threshold     – similarity_ratio mínimo para considerar "parecido"

    Retorna dict mesclável com o bloco threat_center:
      route_similarity – bloco detalhado
      threat_badges    – ["ROTA_PARECIDA"] se matched, else []
      score_delta      – incremento proporcional à similaridade
    """
    empty_route = {
        "matched":          False,
        "best_alvo":        None,
        "common_cities":    [],
        "common_cameras":   [],
        "similarity_ratio": 0.0,
    }

    if not group_cameras or not alvo_routes:
        return {"route_similarity": empty_route, "threat_badges": [], "score_delta": 0}

    g_cam_set  = {c for c in group_cameras if c}
    g_city_set = {c for c in group_cities  if c}

    best_ratio   = 0.0
    best_alvo    = None
    best_cams    = []
    best_cities  = []

    for alvo_plate, route in alvo_routes.items():
        a_cam_set = {c for c in route.get("cameras", []) if c}
        if not a_cam_set:
            continue
        common_cams = g_cam_set & a_cam_set
        union_cams  = g_cam_set | a_cam_set
        ratio = len(common_cams) / len(union_cams) if union_cams else 0.0
        if ratio > best_ratio:
            best_ratio  = ratio
            best_alvo   = alvo_plate
            best_cams   = sorted(common_cams)
            best_cities = sorted(g_city_set & {c for c in route.get("cities", []) if c})

    matched     = best_ratio >= threshold
    badges      = ["ROTA_PARECIDA"] if matched else []
    score_delta = int(best_ratio * 30) if matched else 0

    return {
        "route_similarity": {
            "matched":          matched,
            "best_alvo":        best_alvo,
            "common_cities":    best_cities,
            "common_cameras":   best_cams,
            "similarity_ratio": round(best_ratio, 3),
        },
        "threat_badges": badges,
        "score_delta":   score_delta,
    }


def _merge_threat_center_phases(tc1: dict, tc2: dict) -> dict:
    """
    Mescla o bloco threat_center da Fase 1 com o resultado da Fase 2.
    Preserva todos os campos existentes e adiciona novos sem sobrescrever.
    """
    merged = tc1.copy()
    merged["threat_badges"] = list(
        set(tc1.get("threat_badges", [])) | set(tc2.get("threat_badges", []))
    )
    merged["score_delta"]      = tc1.get("score_delta", 0) + tc2.get("score_delta", 0)
    merged["matched_target"]   = tc1.get("matched_target", False) or bool(tc2.get("threat_badges"))
    merged["route_similarity"] = tc2.get("route_similarity", {
        "matched": False, "best_alvo": None,
        "common_cities": [], "common_cameras": [], "similarity_ratio": 0.0,
    })
    return merged


def _fetch_alvo_routes(cur, alvo_plates: list, t_from, t_to) -> dict:
    """
    Busca as rotas históricas (camera_id + cam_nome) de cada alvo no período.
    Retorna {plate_norm: {"cameras": [...], "cities": [...]}}
    """
    routes: dict = {}
    if not alvo_plates:
        return routes
    cur.execute("""
        SELECT
            e.plate,
            e.camera_id,
            COALESCE(c.nome, e.camera_id) AS cam_nome
        FROM lpr_events e
        LEFT JOIN cameras c ON c.camera_id = e.camera_id
        WHERE e.plate = ANY(%s)
          AND COALESCE(e.occurred_at, e.ts) BETWEEN %s AND %s
        ORDER BY e.plate, COALESCE(e.occurred_at, e.ts)
    """, [alvo_plates, t_from, t_to])
    for _plate, _cam_id, _cam_nome in cur.fetchall():
        _n = _normalize_plate(_plate)
        if _n not in routes:
            routes[_n] = {"cameras": [], "cities": []}
        routes[_n]["cameras"].append(_cam_id)
        routes[_n]["cities"].append(_cam_nome)
    return routes


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
    Fallback restrito: busca câmera pelo channelName do XML apenas quando houver
    correspondência EXATA (após normalização) com camera_id ou nome.

    Isso evita o casamento frouxo por "nome parecido", que podia associar um
    evento à câmera errada quando havia canais com nomes semelhantes.
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
        matches = []
        for row in rows:
            cam_id_norm = _norm(row[1] or "")
            cam_nome_norm = _norm(row[2] or "")
            if needle == cam_id_norm or needle == cam_nome_norm:
                matches.append(
                    {
                        "id": row[0], "camera_id": row[1], "nome": row[2],
                        "ativa": row[3], "criticidade": (row[4] or "NORMAL").upper(),
                        "peso": float(row[5] or 1.0), "peso_score": float(row[5] or 1.0),
                        "ip": row[7], "direcao": row[8] or None,
                        "latitude": float(row[9]) if row[9] is not None else None,
                        "longitude": float(row[10]) if row[10] is not None else None,
                    }
                )
        if len(matches) == 1:
            return matches[0]
        if len(matches) > 1:
            print(
                f"[CAMERA] _lookup_camera_by_channel ambíguo channel_name={channel_name!r} "
                f"matches={[m['camera_id'] for m in matches]}"
            )
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
app.add_middleware(AuthMiddleware)

# static
STATIC_DIR.mkdir(parents=True, exist_ok=True)
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


app.include_router(build_auth_router(_conn))
app.include_router(build_admin_activity_router(_conn))
app.include_router(build_camera_router(_conn, get_camera_row))
app.include_router(
    build_storage_router(
        _conn,
        require_auth,
        assert_admin,
        _resolve_storage_path,
        _ensure_storage_dir,
        _get_storage_dir,
        _default_storage_paths,
        _set_storage_settings_cache,
    )
)
app.include_router(build_produtividade_router(_conn))
app.include_router(
    build_pessoas_router(
        _conn,
        require_auth,
        assert_admin,
        assert_admin_or_operator,
        verify_password,
        lambda value: _s(value),
        lambda value: _parse_date(value),
    )
)
app.include_router(build_users_router(_conn))
app.include_router(
    build_veiculos_abordagem_router(
        _conn,
        require_auth,
        assert_admin_or_operator,
        lambda value: _s(value),
    )
)
app.include_router(
    build_abordagens_router(
        _conn,
        require_auth,
        assert_admin,
        assert_admin_or_operator,
        lambda value: _s(value),
        _clean_cpf,
        lambda value: _parse_date(value),
        _utcnow,
        _normalize_plate,
        _sync_alvo_to_lista,
        lambda: _get_storage_dir("abordagem_images_dir"),
    )
)
app.include_router(build_consulta_router(_conn, require_auth))
app.include_router(
    build_fcm_router(
        _conn,
        assert_admin,
        _resolve_user_numeric_id_from_sub,
        register_fcm_token,
        is_likely_fake_token,
        FCMAlert,
        send_alert_to_alarm_users,
        send_alert_to_user_tokens,
        get_fcm_credential_identity,
        logger,
    )
)
app.include_router(
    build_alarmes_router(
        _conn,
        require_role,
        assert_admin,
        assert_admin_or_operator,
        FCMAlert,
        send_alert_to_alarm_users,
        get_fcm_credential_identity,
        logger,
    )
)
app.include_router(build_vehicles_router(_conn))
app.include_router(
    build_alvos_router(
        _conn,
        require_auth,
        lambda window: _parse_window_to_minutes(window),
        _parse_dt,
    )
)
app.include_router(
    build_trajetoria_router(
        _conn,
        require_auth,
        lambda *args, **kwargs: _detect_convoy_groups(*args, **kwargs),
    )
)
app.include_router(
    build_vehicle_report_router(
        _conn,
        assert_admin_or_operator,
        _utcnow,
        lambda window: _parse_window_to_minutes(window),
        lambda *args, **kwargs: _detect_convoy_groups(*args, **kwargs),
    )
)
app.include_router(
    build_comboio_router(
        _conn,
        assert_admin_or_operator,
        lambda window: _parse_window_to_minutes(window),
        _utcnow,
        lambda *args, **kwargs: _detect_convoy_groups(*args, **kwargs),
        _fetch_alvo_routes,
        compute_threat_center_phase1,
        compute_threat_center_phase2_route_similarity,
        _merge_threat_center_phases,
    )
)
app.include_router(
    build_central_router(
        _conn,
        _utcnow,
        _parse_dt,
        lambda window: _parse_window_to_minutes(window),
        _normalize_plate,
        lambda *args, **kwargs: _detect_convoy_groups(*args, **kwargs),
        _fetch_alvo_routes,
        compute_threat_center_phase1,
        compute_threat_center_phase2_route_similarity,
        _merge_threat_center_phases,
        logger,
    )
)
app.include_router(
    build_events_stats_router(
        _conn,
        _parse_dt,
        _utcnow,
        get_event_by_id,
    )
)
app.include_router(build_core_router(STATIC_DIR, lambda request: _catchall_handler(request)))
app.include_router(build_webhook_router(lambda request, background_tasks: simple_webhook_handler(request, background_tasks)))


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
    upload_dir = _get_storage_dir("event_images_dir")
    d     = upload_dir / day
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
    abs_path = str((d / fname).resolve())
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

async def simple_webhook_handler(request: Request, background_tasks: BackgroundTasks):
    client_ip = _get_client_ip(request)
    content_type = request.headers.get("content-type", "")
    ct_lower = content_type.lower()

    _enforce_webhook_body_limits(request)

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
        _form_text_fields = {}
        _parser_used = f"multipart/manual ({ct_lower.split(';')[0].strip()})"
        try:
            body_raw = await _read_body_limited(request, WEBHOOK_MAX_BODY_BYTES)
        except ClientDisconnect:
            return JSONResponse({"ok": True})
        logger.info(
            "[WEBHOOK-DIAG] multipart ip=%s len=%d primeiros_500=%r",
            client_ip, len(body_raw), body_raw[:500].decode("utf-8", errors="replace"),
        )
        xml_bytes, images = _parse_multipart_body(content_type, body_raw)
        logger.info(
            "[WEBHOOK-HTTP-ESCUTA] ip=%s campos_form=%r xml_bytes=%s images=%d",
            client_ip,
            [],
            len(xml_bytes) if xml_bytes else 0,
            len(images),
        )

    else:
        _form_text_fields = {}
        body = await _read_body_limited(request, WEBHOOK_MAX_BODY_BYTES)

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

            # camera_id a partir do XML: apenas o IP real do XML.
            # channel_name_xml e channel_id_xml NÃO definem camera_id —
            # são usados somente como nome/canal auxiliar.
            # A resolução final de camera_id acontece abaixo, fora do bloco XML,
            # com prioridade: X-Camera-IP > xml_ip > client_ip.
            if xml_ip:
                camera_id = xml_ip

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
            # Tipos de evento Hikvision que indicam leitura LPR/ANPR:
            # - "ANPR"                → firmware moderno ISAPI
            # - "vehicleDetection"   → firmware antigo (< V4.x) e câmeras DS-2CD série
            # - "trafficVehicle"     → câmeras de tráfego Hikvision
            # - "anprdetection"      → alias encontrado em alguns firmwares
            # Se xml_event_type está ausente (None), não descarta — câmera pode omitir
            _LPR_EVENT_TYPES = {"anpr", "vehicledetection", "trafficvehicle", "anprdetection",
                                 "vehiclepassage", "vehicleevent", "licenseplate"}
            _is_non_lpr_event = (
                xml_event_type is not None
                and xml_event_type.lower() not in _LPR_EVENT_TYPES
            )
            if _is_non_lpr_event:
                logger.info(
                    "[WEBHOOK-NOT-ANPR] ip=%s eventType=%r — evento não é LPR/ANPR, placa descartada",
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

    # ── Resolução final de camera_id ──────────────────────────────────────────
    # Prioridade: X-Camera-IP (header) > xml_ip (do XML) > client_ip (TCP)
    # channel_name_xml e channel_id_xml NUNCA são usados como identidade da câmera;
    # servem apenas como nome/canal auxiliar para exibição.
    _header_ip = request.headers.get("X-Camera-IP", "").strip()
    if _header_ip:
        # X-Camera-IP tem prioridade máxima — enviado pelo camera-poller ou proxy
        camera_id = _header_ip
        xml_ip    = xml_ip or _header_ip
    elif xml_ip:
        # IP real extraído do XML <ipAddress> — confiável quando presente
        camera_id = xml_ip
    else:
        # Fallback: IP TCP da conexão HTTP (client_ip)
        camera_id = client_ip
        xml_ip    = client_ip

    # Log obrigatório: mostra todos os candidatos e a decisão final
    logger.info(
        "[WEBHOOK-CAM-RESOLVE] client_ip=%s header_ip=%s xml_ip=%s "
        "channel_name_xml=%r channel_id_xml=%r → camera_id=%s",
        client_ip,
        _header_ip or "-",
        xml_ip or "-",
        channel_name_xml or "-",
        channel_id_xml if 'channel_id_xml' in dir() else "-",
        camera_id,
    )

    if camera_id:
        # nome padrão = channelName do XML; fallback = próprio camera_id
        default_nome = channel_name_xml or camera_id
        cam = ensure_camera_exists(camera_id, default_name=default_nome, ip=xml_ip)

        # Fallback restrito: só aceita channelName quando o casamento for exato e único.
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
    if not plate and images and YOLO_OCR_FALLBACK_ENABLED:
        lpr_meta["needs_ocr"] = True

    # ── Salva imagem enviada no POST (se houver) ──────────────────────────
    # Apenas salva o arquivo em disco aqui; o job YOLO é enfileirado DEPOIS
    # do INSERT para que event_id já exista no banco quando o worker rodar.
    _yolo_jobs_pending: list[tuple[str, str]] = []   # (abs_path, image_path)
    selected_images = images[:WEBHOOK_MAX_IMAGES_PER_EVENT]
    dropped_images = max(0, len(images) - len(selected_images))
    if dropped_images:
        logger.warning(
            "[WEBHOOK] %d imagem(ns) descartada(s) por limite do evento camera_id=%s limit=%d",
            dropped_images,
            camera_id,
            WEBHOOK_MAX_IMAGES_PER_EVENT,
        )
    for _img_name, data in selected_images:
        day   = (occurred_at or _utcnow()).strftime("%Y-%m-%d")
        upload_dir = _get_storage_dir("event_images_dir")
        d     = upload_dir / day
        d.mkdir(parents=True, exist_ok=True)
        fname = f"{uuid.uuid4().hex}.jpg"
        try:
            (d / fname).write_bytes(data)
            image_path = f"/uploads/{day}/{fname}"
            abs_path   = str((d / fname).resolve())
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
            if YOLO_ENQUEUE_ENABLED:
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

    # Snapshot fallback é opt-in porque, sob carga, um GET por evento pode saturar a câmera/ingest.
    if (
        SNAPSHOT_FALLBACK_ENABLED
        and not image_path
        and cam.get("ip")
        and cam.get("usuario")
        and cam.get("senha")
    ):
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

    if target_plate:
        cur.execute(
            """
            SELECT
                e.camera_id,
                COALESCE(e.ts, e.occurred_at) AS sort_time
            FROM lpr_events e
            WHERE e.plate = %s
              AND COALESCE(e.occurred_at, e.ts) BETWEEN %s AND %s
            ORDER BY e.camera_id, COALESCE(e.ts, e.occurred_at), e.id
            LIMIT 5000
            """,
            [target_plate, t_from, t_to],
        )
        target_rows = cur.fetchall()
        if not target_rows:
            return []

        target_ranges: dict[str, list[tuple]] = defaultdict(list)
        for cam_id, sort_time in target_rows:
            target_ranges[cam_id].append(
                (
                    sort_time - timedelta(seconds=window_s),
                    sort_time + timedelta(seconds=window_s),
                )
            )

        merged_ranges: dict[str, list[tuple]] = {}
        for cam_id, ranges in target_ranges.items():
            ranges = sorted(ranges, key=lambda item: item[0])
            merged: list[tuple] = []
            for start_at, end_at in ranges:
                if not merged or start_at > merged[-1][1]:
                    merged.append((start_at, end_at))
                else:
                    merged[-1] = (merged[-1][0], max(merged[-1][1], end_at))
            merged_ranges[cam_id] = merged

        target_clauses: list[str] = []
        target_vals: list = []
        for cam_id, ranges in merged_ranges.items():
            for start_at, end_at in ranges:
                target_clauses.append("(e.camera_id = %s AND COALESCE(e.ts, e.occurred_at) BETWEEN %s AND %s)")
                target_vals.extend([cam_id, start_at, end_at])
        target_sql = "AND (" + " OR ".join(target_clauses) + ")"
    else:
        target_sql = ""
        target_vals = []

    cur.execute(f"""
        SELECT
            e.camera_id,
            COALESCE(c.nome, e.camera_id)   AS cam_nome,
            e.plate,
            COALESCE(e.occurred_at, e.ts)   AS event_time,
            COALESCE(e.ts, e.occurred_at)   AS sort_time
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
          {target_sql}
          {prefix_sql} {allow_sql}
        ORDER BY e.camera_id, COALESCE(e.ts, e.occurred_at), e.id
        LIMIT {int(limit_events)}
    """, [t_from, t_to] + target_vals + prefix_vals + allow_vals)
    rows = cur.fetchall()

    # ── 2. Agrupar por câmera ──────────────────────────────────────────────
    cam_events: dict = defaultdict(list)
    for cam_id, cam_nome, plate, event_time, sort_time in rows:
        cam_events[cam_id].append((plate, event_time, sort_time, cam_nome))

    # ── 3. Formar clusters por câmera (janela deslizante) ──────────────────
    # Para cada câmera, encontra conjuntos de placas onde span <= window_s
    # Resultado: cam_plate_sets[camera_id] = [{"plates": frozenset, "ts_min", "ts_max", "plate_times"}]
    cam_plate_sets: dict = defaultdict(list)

    for cam_id, events in cam_events.items():
        n = len(events)
        if n < 2:
            continue
        cam_nome = events[0][3]

        # Janela deslizante: i=início, j avança enquanto span <= window_s
        i = 0
        while i < n:
            j = i + 1
            while j < n and (events[j][2] - events[i][2]).total_seconds() <= window_s:
                j += 1
            # events[i..j-1] formam um cluster temporal
            # Extrair placas únicas e seus timestamps
            plate_times: dict = {}
            for k in range(i, j):
                p, event_t, sort_t, _ = events[k]
                if p not in plate_times:
                    plate_times[p] = {
                        "event_min": event_t,
                        "event_max": event_t,
                        "sort_min": sort_t,
                        "sort_max": sort_t,
                    }
                else:
                    if event_t < plate_times[p]["event_min"]:
                        plate_times[p]["event_min"] = event_t
                    if event_t > plate_times[p]["event_max"]:
                        plate_times[p]["event_max"] = event_t
                    if sort_t < plate_times[p]["sort_min"]:
                        plate_times[p]["sort_min"] = sort_t
                    if sort_t > plate_times[p]["sort_max"]:
                        plate_times[p]["sort_max"] = sort_t

            unique_plates = set(plate_times.keys())
            if len(unique_plates) >= 2:
                all_event_ts = [events[k][1] for k in range(i, j)]
                all_sort_ts = [events[k][2] for k in range(i, j)]
                ts_min = min(all_event_ts)
                ts_max = max(all_event_ts)
                sort_ts_min = min(all_sort_ts)
                sort_ts_max = max(all_sort_ts)
                cam_plate_sets[cam_id].append({
                    "plates": frozenset(unique_plates),
                    "ts_min": ts_min,
                    "ts_max": ts_max,
                    "sort_ts_min": sort_ts_min,
                    "sort_ts_max": sort_ts_max,
                    "span_sec": (sort_ts_max - sort_ts_min).total_seconds(),
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
                    sub_event_times = []
                    sub_sort_times = []
                    sub_plate_times = {}
                    for p in subset:
                        pt = cluster["plate_times"][p]
                        sub_event_times.append(pt["event_min"])
                        sub_event_times.append(pt["event_max"])
                        sub_sort_times.append(pt["sort_min"])
                        sub_sort_times.append(pt["sort_max"])
                        sub_plate_times[p] = pt
                    sub_ts_min = min(sub_event_times)
                    sub_ts_max = max(sub_event_times)
                    sub_sort_ts_min = min(sub_sort_times)
                    sub_sort_ts_max = max(sub_sort_times)
                    sub_span = (sub_sort_ts_max - sub_sort_ts_min).total_seconds()
                    if sub_span > window_s:
                        continue
                    # Usa a sequência de ingestão para manter a ordem estável
                    # mesmo quando uma câmera está com o relógio incorreto.
                    plate_order = sorted(subset, key=lambda p: (sub_plate_times[p]["sort_min"], p))
                    ts_rep = sub_sort_ts_min
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
        for idx, c in enumerate(sorted_cams, start=1):
            cameras_confirmed.append({
                "camera_id": c["camera_id"],
                "cam_nome": c["cam_nome"],
                "ts_min": c["ts_min"].isoformat(),
                "ts_max": c["ts_max"].isoformat(),
                "span_sec": c["span_sec"],
                "plate_order": c["plate_order"],
                "timeline_index": idx,
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


# ===========================
# MÓDULO ABORDAGENS — HELPERS
# ===========================

def _parse_date(val: Optional[str]) -> Optional[str]:
    """Valida e retorna data ISO 8601 ou None."""
    if not val:
        return None
    try:
        from datetime import date as _date
        _date.fromisoformat(val)
        return val
    except ValueError:
        return None

def _s(val: Optional[str]) -> Optional[str]:
    """Strip string; retorna None se vazio."""
    v = (val or "").strip()
    return v or None


# ──────────────── ABORDAGENS ─────────────────────────────────────────────────
# ===========================
# ROTA CATCHALL
# ===========================
