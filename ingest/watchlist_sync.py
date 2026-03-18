import logging

from services.fcm_service import normalize_plate

logger = logging.getLogger(__name__)

ALVOS_LIST_NAME = "Alvos Rastreados"


def _normalize_plate(value: str | None) -> str:
    return normalize_plate(value)


def _get_or_create_alvos_list_id(cur) -> int:
    """Retorna o id da lista 'Alvos Rastreados', criando-a se necessário."""
    cur.execute("SELECT id FROM vehicle_lists WHERE name = %s", (ALVOS_LIST_NAME,))
    row = cur.fetchone()
    if row:
        cur.execute("UPDATE vehicle_lists SET alarm_enabled = TRUE WHERE id = %s", (row[0],))
        return row[0]
    cur.execute(
        """
        INSERT INTO vehicle_lists (name, description, color, alarm_enabled)
        VALUES (%s, %s, %s, TRUE)
        RETURNING id
        """,
        (
            ALVOS_LIST_NAME,
            "Gerada automaticamente pelo módulo Batedor/Alvos Rastreados",
            "#dc2626",
        ),
    )
    return cur.fetchone()[0]


def _sync_alvo_to_lista(cur, plate: str, descricao: str, old_plate: str = None):
    """Adiciona ou atualiza a placa na lista de monitoramento 'Alvos Rastreados'."""
    plate = _normalize_plate(plate)
    old_plate = _normalize_plate(old_plate) if old_plate else None
    list_id = _get_or_create_alvos_list_id(cur)
    notes = descricao or "Alvo rastreado"
    if old_plate and old_plate != plate:
        cur.execute(
            "DELETE FROM vehicle_list_items WHERE list_id = %s AND plate = %s",
            (list_id, old_plate),
        )
    cur.execute(
        """
        INSERT INTO vehicle_list_items (list_id, plate, notes, is_alvo)
        VALUES (%s, %s, %s, TRUE)
        ON CONFLICT (list_id, plate) DO UPDATE
            SET notes = EXCLUDED.notes,
                is_alvo = TRUE
        """,
        (list_id, plate, notes),
    )
    logger.info("[alvo-sync] upsert lista '%s' (id=%s) placa=%s", ALVOS_LIST_NAME, list_id, plate)


def _remove_alvo_from_lista(cur, plate: str):
    """Remove a placa da lista de monitoramento 'Alvos Rastreados'."""
    plate = _normalize_plate(plate)
    cur.execute("SELECT id FROM vehicle_lists WHERE name = %s", (ALVOS_LIST_NAME,))
    row = cur.fetchone()
    if row:
        cur.execute(
            "DELETE FROM vehicle_list_items WHERE list_id = %s AND plate = %s",
            (row[0], plate),
        )


def _vehicle_has_other_alvo(cur, plate: str, exclude_vli_id: int = None) -> bool:
    """Verifica se algum outro vehicle_list_item marca esta placa como alvo."""
    q = "SELECT 1 FROM vehicle_list_items WHERE plate = %s AND is_alvo = TRUE"
    params: list = [plate]
    if exclude_vli_id is not None:
        q += " AND id != %s"
        params.append(exclude_vli_id)
    cur.execute(q, params)
    return cur.fetchone() is not None


def _sync_vehicle_alvo_status(
    cur,
    plate: str,
    notes: str,
    is_alvo: bool,
    old_plate: str = None,
    old_is_alvo: bool = None,
    vli_id: int = None,
):
    """
    Sincroniza is_alvo do vehicle_list_item com a tabela alvos e a lista
    'Alvos Rastreados'. Chame esta função após gravar is_alvo no banco.
    """
    plate = _normalize_plate(plate)
    old_plate = _normalize_plate(old_plate) if old_plate else None
    descricao = notes or "Alvo rastreado"

    logger.info(
        "[alvo-sync] plate=%s is_alvo=%s old_plate=%s old_is_alvo=%s vli_id=%s",
        plate,
        is_alvo,
        old_plate,
        old_is_alvo,
        vli_id,
    )

    if is_alvo:
        old_p = old_plate if (old_plate and old_plate != plate) else None
        cur.execute(
            """
            INSERT INTO alvos (plate, descricao)
            VALUES (%s, %s)
            ON CONFLICT (plate) DO UPDATE SET descricao = EXCLUDED.descricao
            """,
            (plate, descricao),
        )
        logger.info("[alvo-sync] upsert tabela alvos: plate=%s descricao=%r", plate, descricao)
        _sync_alvo_to_lista(cur, plate, descricao, old_plate=old_p)
        if old_p and not _vehicle_has_other_alvo(cur, old_p, exclude_vli_id=vli_id):
            cur.execute("DELETE FROM alvos WHERE plate = %s", (old_p,))
            logger.info("[alvo-sync] removeu placa antiga de alvos: plate=%s", old_p)
    else:
        target_plate = old_plate if old_plate else plate
        if old_is_alvo and not _vehicle_has_other_alvo(cur, target_plate, exclude_vli_id=vli_id):
            cur.execute("DELETE FROM alvos WHERE plate = %s", (target_plate,))
            _remove_alvo_from_lista(cur, target_plate)
            logger.info("[alvo-sync] removeu de alvos e lista: plate=%s", target_plate)
        else:
            logger.info(
                "[alvo-sync] nenhuma remoção necessária: plate=%s old_is_alvo=%s",
                target_plate,
                old_is_alvo,
            )
