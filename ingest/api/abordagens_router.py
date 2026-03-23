import json
import os
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Optional

from fastapi import APIRouter, HTTPException, Request


PAPEIS_VALIDOS = {"abordado", "motorista", "proprietario", "passageiro", "garupa", "outro"}
_ABORDADO_IMAGES_DIR = Path(os.getenv("ABORDADO_IMAGES_DIR", "/app/abordados"))
_ALLOWED_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp"}


def _guess_image_extension(filename: str, content_type: Optional[str]) -> str:
    suffix = Path(filename or "").suffix.lower()
    if suffix in _ALLOWED_EXTENSIONS:
        return ".jpg" if suffix == ".jpeg" else suffix
    mapping = {
        "image/jpeg": ".jpg",
        "image/png": ".png",
        "image/webp": ".webp",
        "image/gif": ".gif",
        "image/bmp": ".bmp",
    }
    return mapping.get((content_type or "").lower(), ".jpg")


async def _save_abordado_image(upload, base_dir: Path) -> Optional[str]:
    if not upload or not getattr(upload, "filename", None):
        return None
    content_type = (getattr(upload, "content_type", "") or "").lower()
    if content_type and not content_type.startswith("image/"):
        raise HTTPException(status_code=400, detail="A imagem do abordado deve ser um arquivo de imagem valido")
    data = await upload.read()
    if not data:
        return None
    day_dir = datetime.utcnow().strftime("%Y-%m-%d")
    rel_dir = Path(day_dir)
    abs_dir = base_dir / rel_dir
    abs_dir.mkdir(parents=True, exist_ok=True)
    ext = _guess_image_extension(upload.filename, content_type)
    filename = f"abordado-{datetime.utcnow().strftime('%H%M%S')}-{os.urandom(6).hex()}{ext}"
    abs_path = abs_dir / filename
    abs_path.write_bytes(data)
    return "/abordados/" + str((rel_dir / filename).as_posix()).lstrip("/")


async def _save_vehicle_image(upload, base_dir: Path) -> Optional[str]:
    if not upload or not getattr(upload, "filename", None):
        return None
    content_type = (getattr(upload, "content_type", "") or "").lower()
    if content_type and not content_type.startswith("image/"):
        raise HTTPException(status_code=400, detail="A imagem do veiculo deve ser um arquivo de imagem valido")
    data = await upload.read()
    if not data:
        return None
    day_dir = datetime.utcnow().strftime("%Y-%m-%d")
    rel_dir = Path("veiculos") / day_dir
    abs_dir = base_dir / rel_dir
    abs_dir.mkdir(parents=True, exist_ok=True)
    ext = _guess_image_extension(upload.filename, content_type)
    filename = f"veiculo-{datetime.utcnow().strftime('%H%M%S')}-{os.urandom(6).hex()}{ext}"
    abs_path = abs_dir / filename
    abs_path.write_bytes(data)
    return "/abordados/" + str((rel_dir / filename).as_posix()).lstrip("/")


def build_abordagens_router(
    conn_factory: Callable[[], Any],
    require_auth_fn: Callable[[Request], Any],
    assert_admin_fn: Callable[[Request, str], Any],
    assert_admin_or_operator_fn: Callable[[Request, str], Any],
    normalize_str_fn: Callable[[Optional[str]], Optional[str]],
    clean_cpf_fn: Callable[[Optional[str]], Optional[str]],
    parse_date_fn: Callable[[Optional[str]], Optional[str]],
    utcnow_fn: Callable[[], datetime],
    normalize_plate_fn: Callable[[Optional[str]], str],
    sync_alvo_to_lista_fn: Callable[[Any, str, str], Any],
    get_abordados_dir_fn: Callable[[], Path] | None = None,
) -> APIRouter:
    router = APIRouter(tags=["abordagens"])
    resolve_abordados_dir = get_abordados_dir_fn or (lambda: _ABORDADO_IMAGES_DIR)

    @router.get("/api/abordagens")
    def listar_abordagens(
        request: Request,
        q: Optional[str] = None,
        limit: int = 50,
        offset: int = 0,
        dt_from: Optional[str] = None,
        dt_to: Optional[str] = None,
    ):
        """
        Lista abordagens com filtros opcionais.
        q      -> busca em local, equipe, tipo_motivo
        dt_from / dt_to -> filtro de periodo (AAAA-MM-DD)
        Retorna abordagem + veiculo + lista de pessoas vinculadas.
        """
        require_auth_fn(request)
        limit = max(1, min(200, int(limit)))
        offset = max(0, int(offset))
        clauses, params = [], []
        if q and q.strip():
            term = f"%{q.strip()}%"
            clauses.append("(a.local ILIKE %s OR a.equipe ILIKE %s OR a.tipo_motivo ILIKE %s)")
            params += [term, term, term]
        if dt_from:
            clauses.append("a.data_hora >= %s")
            params.append(dt_from)
        if dt_to:
            clauses.append("a.data_hora <= %s")
            params.append(dt_to + " 23:59:59")
        where = ("WHERE " + " AND ".join(clauses)) if clauses else ""

        with conn_factory() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    f"""
                    SELECT a.id, a.data_hora, a.local, a.equipe, a.tipo_motivo,
                           a.observacoes, a.veiculo_id, a.data_cadastro,
                           v.placa, v.marca, v.modelo, v.cor, v.ano, v.tipo
                    FROM abordagens a
                    LEFT JOIN veiculos_abordagem v ON v.id = a.veiculo_id
                    {where}
                    ORDER BY a.data_hora DESC
                    LIMIT %s OFFSET %s
                    """,
                    (*params, limit, offset),
                )
                rows = cur.fetchall()
                cur.execute(f"SELECT COUNT(*) FROM abordagens a {where}", params)
                total = cur.fetchone()[0]

        result = []
        for row in rows:
            result.append(
                {
                    "id": row[0],
                    "data_hora": row[1].isoformat() if row[1] else None,
                    "local": row[2],
                    "equipe": row[3],
                    "tipo_motivo": row[4],
                    "observacoes": row[5],
                    "veiculo_id": row[6],
                    "data_cadastro": row[7].isoformat() if row[7] else None,
                    "veiculo": {
                        "placa": row[8],
                        "marca": row[9],
                        "modelo": row[10],
                        "cor": row[11],
                        "ano": row[12],
                        "tipo": row[13],
                    }
                    if row[8]
                    else None,
                    "pessoas": [],
                }
            )

        if result:
            ids = [abordagem["id"] for abordagem in result]
            with conn_factory() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        SELECT ap.abordagem_id, ap.papel, ap.observacao_pessoal,
                               p.id, p.nome, p.apelido, p.cpf, p.rg
                        FROM abordagem_pessoas ap
                        JOIN pessoas p ON p.id = ap.pessoa_id
                        WHERE ap.abordagem_id = ANY(%s)
                        ORDER BY ap.abordagem_id, p.nome
                        """,
                        (ids,),
                    )
                    for pessoa in cur.fetchall():
                        for abordagem in result:
                            if abordagem["id"] == pessoa[0]:
                                abordagem["pessoas"].append(
                                    {
                                        "papel": pessoa[1],
                                        "observacao_pessoal": pessoa[2],
                                        "id": pessoa[3],
                                        "nome": pessoa[4],
                                        "apelido": pessoa[5],
                                        "cpf": pessoa[6],
                                        "rg": pessoa[7],
                                    }
                                )
                                break

        return {"total": total, "abordagens": result}

    @router.get("/api/abordagens/{abordagem_id}")
    def buscar_abordagem_por_id(abordagem_id: int, request: Request):
        """Retorna uma abordagem completa: dados + veículo + todas as pessoas vinculadas."""
        require_auth_fn(request)
        with conn_factory() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT a.id, a.data_hora, a.local, a.equipe, a.tipo_motivo,
                           a.observacoes, a.veiculo_id, a.data_cadastro,
                           v.placa, v.marca, v.modelo, v.cor, v.ano, v.tipo, v.foto_path, v.observacoes
                    FROM abordagens a
                    LEFT JOIN veiculos_abordagem v ON v.id = a.veiculo_id
                    WHERE a.id = %s LIMIT 1
                    """,
                    (abordagem_id,),
                )
                row = cur.fetchone()
                if not row:
                    raise HTTPException(status_code=404, detail="Abordagem não encontrada")
                abordagem = {
                    "id": row[0],
                    "data_hora": row[1].isoformat() if row[1] else None,
                    "local": row[2],
                    "equipe": row[3],
                    "tipo_motivo": row[4],
                    "observacoes": row[5],
                    "veiculo_id": row[6],
                    "data_cadastro": row[7].isoformat() if row[7] else None,
                    "veiculo": {
                        "placa": row[8],
                        "marca": row[9],
                        "modelo": row[10],
                        "cor": row[11],
                        "ano": row[12],
                        "tipo": row[13],
                        "foto_path": row[14],
                        "observacoes": row[15],
                    }
                    if row[8]
                    else None,
                    "pessoas": [],
                }
                cur.execute(
                    """
                    SELECT ap.papel, ap.observacao_pessoal,
                           p.id, p.nome, p.apelido, p.cpf, p.rg,
                           p.foto_path, p.data_nascimento, p.naturalidade, p.estado_naturalidade,
                           p.nome_mae, p.nome_pai, p.contato, p.profissao, p.endereco
                    FROM abordagem_pessoas ap
                    JOIN pessoas p ON p.id = ap.pessoa_id
                    WHERE ap.abordagem_id = %s
                    ORDER BY p.nome
                    """,
                    (abordagem_id,),
                )
                for pessoa in cur.fetchall():
                    abordagem["pessoas"].append(
                        {
                            "papel": pessoa[0],
                            "observacao_pessoal": pessoa[1],
                            "id": pessoa[2],
                            "nome": pessoa[3],
                            "apelido": pessoa[4],
                            "cpf": pessoa[5],
                            "rg": pessoa[6],
                            "foto_path": pessoa[7],
                            "data_nascimento": pessoa[8].isoformat() if pessoa[8] else None,
                            "naturalidade": pessoa[9],
                            "estado_naturalidade": pessoa[10],
                            "nome_mae": pessoa[11],
                            "nome_pai": pessoa[12],
                            "contato": pessoa[13],
                            "profissao": pessoa[14],
                            "endereco": pessoa[15],
                        }
                    )
        return abordagem

    @router.post("/api/abordagens", status_code=201)
    async def criar_abordagem(request: Request):
        """
        Cria uma abordagem completa em uma única operação.
        """
        assert_admin_or_operator_fn(
            request,
            "Apenas administradores e operadores podem registrar abordagens",
        )
        content_type = (request.headers.get("content-type") or "").lower()
        abordado_foto_path = None
        veiculo_foto_path = None
        if "multipart/form-data" in content_type:
            form = await request.form()
            raw_payload = form.get("payload")
            if raw_payload is None:
                raise HTTPException(status_code=400, detail="payload nao informado")
            try:
                data = json.loads(str(raw_payload))
            except json.JSONDecodeError as exc:
                raise HTTPException(status_code=400, detail="payload invalido") from exc
            base_dir = resolve_abordados_dir()
            abordado_foto_path = await _save_abordado_image(form.get("abordado_imagem"), base_dir)
            veiculo_foto_path = await _save_vehicle_image(form.get("veiculo_imagem"), base_dir)
            for pessoa_data in (data.get("pessoas") or []):
                upload_key = str(pessoa_data.get("foto_upload_key") or "").strip()
                if not upload_key:
                    continue
                foto_path = await _save_abordado_image(form.get(upload_key), base_dir)
                if foto_path:
                    pessoa_data["foto_path"] = foto_path
        else:
            data = await request.json()

        veiculo_id = None
        veiculo_data = data.get("veiculo")
        if veiculo_data and normalize_str_fn(veiculo_data.get("placa")):
            placa = normalize_str_fn(veiculo_data["placa"]).upper()
            with conn_factory() as conn:
                with conn.cursor() as cur:
                    cur.execute("SELECT id FROM veiculos_abordagem WHERE placa=%s LIMIT 1", (placa,))
                    existing = cur.fetchone()
                    if existing:
                        veiculo_id = existing[0]
                        ano_raw = veiculo_data.get("ano")
                        ano = int(ano_raw) if ano_raw and str(ano_raw).isdigit() else None
                        cur.execute(
                            """
                            UPDATE veiculos_abordagem
                            SET marca=COALESCE(%s, marca), modelo=COALESCE(%s, modelo),
                                cor=COALESCE(%s, cor), ano=COALESCE(%s, ano),
                                tipo=COALESCE(%s, tipo), foto_path=COALESCE(%s, foto_path),
                                observacoes=COALESCE(%s, observacoes)
                            WHERE id=%s
                            """,
                            (
                                normalize_str_fn(veiculo_data.get("marca")),
                                normalize_str_fn(veiculo_data.get("modelo")),
                                normalize_str_fn(veiculo_data.get("cor")),
                                ano,
                                normalize_str_fn(veiculo_data.get("tipo")),
                                veiculo_foto_path,
                                normalize_str_fn(veiculo_data.get("observacoes")),
                                veiculo_id,
                            ),
                        )
                    else:
                        ano_raw = veiculo_data.get("ano")
                        ano = int(ano_raw) if ano_raw and str(ano_raw).isdigit() else None
                        cur.execute(
                            """
                            INSERT INTO veiculos_abordagem
                                   (placa, marca, modelo, cor, ano, tipo, foto_path, observacoes)
                            VALUES (%s,%s,%s,%s,%s,%s,%s,%s)
                            RETURNING id
                            """,
                            (
                                placa,
                                normalize_str_fn(veiculo_data.get("marca")),
                                normalize_str_fn(veiculo_data.get("modelo")),
                                normalize_str_fn(veiculo_data.get("cor")),
                                ano,
                                normalize_str_fn(veiculo_data.get("tipo")),
                                veiculo_foto_path,
                                normalize_str_fn(veiculo_data.get("observacoes")),
                            ),
                        )
                        veiculo_id = cur.fetchone()[0]

        if veiculo_data and veiculo_data.get("vincular_como_alvo") and veiculo_id:
            placa_norm = normalize_plate_fn(normalize_str_fn(veiculo_data.get("placa")) or "")
            if placa_norm:
                obs_local = normalize_str_fn(data.get("local")) or ""
                descricao = "Vinculado via abordagem" + (f" — {obs_local}" if obs_local else "")
                with conn_factory() as conn:
                    with conn.cursor() as cur:
                        cur.execute(
                            """
                            INSERT INTO alvos (plate, descricao)
                            VALUES (%s, %s)
                            ON CONFLICT (plate) DO UPDATE SET descricao = EXCLUDED.descricao
                            """,
                            (placa_norm, descricao),
                        )
                        sync_alvo_to_lista_fn(cur, placa_norm, descricao)

        data_hora_raw = normalize_str_fn(data.get("data_hora"))
        data_hora = None
        if data_hora_raw:
            try:
                data_hora = datetime.fromisoformat(data_hora_raw.replace("Z", "+00:00"))
            except ValueError:
                data_hora = None

        with conn_factory() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO abordagens (data_hora, local, equipe, tipo_motivo, observacoes, veiculo_id)
                    VALUES (%s, %s, %s, %s, %s, %s)
                    RETURNING id
                    """,
                    (
                        data_hora or utcnow_fn(),
                        normalize_str_fn(data.get("local")),
                        normalize_str_fn(data.get("equipe")),
                        normalize_str_fn(data.get("tipo_motivo")),
                        normalize_str_fn(data.get("observacoes")),
                        veiculo_id,
                    ),
                )
                abordagem_id = cur.fetchone()[0]

        for pessoa_data in (data.get("pessoas") or []):
            papel = (pessoa_data.get("papel") or "outro").strip().lower()
            if papel not in PAPEIS_VALIDOS:
                papel = "outro"
            obs_pessoal = normalize_str_fn(pessoa_data.get("observacao_pessoal"))
            pessoa_foto_path = normalize_str_fn(pessoa_data.get("foto_path"))

            pessoa_id = pessoa_data.get("pessoa_id")
            if pessoa_id:
                pessoa_id = int(pessoa_id)
                atualizacoes: dict = {}
                if pessoa_foto_path:
                    atualizacoes["foto_path"] = pessoa_foto_path
                cpf_atualizado = clean_cpf_fn(pessoa_data.get("cpf"))
                if cpf_atualizado:
                    atualizacoes["cpf"] = cpf_atualizado
                for campo in (
                    "rg",
                    "contato",
                    "profissao",
                    "endereco",
                    "nome_pai",
                    "nome_mae",
                    "naturalidade",
                    "estado_naturalidade",
                ):
                    valor = normalize_str_fn(pessoa_data.get(campo))
                    if valor:
                        atualizacoes[campo] = valor
                data_nascimento_atualizada = parse_date_fn(pessoa_data.get("data_nascimento"))
                if data_nascimento_atualizada:
                    atualizacoes["data_nascimento"] = data_nascimento_atualizada
                if atualizacoes:
                    cols = ", ".join(f"{campo}=%s" for campo in atualizacoes)
                    with conn_factory() as conn:
                        with conn.cursor() as cur:
                            cur.execute(
                                f"UPDATE pessoas SET {cols} WHERE id=%s",
                                list(atualizacoes.values()) + [pessoa_id],
                            )
            else:
                cpf_raw = clean_cpf_fn(pessoa_data.get("cpf"))
                found_id = None
                if cpf_raw:
                    with conn_factory() as conn:
                        with conn.cursor() as cur:
                            cur.execute("SELECT id FROM pessoas WHERE cpf=%s LIMIT 1", (cpf_raw,))
                            row = cur.fetchone()
                            if row:
                                found_id = row[0]
                if not found_id:
                    rg = normalize_str_fn(pessoa_data.get("rg"))
                    if rg:
                        with conn_factory() as conn:
                            with conn.cursor() as cur:
                                cur.execute("SELECT id FROM pessoas WHERE rg=%s LIMIT 1", (rg,))
                                row = cur.fetchone()
                                if row:
                                    found_id = row[0]
                if found_id:
                    pessoa_id = found_id
                    if pessoa_foto_path:
                        with conn_factory() as conn:
                            with conn.cursor() as cur:
                                cur.execute(
                                    "UPDATE pessoas SET foto_path=%s WHERE id=%s",
                                    (pessoa_foto_path, pessoa_id),
                                )
                else:
                    nome = normalize_str_fn(pessoa_data.get("nome"))
                    if not nome:
                        continue
                    data_nascimento = parse_date_fn(pessoa_data.get("data_nascimento"))
                    with conn_factory() as conn:
                        with conn.cursor() as cur:
                            cur.execute(
                                """
                                INSERT INTO pessoas
                                    (nome, apelido, contato, profissao, cpf, rg,
                                     data_nascimento, naturalidade, estado_naturalidade,
                                     nome_mae, nome_pai, endereco, foto_path)
                                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                                RETURNING id
                                """,
                                (
                                    nome,
                                    normalize_str_fn(pessoa_data.get("apelido")),
                                    normalize_str_fn(pessoa_data.get("contato")),
                                    normalize_str_fn(pessoa_data.get("profissao")),
                                    cpf_raw,
                                    normalize_str_fn(pessoa_data.get("rg")),
                                    data_nascimento,
                                    normalize_str_fn(pessoa_data.get("naturalidade")),
                                    normalize_str_fn(pessoa_data.get("estado_naturalidade")),
                                    normalize_str_fn(pessoa_data.get("nome_mae")),
                                    normalize_str_fn(pessoa_data.get("nome_pai")),
                                    normalize_str_fn(pessoa_data.get("endereco")),
                                    pessoa_foto_path,
                                ),
                            )
                            pessoa_id = cur.fetchone()[0]

            with conn_factory() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        INSERT INTO abordagem_pessoas
                            (abordagem_id, pessoa_id, papel, observacao_pessoal)
                        VALUES (%s, %s, %s, %s)
                        ON CONFLICT (abordagem_id, pessoa_id) DO UPDATE
                            SET papel=EXCLUDED.papel,
                                observacao_pessoal=EXCLUDED.observacao_pessoal
                        """,
                        (abordagem_id, pessoa_id, papel, obs_pessoal),
                    )

        return {"ok": True, "id": abordagem_id}

    @router.put("/api/abordagens/{abordagem_id}")
    async def atualizar_abordagem(abordagem_id: int, request: Request):
        """
        Atualiza dados gerais de uma abordagem (não altera pessoas/veículo aqui).
        Payload: data_hora, local, equipe, tipo_motivo, observacoes, veiculo_id
        """
        assert_admin_or_operator_fn(
            request,
            "Apenas administradores e operadores podem editar abordagens",
        )
        data = await request.json()
        data_hora_raw = normalize_str_fn(data.get("data_hora"))
        data_hora = None
        if data_hora_raw:
            try:
                data_hora = datetime.fromisoformat(data_hora_raw.replace("Z", "+00:00"))
            except ValueError:
                pass
        with conn_factory() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE abordagens
                    SET data_hora=COALESCE(%s, data_hora),
                        local=%s, equipe=%s, tipo_motivo=%s, observacoes=%s,
                        veiculo_id=COALESCE(%s, veiculo_id)
                    WHERE id=%s
                    """,
                    (
                        data_hora,
                        normalize_str_fn(data.get("local")),
                        normalize_str_fn(data.get("equipe")),
                        normalize_str_fn(data.get("tipo_motivo")),
                        normalize_str_fn(data.get("observacoes")),
                        data.get("veiculo_id"),
                        abordagem_id,
                    ),
                )
                if cur.rowcount == 0:
                    raise HTTPException(status_code=404, detail="Abordagem não encontrada")
        return {"ok": True}

    @router.post("/api/abordagens/{abordagem_id}/pessoas", status_code=201)
    async def vincular_pessoa_abordagem(abordagem_id: int, request: Request):
        """
        Vincula ou atualiza uma pessoa em uma abordagem existente.
        Payload: { "pessoa_id": 5, "papel": "passageiro", "observacao_pessoal": "" }
        """
        assert_admin_or_operator_fn(
            request,
            "Apenas administradores e operadores podem vincular pessoas a abordagens",
        )
        data = await request.json()
        pessoa_id = data.get("pessoa_id")
        if not pessoa_id:
            raise HTTPException(status_code=400, detail="pessoa_id é obrigatório")
        papel = (data.get("papel") or "outro").strip().lower()
        if papel not in PAPEIS_VALIDOS:
            papel = "outro"
        with conn_factory() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT id FROM abordagens WHERE id=%s LIMIT 1", (abordagem_id,))
                if not cur.fetchone():
                    raise HTTPException(status_code=404, detail="Abordagem não encontrada")
                cur.execute("SELECT id FROM pessoas WHERE id=%s LIMIT 1", (pessoa_id,))
                if not cur.fetchone():
                    raise HTTPException(status_code=404, detail="Pessoa não encontrada")
                cur.execute(
                    """
                    INSERT INTO abordagem_pessoas
                        (abordagem_id, pessoa_id, papel, observacao_pessoal)
                    VALUES (%s,%s,%s,%s)
                    ON CONFLICT (abordagem_id, pessoa_id) DO UPDATE
                        SET papel=EXCLUDED.papel,
                            observacao_pessoal=EXCLUDED.observacao_pessoal
                    """,
                    (
                        abordagem_id,
                        int(pessoa_id),
                        papel,
                        normalize_str_fn(data.get("observacao_pessoal")),
                    ),
                )
        return {"ok": True}

    @router.delete("/api/abordagens/{abordagem_id}/pessoas/{pessoa_id}", status_code=204)
    def desvincular_pessoa_abordagem(abordagem_id: int, pessoa_id: int, request: Request):
        """Remove o vínculo de uma pessoa em uma abordagem."""
        assert_admin_or_operator_fn(
            request,
            "Apenas administradores e operadores podem remover pessoas de abordagens",
        )
        with conn_factory() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "DELETE FROM abordagem_pessoas WHERE abordagem_id=%s AND pessoa_id=%s",
                    (abordagem_id, pessoa_id),
                )
                if cur.rowcount == 0:
                    raise HTTPException(status_code=404, detail="Vínculo não encontrado")
        return None

    @router.delete("/api/abordagens/{abordagem_id}", status_code=204)
    def excluir_abordagem(abordagem_id: int, request: Request):
        """Remove uma abordagem e todos os seus vínculos (CASCADE)."""
        assert_admin_fn(request, "Apenas administradores podem excluir abordagens")
        with conn_factory() as conn:
            with conn.cursor() as cur:
                cur.execute("DELETE FROM abordagens WHERE id=%s", (abordagem_id,))
                if cur.rowcount == 0:
                    raise HTTPException(status_code=404, detail="Abordagem não encontrada")
        return None

    return router
