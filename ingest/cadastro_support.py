from typing import Optional


def _clean_cpf(val: Optional[str]) -> Optional[str]:
    raw = "".join(ch for ch in (val or "") if ch.isdigit())
    return raw or None


_PESSOA_SELECT = """
    SELECT id, nome, apelido, contato, profissao, cpf, rg,
           data_nascimento, naturalidade, estado_naturalidade,
           nome_mae, nome_pai, data_cadastro, endereco
    FROM pessoas
"""


def _pessoa_row_to_dict(r) -> dict:
    return {
        "id": r[0],
        "nome": r[1],
        "apelido": r[2],
        "contato": r[3],
        "profissao": r[4],
        "cpf": r[5],
        "rg": r[6],
        "data_nascimento": r[7].isoformat() if r[7] else None,
        "naturalidade": r[8],
        "estado_naturalidade": r[9],
        "nome_mae": r[10],
        "nome_pai": r[11],
        "data_cadastro": r[12].isoformat() if r[12] else None,
        "endereco": r[13],
    }


_VEICULO_SELECT = """
    SELECT id, placa, marca, modelo, cor, ano, tipo, observacoes, data_cadastro
    FROM veiculos_abordagem
"""


def _veiculo_row_to_dict(r) -> dict:
    return {
        "id": r[0],
        "placa": r[1],
        "marca": r[2],
        "modelo": r[3],
        "cor": r[4],
        "ano": r[5],
        "tipo": r[6],
        "observacoes": r[7],
        "data_cadastro": r[8].isoformat() if r[8] else None,
    }
