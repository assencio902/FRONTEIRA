from typing import Optional


def _clean_cpf(val: Optional[str]) -> Optional[str]:
    raw = "".join(ch for ch in (val or "") if ch.isdigit())
    return raw or None


_PESSOA_SELECT = """
    SELECT id, nome, apelido, contato, profissao, cpf, rg,
           data_nascimento, naturalidade, estado_naturalidade,
           nome_mae, nome_pai, foto_path, data_cadastro, endereco
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
        "foto_path": r[12],
        "data_cadastro": r[13].isoformat() if r[13] else None,
        "endereco": r[14],
    }


_VEICULO_SELECT = """
    SELECT id, placa, marca, modelo, cor, ano, tipo, foto_path, observacoes, data_cadastro
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
        "foto_path": r[7],
        "observacoes": r[8],
        "data_cadastro": r[9].isoformat() if r[9] else None,
    }
