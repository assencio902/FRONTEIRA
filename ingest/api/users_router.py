from typing import Any, Callable

from fastapi import APIRouter, HTTPException, Request

from auth_core import hash_password
from rbac import VALID_ROLES, assert_admin, normalize_role_input


def build_users_router(conn_factory: Callable[[], Any]) -> APIRouter:
    router = APIRouter(tags=["users"])

    @router.get("/api/users")
    async def list_users(request: Request):
        assert_admin(request, "Acesso restrito a administradores")
        with conn_factory() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT id, username, full_name, role, ativa, created_at
                    FROM users
                    ORDER BY id
                    """
                )
                rows = cur.fetchall()

        return {
            "items": [
                {
                    "id": r[0],
                    "username": r[1],
                    "full_name": r[2],
                    "role": r[3],
                    "ativa": r[4],
                    "created_at": r[5].isoformat() if r[5] else None,
                }
                for r in rows
            ]
        }

    @router.post("/api/users", status_code=201)
    async def create_user(request: Request):
        assert_admin(request, "Acesso restrito a administradores")
        data = await request.json()
        username = str(data.get("username") or "").strip().lower()
        password = str(data.get("password") or "").strip()
        full_name = str(data.get("full_name") or "").strip()
        role_raw = data.get("role")
        role = normalize_role_input(role_raw)
        ativa = bool(data.get("ativa", True))

        if not username:
            raise HTTPException(status_code=400, detail="username obrigatório")
        if not password:
            raise HTTPException(status_code=400, detail="password obrigatório")
        if role not in VALID_ROLES:
            raise HTTPException(
                status_code=400,
                detail=f"role inválido: '{role_raw}'. Use apenas: admin, operador, visualizador",
            )

        try:
            with conn_factory() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        INSERT INTO users (username, password_hash, full_name, role, ativa)
                        VALUES (%s, %s, %s, %s, %s)
                        RETURNING id
                        """,
                        (username, hash_password(password), full_name, role, ativa),
                    )
                    new_id = cur.fetchone()[0]
        except Exception as exc:
            if "unique" in str(exc).lower():
                raise HTTPException(status_code=409, detail="Username já existe")
            raise

        return {
            "id": new_id,
            "username": username,
            "full_name": full_name,
            "role": role,
            "ativa": ativa,
        }

    @router.put("/api/users/{uid}")
    async def update_user(uid: int, request: Request):
        assert_admin(request, "Apenas administradores podem alterar usuários")
        data = await request.json()
        sets, vals = [], []

        if "full_name" in data:
            sets.append("full_name=%s")
            vals.append(str(data["full_name"]).strip())
        if "role" in data:
            role_raw = data["role"]
            role = normalize_role_input(role_raw)
            if role not in VALID_ROLES:
                raise HTTPException(
                    status_code=400,
                    detail=f"role inválido: '{role_raw}'. Use apenas: admin, operador, visualizacao",
                )
            sets.append("role=%s")
            vals.append(role)
        if "ativa" in data:
            sets.append("ativa=%s")
            vals.append(bool(data["ativa"]))
        if "password" in data and data["password"]:
            sets.append("password_hash=%s")
            vals.append(hash_password(str(data["password"])))

        if not sets:
            raise HTTPException(status_code=400, detail="Nenhum campo para atualizar")

        sets.append("updated_at=NOW()")
        vals.append(uid)

        with conn_factory() as conn:
            with conn.cursor() as cur:
                cur.execute(f"UPDATE users SET {', '.join(sets)} WHERE id=%s", tuple(vals))
                if cur.rowcount == 0:
                    raise HTTPException(status_code=404, detail="Usuário não encontrado")

        return {"ok": True}

    @router.delete("/api/users/{uid}", status_code=204)
    async def delete_user(uid: int, request: Request):
        assert_admin(request, "Acesso restrito a administradores")
        with conn_factory() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT username FROM users WHERE id=%s", (uid,))
                row = cur.fetchone()
                if not row:
                    raise HTTPException(status_code=404, detail="Usuário não encontrado")
                if row[0] == "admin":
                    raise HTTPException(status_code=400, detail="Não é possível excluir o admin principal")
                cur.execute("DELETE FROM users WHERE id=%s", (uid,))

    return router
