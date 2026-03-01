# Camada de acesso a dados para usuários
from utils import _conn
from fastapi import HTTPException

class UserRepository:
    @staticmethod
    def list_users():
        with _conn() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT id, username, full_name, role, ativa, created_at FROM users ORDER BY id")
                rows = cur.fetchall()
        return {"items": [{"id": r[0], "username": r[1], "full_name": r[2], "role": r[3], "ativa": r[4], "created_at": r[5].isoformat() if r[5] else None} for r in rows]}

    @staticmethod
    def create_user(body):
        from utils import _hash_pw
        username  = body.username.strip().lower()
        password  = body.password.strip()
        full_name = body.full_name.strip() if body.full_name else ""
        role      = body.role
        ativa     = body.ativa
        with _conn() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT id FROM users WHERE username=%s LIMIT 1", (username,))
                if cur.fetchone():
                    raise HTTPException(status_code=400, detail="Usuário já existe")
                cur.execute(
                    "INSERT INTO users (username, password_hash, full_name, role, ativa) VALUES (%s, %s, %s, %s, %s) RETURNING id",
                    (username, _hash_pw(password), full_name, role, ativa)
                )
                uid = cur.fetchone()[0]
        return {"id": uid, "username": username, "full_name": full_name, "role": role, "ativa": ativa}

    @staticmethod
    def update_user(uid: int, body):
        with _conn() as conn:
            with conn.cursor() as cur:
                sets = []
                vals = []
                if body.full_name is not None:
                    sets.append("full_name=%s")
                    vals.append(body.full_name)
                if body.role is not None:
                    sets.append("role=%s")
                    vals.append(body.role)
                if body.ativa is not None:
                    sets.append("ativa=%s")
                    vals.append(body.ativa)
                if body.password is not None:
                    from utils import _hash_pw
                    sets.append("password_hash=%s")
                    vals.append(_hash_pw(body.password))
                if not sets:
                    raise HTTPException(status_code=400, detail="Nada para atualizar")
                vals.append(uid)
                cur.execute(f"UPDATE users SET {', '.join(sets)} WHERE id=%s", tuple(vals))
        return {"id": uid}

    @staticmethod
    def delete_user(uid: int):
        with _conn() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT username FROM users WHERE id=%s", (uid,))
                row = cur.fetchone()
                if not row:
                    raise HTTPException(status_code=404, detail="Usuário não encontrado")
                if row[0] == "admin":
                    raise HTTPException(status_code=400, detail="Não é possível excluir o admin principal")
                cur.execute("DELETE FROM users WHERE id=%s", (uid,))
        return {"ok": True}
