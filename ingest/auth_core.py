import logging
import os
import re
from datetime import datetime, timedelta, timezone

from fastapi.responses import JSONResponse
from jose import JWTError, ExpiredSignatureError, jwt as _jwt
from passlib.context import CryptContext
from starlette.middleware.base import BaseHTTPMiddleware

from rbac import normalize_role

logger = logging.getLogger(__name__)

_INSECURE_DEFAULT_SECRETS = {
    "JWT_SECRET": {"bpfron-change-me-in-production"},
    "ADMIN_PASSWORD": {"admin123"},
}


def _required_env(name: str, *, min_len: int = 1) -> str:
    value = str(os.getenv(name, "")).strip()
    if not value:
        raise RuntimeError(
            f"Variável de ambiente obrigatória ausente: {name}. "
            "Configure-a no .env antes de iniciar o serviço."
        )
    if value in _INSECURE_DEFAULT_SECRETS.get(name, set()):
        raise RuntimeError(
            f"Variável de ambiente insegura: {name} ainda está com valor padrão conhecido. "
            "Defina um segredo forte no .env antes de iniciar o serviço."
        )
    if len(value) < min_len:
        raise RuntimeError(
            f"Variável de ambiente inválida: {name} precisa ter pelo menos {min_len} caracteres."
        )
    return value


JWT_SECRET = _required_env("JWT_SECRET", min_len=32)
JWT_ALG = "HS256"
JWT_EXPIRE = int(os.getenv("JWT_EXPIRE_HOURS", "8"))
JWT_REFRESH_EXPIRE = int(os.getenv("JWT_REFRESH_EXPIRE_DAYS", "30"))
ADMIN_BOOTSTRAP_USER = str(os.getenv("ADMIN_USER", "admin")).strip() or "admin"
ADMIN_BOOTSTRAP_PASSWORD = _required_env("ADMIN_PASSWORD", min_len=12)

_pwd_ctx = CryptContext(schemes=["bcrypt"], deprecated="auto")


def hash_password(plain: str) -> str:
    return _pwd_ctx.hash(plain)


def verify_password(plain: str, hashed: str) -> bool:
    return _pwd_ctx.verify(plain, hashed)


def make_access_token(sub: str, role: str, full_name: str) -> str:
    exp = datetime.now(timezone.utc) + timedelta(hours=JWT_EXPIRE)
    safe_role = normalize_role(role)
    return _jwt.encode(
        {"sub": sub, "role": safe_role, "name": full_name, "exp": exp},
        JWT_SECRET,
        algorithm=JWT_ALG,
    )


def make_refresh_token(sub: str) -> str:
    exp = datetime.now(timezone.utc) + timedelta(days=JWT_REFRESH_EXPIRE)
    return _jwt.encode(
        {"sub": sub, "type": "refresh", "exp": exp},
        JWT_SECRET,
        algorithm=JWT_ALG,
    )


def decode_token(token: str) -> dict:
    return _jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALG])


def safe_sub(token_str: str) -> str:
    try:
        payload = _jwt.decode(
            token_str,
            JWT_SECRET,
            algorithms=[JWT_ALG],
            options={"verify_exp": False},
        )
        return payload.get("sub", "?")
    except Exception:
        return "?"


_PUBLIC_PREFIXES = (
    "/api/health",
    "/static",
    "/uploads",
    "/abordados",
    "/login",
    "/api/webhook",
    "/api/simple-webhook",
    "/webhook",
    "/api/ingest",
    "/api/catchall",
    "/catchall",
)
_PUBLIC_EXACT = {
    "/",
    "/dashboard",
    "/favicon.ico",
    "/api/auth/login",
    "/api/auth/refresh",
    "/docs",
    "/redoc",
    "/openapi.json",
}
_PUBLIC_RE = re.compile(r"^/api/events/\d+/(image|thumbnail)(\?.*)?$")


class AuthMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        path = request.url.path
        if (
            path in _PUBLIC_EXACT
            or any(path.startswith(p) for p in _PUBLIC_PREFIXES)
            or _PUBLIC_RE.match(path)
        ):
            return await call_next(request)

        auth = request.headers.get("Authorization", "")
        if not auth.startswith("Bearer "):
            logger.warning("[AUTH] Sem Bearer token em %s", path)
            return JSONResponse({"detail": "Não autenticado"}, status_code=401)

        token_str = auth.split(" ", 1)[1]
        try:
            payload = decode_token(token_str)
            payload["role"] = normalize_role(payload.get("role"))
            request.state.user = payload
        except ExpiredSignatureError:
            logger.warning("[AUTH] Token expirado em %s (sub=%s)", path, safe_sub(token_str))
            return JSONResponse(
                {"detail": "Sessão expirada. Faça login novamente."},
                status_code=401,
            )
        except JWTError as exc:
            logger.warning("[AUTH] Token inválido em %s: %s", path, exc)
            return JSONResponse({"detail": "Token inválido ou expirado"}, status_code=401)

        return await call_next(request)
