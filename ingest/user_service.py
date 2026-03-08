from typing import Optional
from fastapi import HTTPException
from utils import _conn, _hash_pw, _verify_pw, _make_token
from rbac import normalize_role, normalize_role_input, VALID_ROLES

class UserService:
    @staticmethod
    def authenticate(username: str, password: str):
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
        token = _make_token(uname, role, full_name or uname)
        return {"access_token": token, "token_type": "bearer", "role": role, "full_name": full_name or uname, "username": uname}

    @staticmethod
    def change_password(username: str, current_pw: str, new_pw: str):
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

    @staticmethod
    def create_user(username: str, password: str, full_name: str, role: str, ativa: bool):
        role_raw = role
        role = normalize_role_input(role)
        if role not in VALID_ROLES:
            raise HTTPException(status_code=400, detail=f"role inválido: '{role_raw}'. Use apenas: admin, operador, visualizacao")
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

    @staticmethod
    def update_user(uid: int, full_name: Optional[str], role: Optional[str], ativa: Optional[bool], password: Optional[str]):
        sets, vals = [], []
        if full_name is not None:
            sets.append("full_name=%s"); vals.append(full_name.strip())
        if role is not None:
            role_raw = role
            role = normalize_role_input(role)
            if role not in VALID_ROLES:
                raise HTTPException(status_code=400, detail=f"role inválido: '{role_raw}'. Use apenas: admin, operador, visualizacao")
            sets.append("role=%s"); vals.append(role)
        if ativa is not None:
            sets.append("ativa=%s"); vals.append(ativa)
        if password:
            sets.append("password_hash=%s"); vals.append(_hash_pw(password))
        if not sets:
            raise HTTPException(status_code=400, detail="Nenhum campo para atualizar")
        sets.append("updated_at=NOW()")
        vals.append(uid)
        with _conn() as conn:
            with conn.cursor() as cur:
                cur.execute(f"UPDATE users SET {', '.join(sets)} WHERE id=%s", tuple(vals))
                if cur.rowcount == 0:
                    raise HTTPException(status_code=404, detail="Usuário não encontrado")
        return {"ok": True}
