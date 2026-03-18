import re
from typing import Any, Callable, Optional

from fastapi import APIRouter, HTTPException, Request

from cadastro_support import (
    _PESSOA_SELECT,
    _VEICULO_SELECT,
    _pessoa_row_to_dict,
    _veiculo_row_to_dict,
)


def build_consulta_router(
    conn_factory: Callable[[], Any],
    require_auth_fn: Callable[[Request], Any],
) -> APIRouter:
    router = APIRouter(tags=["consulta-relatorio"])

    def _ocupantes_da_abordagem(abordagem_id: int) -> list:
        """Retorna lista de ocupantes (pessoa + papel) de uma abordagem."""
        with conn_factory() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT p.id, p.nome, p.apelido, p.cpf, p.rg,
                           ap.papel, ap.observacao_pessoal
                    FROM abordagem_pessoas ap
                    JOIN pessoas p ON p.id = ap.pessoa_id
                    WHERE ap.abordagem_id = %s
                    ORDER BY p.nome
                    """,
                    (abordagem_id,),
                )
                return [
                    {
                        "id": row[0],
                        "nome": row[1],
                        "apelido": row[2],
                        "cpf": row[3],
                        "rg": row[4],
                        "papel": row[5],
                        "observacao_pessoal": row[6],
                    }
                    for row in cur.fetchall()
                ]

    def _abordagens_da_pessoa(pessoa_id: int) -> list:
        """Retorna histórico de abordagens de uma pessoa, com veículo e ocupantes."""
        with conn_factory() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT a.id, a.data_hora, a.local, a.equipe, a.tipo_motivo,
                           a.observacoes, ap.papel, ap.observacao_pessoal,
                           v.placa, v.marca, v.modelo, v.cor, v.ano
                    FROM abordagem_pessoas ap
                    JOIN abordagens a ON a.id = ap.abordagem_id
                    LEFT JOIN veiculos_abordagem v ON v.id = a.veiculo_id
                    WHERE ap.pessoa_id = %s
                    ORDER BY a.data_hora DESC
                    """,
                    (pessoa_id,),
                )
                rows = cur.fetchall()

        result = []
        for row in rows:
            abordagem_id = row[0]
            result.append(
                {
                    "id": row[0],
                    "data_hora": row[1].isoformat() if row[1] else None,
                    "local": row[2],
                    "equipe": row[3],
                    "tipo_motivo": row[4],
                    "observacoes": row[5],
                    "papel_nesta": row[6],
                    "obs_pessoal": row[7],
                    "veiculo": {
                        "placa": row[8],
                        "marca": row[9],
                        "modelo": row[10],
                        "cor": row[11],
                        "ano": row[12],
                    }
                    if row[8]
                    else None,
                    "ocupantes": _ocupantes_da_abordagem(abordagem_id),
                }
            )
        return result

    def _abordagens_do_veiculo(veiculo_id: int) -> list:
        """Retorna histórico de abordagens de um veículo, com todos os ocupantes."""
        with conn_factory() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT a.id, a.data_hora, a.local, a.equipe, a.tipo_motivo, a.observacoes
                    FROM abordagens a
                    WHERE a.veiculo_id = %s
                    ORDER BY a.data_hora DESC
                    """,
                    (veiculo_id,),
                )
                rows = cur.fetchall()

        result = []
        for row in rows:
            abordagem_id = row[0]
            result.append(
                {
                    "id": row[0],
                    "data_hora": row[1].isoformat() if row[1] else None,
                    "local": row[2],
                    "equipe": row[3],
                    "tipo_motivo": row[4],
                    "observacoes": row[5],
                    "ocupantes": _ocupantes_da_abordagem(abordagem_id),
                }
            )
        return result

    @router.get("/api/consulta-relatorio")
    def consulta_relatorio(request: Request, q: Optional[str] = None):
        """
        Pesquisa unificada por nome, CPF ou placa.
        Retorna ficha + histórico completo de abordagens.
        """
        require_auth_fn(request)
        if not q or not q.strip():
            raise HTTPException(status_code=400, detail="Parâmetro q é obrigatório")

        termo = q.strip()
        digitos = "".join(ch for ch in termo if ch.isdigit())

        placa_pattern = re.compile(r"^[A-Za-z]{3}[\w]{4,5}$")
        if placa_pattern.match(termo.replace("-", "").replace(" ", "")):
            tipo_busca = "placa"
        elif len(digitos) == 11:
            tipo_busca = "cpf"
        else:
            tipo_busca = "nome"

        resultados = []

        if tipo_busca == "placa":
            placa_norm = termo.replace("-", "").replace(" ", "").upper()
            with conn_factory() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        _VEICULO_SELECT + "WHERE placa ILIKE %s LIMIT 10",
                        (f"%{placa_norm}%",),
                    )
                    veiculos = [_veiculo_row_to_dict(row) for row in cur.fetchall()]

            for veiculo in veiculos:
                abordagens = _abordagens_do_veiculo(veiculo["id"])
                resultados.append(
                    {
                        "tipo": "veiculo",
                        "ficha": veiculo,
                        "total_abordagens": len(abordagens),
                        "abordagens": abordagens,
                    }
                )
        elif tipo_busca == "cpf":
            with conn_factory() as conn:
                with conn.cursor() as cur:
                    cur.execute(_PESSOA_SELECT + "WHERE cpf=%s LIMIT 10", (digitos,))
                    pessoas = [_pessoa_row_to_dict(row) for row in cur.fetchall()]
            for pessoa in pessoas:
                abordagens = _abordagens_da_pessoa(pessoa["id"])
                resultados.append(
                    {
                        "tipo": "pessoa",
                        "ficha": pessoa,
                        "total_abordagens": len(abordagens),
                        "abordagens": abordagens,
                    }
                )
        else:
            term = f"%{termo}%"
            with conn_factory() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        _PESSOA_SELECT + "WHERE nome ILIKE %s OR apelido ILIKE %s LIMIT 20",
                        (term, term),
                    )
                    pessoas = [_pessoa_row_to_dict(row) for row in cur.fetchall()]
            for pessoa in pessoas:
                abordagens = _abordagens_da_pessoa(pessoa["id"])
                resultados.append(
                    {
                        "tipo": "pessoa",
                        "ficha": pessoa,
                        "total_abordagens": len(abordagens),
                        "abordagens": abordagens,
                    }
                )

        return {
            "tipo_busca": tipo_busca,
            "total_resultados": len(resultados),
            "resultados": resultados,
        }

    return router
