import logging
from typing import Any, Callable

from fastapi import APIRouter, HTTPException, Request
from jose import ExpiredSignatureError, JWTError

from auth_core import (
    JWT_EXPIRE,
    decode_token,
    hash_password,
    make_access_token,
    make_refresh_token,
    verify_password,
)
from rbac import normalize_role
from services.admin_activity_service import start_user_session

logger = logging.getLogger(__name__)


def build_auth_router(conn_factory: Callable[[], Any]) -> APIRouter:
    router = APIRouter(tags=["auth"])

    @router.post("/api/auth/login")
    async def auth_login(request: Request):
        data = await request.json()
        username = str(data.get("username") or "").strip().lower()
        password = str(data.get("password") or "")
        if not username or not password:
            raise HTTPException(status_code=400, detail="username e password são obrigatórios")

        with conn_factory() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT id, username, password_hash, full_name, role, ativa
                    FROM users
                    WHERE username=%s
                    LIMIT 1
                    """,
                    (username,),
                )
                row = cur.fetchone()

        if not row:
            raise HTTPException(status_code=401, detail="Usuário ou senha inválidos")

        _, uname, pw_hash, full_name, role, ativa = row
        role = normalize_role(role)
        if not ativa:
            raise HTTPException(status_code=403, detail="Usuário inativo")
        if not verify_password(password, pw_hash):
            raise HTTPException(status_code=401, detail="Usuário ou senha inválidos")

        token = make_access_token(uname, role, full_name or uname)
        refresh_token = make_refresh_token(uname)
        session_id = ""
        try:
            session_id = start_user_session(
                conn_factory,
                request=request,
                username=uname,
                full_name=full_name or uname,
                role=role,
            )
        except Exception:
            logger.exception("[AUTH] Falha ao registrar sessao de auditoria para %s", uname)
        return {
            "access_token": token,
            "refresh_token": refresh_token,
            "session_id": session_id,
            "token_type": "bearer",
            "expires_in": JWT_EXPIRE * 3600,
            "role": role,
            "full_name": full_name or uname,
            "username": uname,
        }

    @router.get("/api/auth/me")
    async def auth_me(request: Request):
        user = getattr(request.state, "user", None)
        if not user:
            raise HTTPException(status_code=401, detail="Não autenticado")
        return {
            "username": user.get("sub"),
            "role": normalize_role(user.get("role")),
            "full_name": user.get("name"),
        }

    @router.post("/api/auth/refresh")
    async def auth_refresh(request: Request):
        data = await request.json()
        refresh_tk = str(data.get("refresh_token") or "").strip()
        if not refresh_tk:
            raise HTTPException(status_code=400, detail="refresh_token obrigatório")

        try:
            payload = decode_token(refresh_tk)
            if payload.get("type") != "refresh":
                raise HTTPException(status_code=401, detail="Token inválido (tipo incorreto)")
            sub = payload.get("sub")
            if not sub:
                raise HTTPException(status_code=401, detail="Token inválido")
        except ExpiredSignatureError:
            raise HTTPException(status_code=401, detail="Refresh token expirado. Faça login novamente.")
        except JWTError:
            raise HTTPException(status_code=401, detail="Refresh token inválido")

        with conn_factory() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT username, full_name, role, ativa
                    FROM users
                    WHERE username=%s
                    LIMIT 1
                    """,
                    (sub,),
                )
                row = cur.fetchone()

        if not row:
            raise HTTPException(status_code=401, detail="Usuário não encontrado")

        uname, full_name, role, ativa = row
        if not ativa:
            raise HTTPException(status_code=403, detail="Usuário inativo")

        role = normalize_role(role)
        new_access = make_access_token(uname, role, full_name or uname)
        new_refresh = make_refresh_token(uname)
        logger.info("[AUTH] refresh bem-sucedido sub=%s", uname)
        return {
            "access_token": new_access,
            "refresh_token": new_refresh,
            "token_type": "bearer",
            "expires_in": JWT_EXPIRE * 3600,
        }

    @router.put("/api/auth/password")
    async def change_my_password(request: Request):
        user = getattr(request.state, "user", None)
        if not user:
            raise HTTPException(status_code=401, detail="Não autenticado")

        data = await request.json()
        current_pw = data.get("current_password", "")
        new_pw = data.get("new_password", "")
        if not current_pw or not new_pw:
            raise HTTPException(
                status_code=400,
                detail="Campos obrigatórios: current_password e new_password",
            )
        if len(new_pw) < 6:
            raise HTTPException(status_code=400, detail="Nova senha deve ter pelo menos 6 caracteres")

        username = user.get("sub")
        with conn_factory() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT id, password_hash FROM users WHERE username=%s", (username,))
                row = cur.fetchone()
                if not row:
                    raise HTTPException(status_code=404, detail="Usuário não encontrado")
                if not verify_password(current_pw, row[1]):
                    raise HTTPException(status_code=400, detail="Senha atual incorreta")
                cur.execute(
                    "UPDATE users SET password_hash=%s, updated_at=NOW() WHERE id=%s",
                    (hash_password(new_pw), row[0]),
                )

        return {"ok": True}

    return router
