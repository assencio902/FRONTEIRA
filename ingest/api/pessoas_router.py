from typing import Any, Callable, Optional

from fastapi import APIRouter, HTTPException, Request

from cadastro_support import _clean_cpf, _PESSOA_SELECT, _pessoa_row_to_dict


def build_pessoas_router(
    conn_factory: Callable[[], Any],
    require_auth_fn: Callable[[Request], Any],
    assert_admin_fn: Callable[[Request, str], Any],
    assert_admin_or_operator_fn: Callable[[Request, str], Any],
    verify_password_fn: Callable[[str, str], bool],
    normalize_str_fn: Callable[[Optional[str]], Optional[str]],
    parse_date_fn: Callable[[Optional[str]], Any],
) -> APIRouter:
    router = APIRouter(tags=["pessoas"])

    @router.get("/api/pessoas")
    def listar_pessoas(
        request: Request,
        q: Optional[str] = None,
        limit: int = 50,
        offset: int = 0,
    ):
        """Lista pessoas. Busca por nome, apelido, CPF ou RG."""
        require_auth_fn(request)
        limit = max(1, min(200, int(limit)))
        offset = max(0, int(offset))
        with conn_factory() as conn:
            with conn.cursor() as cur:
                if q and q.strip():
                    term = f"%{q.strip()}%"
                    where = " WHERE nome ILIKE %s OR apelido ILIKE %s OR cpf LIKE %s OR rg ILIKE %s "
                    cur.execute(
                        _PESSOA_SELECT + where + "ORDER BY nome ASC LIMIT %s OFFSET %s",
                        (term, term, term, term, limit, offset),
                    )
                    rows = cur.fetchall()
                    cur.execute("SELECT COUNT(*) FROM pessoas" + where, (term, term, term, term))
                else:
                    cur.execute(_PESSOA_SELECT + "ORDER BY nome ASC LIMIT %s OFFSET %s", (limit, offset))
                    rows = cur.fetchall()
                    cur.execute("SELECT COUNT(*) FROM pessoas")
                total = cur.fetchone()[0]
        return {"total": total, "pessoas": [_pessoa_row_to_dict(row) for row in rows]}

    @router.get("/api/pessoas/existe-cpf")
    def verificar_cpf_existente(request: Request, cpf: str):
        """Verifica se um CPF já está cadastrado. Retorna {existe, id, nome, pessoa}."""
        require_auth_fn(request)
        cpf_clean = _clean_cpf(cpf)
        if not cpf_clean or len(cpf_clean) != 11:
            raise HTTPException(status_code=400, detail="CPF deve ter 11 dígitos")
        with conn_factory() as conn:
            with conn.cursor() as cur:
                cur.execute(_PESSOA_SELECT + "WHERE cpf = %s LIMIT 1", (cpf_clean,))
                row = cur.fetchone()
        if not row:
            return {"existe": False}
        pessoa = _pessoa_row_to_dict(row)
        return {"existe": True, "id": pessoa["id"], "nome": pessoa["nome"], "pessoa": pessoa}

    @router.get("/api/pessoas/{pessoa_id}")
    def buscar_pessoa_por_id(pessoa_id: int, request: Request):
        """Retorna dados de uma pessoa pelo id."""
        require_auth_fn(request)
        with conn_factory() as conn:
            with conn.cursor() as cur:
                cur.execute(_PESSOA_SELECT + "WHERE id = %s LIMIT 1", (pessoa_id,))
                row = cur.fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Pessoa não encontrada")
        return _pessoa_row_to_dict(row)

    @router.get("/api/pessoas/{pessoa_id}/relatorio")
    def relatorio_pessoa(pessoa_id: int, request: Request):
        """
        Relatório completo de uma pessoa:
          - dados cadastrais da pessoa
          - todas as abordagens vinculadas (com veículo e pessoas relacionadas)
          - resumo agregado com reincidências
        """
        require_auth_fn(request)
        with conn_factory() as conn:
            with conn.cursor() as cur:
                cur.execute(_PESSOA_SELECT + "WHERE id = %s LIMIT 1", (pessoa_id,))
                row = cur.fetchone()
                if not row:
                    raise HTTPException(status_code=404, detail="Pessoa não encontrada")
                pessoa = _pessoa_row_to_dict(row)

                cur.execute(
                    """
                    SELECT a.id, a.data_hora, a.local, a.equipe, a.tipo_motivo,
                           a.observacoes, a.data_cadastro,
                           v.id, v.placa, v.marca, v.modelo, v.cor, v.ano, v.tipo, v.observacoes
                    FROM abordagem_pessoas ap
                    JOIN abordagens a ON a.id = ap.abordagem_id
                    LEFT JOIN veiculos_abordagem v ON v.id = a.veiculo_id
                    WHERE ap.pessoa_id = %s
                    ORDER BY a.data_hora DESC
                    """,
                    (pessoa_id,),
                )
                ab_rows = cur.fetchall()
                abordagens = []
                ab_ids = []
                for row in ab_rows:
                    abordagens.append(
                        {
                            "id": row[0],
                            "data_hora": row[1].isoformat() if row[1] else None,
                            "local": row[2],
                            "equipe": row[3],
                            "tipo_motivo": row[4],
                            "observacoes": row[5],
                            "data_cadastro": row[6].isoformat() if row[6] else None,
                            "veiculo": {
                                "id": row[7],
                                "placa": row[8],
                                "marca": row[9],
                                "modelo": row[10],
                                "cor": row[11],
                                "ano": row[12],
                                "tipo": row[13],
                                "observacoes": row[14],
                                "listas": [],
                            }
                            if row[7]
                            else None,
                            "pessoas_relacionadas": [],
                        }
                    )
                    ab_ids.append(row[0])

                if ab_ids:
                    cur.execute(
                        """
                        SELECT ap.abordagem_id, ap.papel, ap.observacao_pessoal,
                               p.id, p.nome, p.apelido, p.cpf, p.rg
                        FROM abordagem_pessoas ap
                        JOIN pessoas p ON p.id = ap.pessoa_id
                        WHERE ap.abordagem_id = ANY(%s)
                          AND ap.pessoa_id != %s
                        ORDER BY ap.abordagem_id, p.nome
                        """,
                        (ab_ids, pessoa_id),
                    )
                    for pessoa_relacionada in cur.fetchall():
                        for abordagem in abordagens:
                            if abordagem["id"] == pessoa_relacionada[0]:
                                abordagem["pessoas_relacionadas"].append(
                                    {
                                        "papel": pessoa_relacionada[1],
                                        "observacao_pessoal": pessoa_relacionada[2],
                                        "id": pessoa_relacionada[3],
                                        "nome": pessoa_relacionada[4],
                                        "apelido": pessoa_relacionada[5],
                                        "cpf": pessoa_relacionada[6],
                                        "rg": pessoa_relacionada[7],
                                    }
                                )
                                break

                placas = list(
                    {
                        abordagem["veiculo"]["placa"]
                        for abordagem in abordagens
                        if abordagem["veiculo"] and abordagem["veiculo"]["placa"]
                    }
                )
                listas_por_placa: dict = {}
                if placas:
                    cur.execute(
                        """
                        SELECT vli.plate, vl.name, vl.color
                        FROM vehicle_list_items vli
                        JOIN vehicle_lists vl ON vl.id = vli.list_id
                        WHERE vli.plate = ANY(%s)
                        """,
                        (placas,),
                    )
                    for placa, nome, cor in cur.fetchall():
                        listas_por_placa.setdefault(placa, []).append({"nome": nome, "cor": cor})

                for abordagem in abordagens:
                    if abordagem["veiculo"] and abordagem["veiculo"]["placa"]:
                        abordagem["veiculo"]["listas"] = listas_por_placa.get(
                            abordagem["veiculo"]["placa"],
                            [],
                        )

        veic_map: dict = {}
        pess_map: dict = {}
        for abordagem in abordagens:
            if abordagem["veiculo"] and abordagem["veiculo"]["placa"]:
                placa = abordagem["veiculo"]["placa"]
                if placa not in veic_map:
                    veic_map[placa] = dict(abordagem["veiculo"])
                    veic_map[placa]["total_abordagens"] = 0
                veic_map[placa]["total_abordagens"] += 1
            for pessoa_relacionada in abordagem["pessoas_relacionadas"]:
                pessoa_relacionada_id = pessoa_relacionada["id"]
                if pessoa_relacionada_id not in pess_map:
                    pess_map[pessoa_relacionada_id] = dict(pessoa_relacionada)
                    pess_map[pessoa_relacionada_id]["total_abordagens"] = 0
                pess_map[pessoa_relacionada_id]["total_abordagens"] += 1

        veiculos_unicos = sorted(veic_map.values(), key=lambda item: -item["total_abordagens"])
        pessoas_unicas = sorted(pess_map.values(), key=lambda item: -item["total_abordagens"])

        return {
            "pessoa": pessoa,
            "abordagens": abordagens,
            "resumo": {
                "total_abordagens": len(abordagens),
                "veiculos_unicos": veiculos_unicos,
                "pessoas_unicas": pessoas_unicas,
                "reincidencias": {
                    "veiculos_reincidentes": [
                        item for item in veiculos_unicos if item["total_abordagens"] > 1
                    ],
                    "pessoas_reincidentes": [
                        item for item in pessoas_unicas if item["total_abordagens"] > 1
                    ],
                },
            },
        }

    @router.post("/api/pessoas", status_code=201)
    async def criar_pessoa(request: Request):
        """
        Cria pessoa no cadastro individual.
        Payload (JSON):
          nome*, apelido, contato, profissao, cpf, rg,
          data_nascimento (AAAA-MM-DD), naturalidade, estado_naturalidade,
          nome_mae, nome_pai, endereco
        """
        assert_admin_or_operator_fn(
            request,
            "Apenas administradores e operadores podem cadastrar pessoas",
        )
        data = await request.json()
        nome = normalize_str_fn(data.get("nome"))
        if not nome:
            raise HTTPException(status_code=400, detail="nome é obrigatório")
        cpf_raw = _clean_cpf(data.get("cpf"))
        if cpf_raw and len(cpf_raw) > 11:
            raise HTTPException(status_code=400, detail="CPF deve ter no máximo 11 dígitos")
        data_nascimento = parse_date_fn(data.get("data_nascimento"))
        with conn_factory() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO pessoas
                        (nome, apelido, contato, profissao, cpf, rg,
                         data_nascimento, naturalidade, estado_naturalidade,
                         nome_mae, nome_pai, endereco)
                    VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                    RETURNING id
                    """,
                    (
                        nome,
                        normalize_str_fn(data.get("apelido")),
                        normalize_str_fn(data.get("contato")),
                        normalize_str_fn(data.get("profissao")),
                        cpf_raw,
                        normalize_str_fn(data.get("rg")),
                        data_nascimento,
                        normalize_str_fn(data.get("naturalidade")),
                        normalize_str_fn(data.get("estado_naturalidade")),
                        normalize_str_fn(data.get("nome_mae")),
                        normalize_str_fn(data.get("nome_pai")),
                        normalize_str_fn(data.get("endereco")),
                    ),
                )
                new_id = cur.fetchone()[0]
        return {"ok": True, "id": new_id}

    @router.put("/api/pessoas/{pessoa_id}")
    async def atualizar_pessoa(pessoa_id: int, request: Request):
        """Atualiza cadastro individual de pessoa."""
        assert_admin_or_operator_fn(
            request,
            "Apenas administradores e operadores podem editar pessoas",
        )
        data = await request.json()
        nome = normalize_str_fn(data.get("nome"))
        if not nome:
            raise HTTPException(status_code=400, detail="nome é obrigatório")
        cpf_raw = _clean_cpf(data.get("cpf"))
        if cpf_raw and len(cpf_raw) > 11:
            raise HTTPException(status_code=400, detail="CPF deve ter no máximo 11 dígitos")
        data_nascimento = parse_date_fn(data.get("data_nascimento"))
        with conn_factory() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE pessoas SET
                        nome=%s, apelido=%s, contato=%s, profissao=%s,
                        cpf=%s, rg=%s, data_nascimento=%s,
                        naturalidade=%s, estado_naturalidade=%s,
                        nome_mae=%s, nome_pai=%s, endereco=%s
                    WHERE id=%s
                    """,
                    (
                        nome,
                        normalize_str_fn(data.get("apelido")),
                        normalize_str_fn(data.get("contato")),
                        normalize_str_fn(data.get("profissao")),
                        cpf_raw,
                        normalize_str_fn(data.get("rg")),
                        data_nascimento,
                        normalize_str_fn(data.get("naturalidade")),
                        normalize_str_fn(data.get("estado_naturalidade")),
                        normalize_str_fn(data.get("nome_mae")),
                        normalize_str_fn(data.get("nome_pai")),
                        normalize_str_fn(data.get("endereco")),
                        pessoa_id,
                    ),
                )
                if cur.rowcount == 0:
                    raise HTTPException(status_code=404, detail="Pessoa não encontrada")
        return {"ok": True}

    @router.delete("/api/pessoas/{pessoa_id}", status_code=204)
    async def excluir_pessoa(pessoa_id: int, request: Request):
        """
        Remove uma pessoa e todos os seus vínculos em cascata.
        Exige campo 'senha_confirmacao' no corpo JSON para autorizar a operação.
        """
        assert_admin_fn(
            request,
            "Apenas administradores podem excluir cadastros de pessoas",
        )
        try:
            body = await request.json()
        except Exception:
            body = {}
        senha_conf = str(body.get("senha_confirmacao") or "").strip()
        if not senha_conf:
            raise HTTPException(status_code=422, detail="Campo 'senha_confirmacao' é obrigatório.")

        user_payload = getattr(request.state, "user", None)
        if not user_payload:
            raise HTTPException(status_code=401, detail="Não autenticado.")
        username = user_payload.get("sub")
        if not username:
            raise HTTPException(status_code=401, detail="Não autenticado.")

        with conn_factory() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT password_hash FROM users WHERE username=%s AND ativa=TRUE LIMIT 1",
                    (username,),
                )
                row = cur.fetchone()
        if not row or not verify_password_fn(senha_conf, row[0]):
            raise HTTPException(
                status_code=403,
                detail="Senha incorreta. Exclusão não autorizada.",
            )

        with conn_factory() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT nome FROM pessoas WHERE id=%s LIMIT 1", (pessoa_id,))
                if not cur.fetchone():
                    raise HTTPException(status_code=404, detail="Pessoa não encontrada.")

                cur.execute(
                    """
                    DELETE FROM abordagens
                    WHERE id IN (
                        SELECT ap.abordagem_id
                        FROM abordagem_pessoas ap
                        WHERE ap.pessoa_id = %s
                        GROUP BY ap.abordagem_id
                        HAVING COUNT(ap.pessoa_id) = 1
                    )
                    """,
                    (pessoa_id,),
                )
                cur.execute("DELETE FROM abordagem_pessoas WHERE pessoa_id=%s", (pessoa_id,))
                cur.execute("DELETE FROM pessoas WHERE id=%s", (pessoa_id,))

        return None

    return router
