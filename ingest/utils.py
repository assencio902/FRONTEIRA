from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from jose import jwt as _jwt
from passlib.context import CryptContext
import os
import psycopg2
import psycopg2.pool

# ===========================
# CONFIG
# ===========================
JWT_SECRET  = os.getenv("JWT_SECRET", "bpfron-change-me-in-production")
JWT_ALG     = "HS256"
JWT_EXPIRE  = int(os.getenv("JWT_EXPIRE_HOURS", "8"))  # horas

_pwd_ctx = CryptContext(schemes=["bcrypt"], deprecated="auto")

# ===========================
# FUNÇÕES UTILITÁRIAS
# ===========================
def _hash_pw(plain: str) -> str:
    return _pwd_ctx.hash(plain)

def _verify_pw(plain: str, hashed: str) -> bool:
    return _pwd_ctx.verify(plain, hashed)

def _make_token(sub: str, role: str, full_name: str) -> str:
    expire = datetime.now(timezone.utc) + timedelta(hours=JWT_EXPIRE)
    to_encode = {"sub": sub, "role": role, "name": full_name, "exp": expire}
    return _jwt.encode(to_encode, JWT_SECRET, algorithm=JWT_ALG)

# ===========================
# CONEXÃO COM O BANCO
# ===========================
_pool = None

def _get_pool():
    global _pool
    if _pool is None:
        _pool = psycopg2.pool.SimpleConnectionPool(
            1, 10,
            dbname=os.getenv("POSTGRES_DB", "bpfron"),
            user=os.getenv("POSTGRES_USER", "postgres"),
            password=os.getenv("POSTGRES_PASSWORD", "postgres"),
            host=os.getenv("POSTGRES_HOST", "localhost"),
            port=os.getenv("POSTGRES_PORT", "5432"),
        )
    return _pool

@contextmanager
def _conn():
    pool = _get_pool()
    conn = pool.getconn()
    try:
        yield conn
    finally:
        pool.putconn(conn)


# ===========================
# SANITIZAÇÃO PARA LOGS
# ===========================
import re
import ipaddress

def _sanitize_token(token: str | None) -> str:
    """Máscara token JWT deixando apenas os últimos 4 caracteres visíveis."""
    if not token or len(token) < 8:
        return "***MASKED***"
    return f"***{token[-4:]}"


def _sanitize_password(password: str | None) -> str:
    """Máscara senha completamente."""
    return "***MASKED***" if password else None


def _sanitize_ip(ip: str | None) -> str:
    """Máscara IPs privados, deixa públicos visíveis."""
    if not ip:
        return ip
    try:
        ip_obj = ipaddress.ip_address(ip)
        if ip_obj.is_private:
            return "***MASKED_PRIVATE_IP***"
        return ip
    except ValueError:
        return ip


def _sanitize_for_logging(obj: dict | list | str) -> dict | list | str:
    """Sanitiza objetos que podem conter dados sensíveis para logging."""
    if isinstance(obj, dict):
        sanitized = {}
        for key, value in obj.items():
            key_lower = key.lower()
            if any(sensitive in key_lower for sensitive in ['token', 'jwt', 'password', 'secret', 'credential', 'authorization']):
                sanitized[key] = _sanitize_token(str(value)) if 'token' in key_lower or 'jwt' in key_lower else _sanitize_password(str(value))
            elif any(ip_kw in key_lower for ip_kw in ['ip', 'host', 'address']):
                sanitized[key] = _sanitize_ip(value) if value else value
            elif isinstance(value, dict):
                sanitized[key] = _sanitize_for_logging(value)
            elif isinstance(value, list):
                sanitized[key] = _sanitize_for_logging(value)
            else:
                sanitized[key] = value
        return sanitized
    elif isinstance(obj, list):
        return [_sanitize_for_logging(item) if isinstance(item, (dict, list)) else item for item in obj]
    return obj


def _sanitize_auth_header(auth_header: str | None) -> str:
    """Máscara Authorization header deixando apenas o tipo."""
    if not auth_header:
        return auth_header
    parts = auth_header.split(" ", 1)
    if len(parts) == 2:
        return f"{parts[0]} ***MASKED***"
    return "***MASKED***"


# ===========================
# HEALTH CHECKS
# ===========================
from datetime import datetime as _datetime

# Rastreia o tempo de inicialização da aplicação
_app_start_time = None

def _set_app_start_time():
    """Define o timestamp de início da aplicação."""
    global _app_start_time
    if _app_start_time is None:
        _app_start_time = _datetime.utcnow()

def _get_uptime() -> dict:
    """Retorna informações de uptime da aplicação."""
    if _app_start_time is None:
        return {"uptime_seconds": 0, "uptime_readable": "0s"}
    
    elapsed = _datetime.utcnow() - _app_start_time
    total_seconds = int(elapsed.total_seconds())
    
    days = total_seconds // 86400
    hours = (total_seconds % 86400) // 3600
    minutes = (total_seconds % 3600) // 60
    seconds = total_seconds % 60
    
    readable = []
    if days > 0:
        readable.append(f"{days}d")
    if hours > 0:
        readable.append(f"{hours}h")
    if minutes > 0:
        readable.append(f"{minutes}m")
    if seconds > 0 or not readable:
        readable.append(f"{seconds}s")
    
    return {
        "uptime_seconds": total_seconds,
        "uptime_readable": " ".join(readable),
        "started_at": _app_start_time.isoformat() + "Z"
    }


def _check_postgresql() -> dict:
    """Verifica saúde da conexão com PostgreSQL."""
    try:
        pool = _get_pool()
        conn = pool.getconn()
        try:
            with conn.cursor() as cur:
                cur.execute("SELECT 1")
                cur.fetchone()
            return {
                "status": "healthy",
                "database": os.getenv("POSTGRES_DB", "monitor"),
                "host": os.getenv("POSTGRES_HOST", "localhost"),
                "port": os.getenv("POSTGRES_PORT", "5432"),
                "timestamp": _datetime.utcnow().isoformat() + "Z"
            }
        finally:
            pool.putconn(conn)
    except Exception as e:
        return {
            "status": "unhealthy",
            "error": str(e)[:100],
            "timestamp": _datetime.utcnow().isoformat() + "Z"
        }


def _check_redis() -> dict:
    """Verifica saúde da conexão com Redis."""
    try:
        redis_url = os.getenv("REDIS_URL", "redis://redis:6379/0")
        r = _redis_lib.from_url(redis_url, decode_responses=True)
        r.ping()
        
        # Tenta obter informações do Redis
        info = r.info()
        return {
            "status": "healthy",
            "redis_version": info.get("redis_version", "unknown"),
            "uptime_seconds": info.get("uptime_in_seconds", 0),
            "connected_clients": info.get("connected_clients", 0),
            "timestamp": _datetime.utcnow().isoformat() + "Z"
        }
    except Exception as e:
        return {
            "status": "unhealthy",
            "error": str(e)[:100],
            "timestamp": _datetime.utcnow().isoformat() + "Z"
        }


def _get_health_status() -> dict:
    """Retorna status geral de saúde do sistema."""
    pg_status = _check_postgresql()
    redis_status = _check_redis()
    uptime = _get_uptime()
    
    # Determina status geral
    overall_status = "healthy"
    if pg_status.get("status") != "healthy" or redis_status.get("status") != "healthy":
        overall_status = "degraded"
    
    return {
        "status": overall_status,
        "timestamp": _datetime.utcnow().isoformat() + "Z",
        "services": {
            "api": "healthy",
            "postgresql": pg_status,
            "redis": redis_status
        },
        **uptime
    }
