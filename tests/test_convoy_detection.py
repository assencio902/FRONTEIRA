"""
Testes unitários para _detect_convoy_groups.

Cenários sintéticos validam as regras:
  A) Co-detecção: veículos na mesma câmera com span ≤ window_s
  B) Comboio: ≥ 2 câmeras distintas com trip_span ≤ max_trip_gap_s
  C) Parceiros: só placas de grupos confirmados
"""
import sys
import types
from unittest import mock
from datetime import datetime, timedelta

# Mockar módulos externos para evitar instalar tudo
for mod_name in (
    "redis", "rq", "jose", "passlib", "passlib.context",
    "cleanup_background",
):
    if mod_name not in sys.modules:
        sys.modules[mod_name] = types.ModuleType(mod_name)

# Atributos necessários pelo módulo
sys.modules["jose"].JWTError = type("JWTError", (Exception,), {})
sys.modules["jose"].jwt = mock.MagicMock()
sys.modules["passlib.context"].CryptContext = mock.MagicMock()
sys.modules["cleanup_background"].start_cleanup_background = mock.MagicMock()
sys.modules["cleanup_background"].stop_cleanup_background = mock.MagicMock()
sys.modules["rq"].Queue = mock.MagicMock()

import pytest

# ── Importa a função sob teste ──────────────────────────────────────────
import ingest.main as main
_detect = main._detect_convoy_groups


# ── FakeCursor retorna rows pré-construídos ─────────────────────────────
class FakeCursor:
    """Cursor fake que ignora a query e devolve rows fixos."""

    def __init__(self, rows):
        self._rows = rows

    def execute(self, query, params=None):
        pass  # ignora a query SQL

    def fetchall(self):
        return list(self._rows)


def _dt(minutes: int) -> datetime:
    """Gera datetime offset relativo a um horário base."""
    return datetime(2025, 7, 1, 10, 0, 0) + timedelta(minutes=minutes)


# ══════════════════════════════════════════════════════════════════════════
# 1. Cenário positivo: A, B, C juntos em cam1 e cam2 dentro de 1h
# ══════════════════════════════════════════════════════════════════════════
def test_basic_convoy_detected():
    """
    cam1: A(0min), B(1min), C(2min)  -- span 2min, dentro de window 300s
    cam2: A(30min), B(31min), C(32min)  -- span 2min
    Trip span (cam1→cam2) = 30min = 1800s ≤ 3600 → comboio confirmado.
    """
    rows = [
        # (camera_id, cam_nome, plate, event_time)
        ("cam1", "Câmera 1", "AAA1111", _dt(0)),
        ("cam1", "Câmera 1", "BBB2222", _dt(1)),
        ("cam1", "Câmera 1", "CCC3333", _dt(2)),
        ("cam2", "Câmera 2", "AAA1111", _dt(30)),
        ("cam2", "Câmera 2", "BBB2222", _dt(31)),
        ("cam2", "Câmera 2", "CCC3333", _dt(32)),
    ]
    cur = FakeCursor(rows)
    result = _detect(
        cur,
        t_from=_dt(-10),
        t_to=_dt(60),
        window_s=300,
        max_trip_gap_s=3600,
        min_cameras=2,
    )

    assert len(result) > 0, "Deveria detectar pelo menos um grupo de comboio"

    # Placa A deve ser parceira de B e C
    groups_with_a = [g for g in result if "AAA1111" in g["plates"]]
    assert len(groups_with_a) > 0, "AAA1111 deve estar em algum grupo"

    # Cada grupo com A deve ter ≥ 2 câmeras
    for g in groups_with_a:
        assert g["cameras_count"] >= 2
        assert g["trip_span_sec"] <= 3600

    # Deve existir o par (A, B)
    ab_groups = [g for g in result if {"AAA1111", "BBB2222"} <= set(g["plates"])]
    assert len(ab_groups) >= 1, "Deve existir grupo contendo A e B"


# ══════════════════════════════════════════════════════════════════════════
# 2. Cenário negativo: apenas 1 câmera → sem comboio
# ══════════════════════════════════════════════════════════════════════════
def test_single_camera_no_convoy():
    """A e B juntos apenas em cam1 → min_cameras=2 não é atingido."""
    rows = [
        ("cam1", "Câmera 1", "AAA1111", _dt(0)),
        ("cam1", "Câmera 1", "BBB2222", _dt(1)),
    ]
    cur = FakeCursor(rows)
    result = _detect(
        cur,
        t_from=_dt(-10),
        t_to=_dt(60),
        window_s=300,
        max_trip_gap_s=3600,
        min_cameras=2,
    )
    assert len(result) == 0, "1 câmera não é suficiente para comboio"


# ══════════════════════════════════════════════════════════════════════════
# 3. Cenário negativo: trip_span excede 1h
# ══════════════════════════════════════════════════════════════════════════
def test_trip_span_exceeds_max():
    """
    cam1: A,B juntos em T=0
    cam2: A,B juntos em T=120min → trip_span = 2h > max 3600s → rejeitado.
    """
    rows = [
        ("cam1", "Câmera 1", "AAA1111", _dt(0)),
        ("cam1", "Câmera 1", "BBB2222", _dt(1)),
        ("cam2", "Câmera 2", "AAA1111", _dt(120)),
        ("cam2", "Câmera 2", "BBB2222", _dt(121)),
    ]
    cur = FakeCursor(rows)
    result = _detect(
        cur,
        t_from=_dt(-10),
        t_to=_dt(150),
        window_s=300,
        max_trip_gap_s=3600,
        min_cameras=2,
    )
    assert len(result) == 0, "Trip span > 1h deve ser rejeitado"


# ══════════════════════════════════════════════════════════════════════════
# 4. Cenário negativo: span na câmera excede window_s
# ══════════════════════════════════════════════════════════════════════════
def test_window_exceeded_per_camera():
    """
    cam1: A em T=0, B em T=10min → span=600s; com window_s=120 → cluster falha.
    cam2: A em T=30, B em T=40 → span=600s → falha idem.
    """
    rows = [
        ("cam1", "Câmera 1", "AAA1111", _dt(0)),
        ("cam1", "Câmera 1", "BBB2222", _dt(10)),
        ("cam2", "Câmera 2", "AAA1111", _dt(30)),
        ("cam2", "Câmera 2", "BBB2222", _dt(40)),
    ]
    cur = FakeCursor(rows)
    result = _detect(
        cur,
        t_from=_dt(-10),
        t_to=_dt(60),
        window_s=120,   # 2 min — span de 10 min não cabe
        max_trip_gap_s=3600,
        min_cameras=2,
    )
    assert len(result) == 0, "Span de 10min excede window_s de 120s"


# ══════════════════════════════════════════════════════════════════════════
# 5. target_plate filtra apenas grupos do alvo
# ══════════════════════════════════════════════════════════════════════════
def test_target_plate_filter():
    """
    A,B em cam1+cam2 em T=0; C,D em cam1+cam2 em T=10min (fora da janela de 120s).
    target_plate=AAA1111 → só retorna grupos contendo A.
    """
    rows = [
        # Grupo A+B (T=0..1min)
        ("cam1", "Câmera 1", "AAA1111", _dt(0)),
        ("cam1", "Câmera 1", "BBB2222", _dt(1)),
        ("cam2", "Câmera 2", "AAA1111", _dt(20)),
        ("cam2", "Câmera 2", "BBB2222", _dt(21)),
        # Grupo C+D (T=10..11min — fora da window de 120s do grupo A+B)
        ("cam1", "Câmera 1", "CCC3333", _dt(10)),
        ("cam1", "Câmera 1", "DDD4444", _dt(11)),
        ("cam2", "Câmera 2", "CCC3333", _dt(30)),
        ("cam2", "Câmera 2", "DDD4444", _dt(31)),
    ]
    cur = FakeCursor(rows)
    result = _detect(
        cur,
        t_from=_dt(-10),
        t_to=_dt(60),
        window_s=120,   # 2min — separa os dois grupos
        max_trip_gap_s=3600,
        min_cameras=2,
        target_plate="AAA1111",
    )
    assert all("AAA1111" in g["plates"] for g in result), \
        "Com target_plate, todos os grupos devem conter AAA1111"
    assert not any("DDD4444" in g["plates"] for g in result), \
        "DDD4444 não deveria aparecer nos grupos de AAA1111"


# ══════════════════════════════════════════════════════════════════════════
# 6. Verifica campos do resultado
# ══════════════════════════════════════════════════════════════════════════
def test_result_structure():
    """Valida que o resultado tem todos os campos esperados."""
    rows = [
        ("cam1", "Câmera 1", "AAA1111", _dt(0)),
        ("cam1", "Câmera 1", "BBB2222", _dt(1)),
        ("cam2", "Câmera 2", "AAA1111", _dt(20)),
        ("cam2", "Câmera 2", "BBB2222", _dt(21)),
    ]
    cur = FakeCursor(rows)
    result = _detect(
        cur,
        t_from=_dt(-10),
        t_to=_dt(60),
        window_s=300,
        max_trip_gap_s=3600,
        min_cameras=2,
    )
    assert len(result) >= 1
    g = result[0]
    required_keys = {
        "plates", "group_size", "cameras_count", "cameras",
        "cameras_confirmed", "trip_span_sec", "first_seen", "last_seen",
    }
    assert required_keys <= set(g.keys()), \
        f"Faltam campos: {required_keys - set(g.keys())}"
    assert g["group_size"] == len(g["plates"])
    assert g["cameras_count"] == len(g["cameras_confirmed"])
    # cameras_confirmed entries
    cc = g["cameras_confirmed"][0]
    cc_keys = {"camera_id", "cam_nome", "ts_min", "ts_max", "span_sec", "plate_order"}
    assert cc_keys <= set(cc.keys()), \
        f"Faltam campos em cameras_confirmed: {cc_keys - set(cc.keys())}"


# ══════════════════════════════════════════════════════════════════════════
# 7. Cenário do usuário: cam1 120s, cam2 300s, trip ≤ 3600
# ══════════════════════════════════════════════════════════════════════════
def test_user_scenario_a_b_c():
    """
    Cenário solicitado pelo usuário:
      cam1: A,B,C dentro de 120s
      cam2: A,B,C dentro de 300s
      timestamps cam1→cam2 dentro de 3600s
    Deve retornar comboio com parceiros [B,C] para A.
    """
    rows = [
        # cam1: A(0s), B(60s=1min), C(120s=2min) — span 120s ≤ 300
        ("cam1", "Câmera 1", "AAA1111", _dt(0)),
        ("cam1", "Câmera 1", "BBB2222", _dt(1)),
        ("cam1", "Câmera 1", "CCC3333", _dt(2)),
        # cam2: A(40min), B(43min), C(45min) — span 5min=300s ≤ 300
        ("cam2", "Câmera 2", "AAA1111", _dt(40)),
        ("cam2", "Câmera 2", "BBB2222", _dt(43)),
        ("cam2", "Câmera 2", "CCC3333", _dt(45)),
    ]
    cur = FakeCursor(rows)
    result = _detect(
        cur,
        t_from=_dt(-10),
        t_to=_dt(60),
        window_s=300,
        max_trip_gap_s=3600,
        min_cameras=2,
        target_plate="AAA1111",
    )

    assert len(result) > 0, "Deve detectar comboio para AAA1111"

    # Todas as placas parceiras de A
    partner_plates = set()
    for g in result:
        for p in g["plates"]:
            if p != "AAA1111":
                partner_plates.add(p)

    assert "BBB2222" in partner_plates, "BBB2222 deve ser parceiro de A"
    assert "CCC3333" in partner_plates, "CCC3333 deve ser parceiro de A"

    # Trip span deve ser ≤ 3600
    for g in result:
        assert g["trip_span_sec"] <= 3600

    # Deve ter ≥ 2 câmeras
    for g in result:
        assert g["cameras_count"] >= 2


# ══════════════════════════════════════════════════════════════════════════
# 8. Cenário: veículo isolado (apenas 1 placa por câmera)
# ══════════════════════════════════════════════════════════════════════════
def test_single_vehicle_no_result():
    """Apenas 1 veículo em cada câmera — sem par possível."""
    rows = [
        ("cam1", "Câmera 1", "AAA1111", _dt(0)),
        ("cam2", "Câmera 2", "AAA1111", _dt(30)),
    ]
    cur = FakeCursor(rows)
    result = _detect(
        cur,
        t_from=_dt(-10),
        t_to=_dt(60),
        window_s=300,
        max_trip_gap_s=3600,
        min_cameras=2,
    )
    assert len(result) == 0, "Veículo isolado não forma grupo"


# ══════════════════════════════════════════════════════════════════════════
# 9. window_s é clamped para [1, 1000]
# ══════════════════════════════════════════════════════════════════════════
def test_window_clamping():
    """window_s=0 deve ser clamped para 1; window_s=9999 para 1000."""
    rows = [
        ("cam1", "Câmera 1", "AAA1111", _dt(0)),
        ("cam1", "Câmera 1", "BBB2222", _dt(0)),  # mesmo instante
        ("cam2", "Câmera 2", "AAA1111", _dt(10)),
        ("cam2", "Câmera 2", "BBB2222", _dt(10)),
    ]
    cur = FakeCursor(rows)

    # window_s=0 → clamped para 1; span=0 ≤ 1 → deve funcionar
    result = _detect(
        cur, t_from=_dt(-10), t_to=_dt(60),
        window_s=0, max_trip_gap_s=3600, min_cameras=2,
    )
    assert len(result) >= 1, "window_s clamped para 1, span=0 deve funcionar"

    # window_s=99999 → clamped para 1000
    result2 = _detect(
        cur, t_from=_dt(-10), t_to=_dt(60),
        window_s=99999, max_trip_gap_s=3600, min_cameras=2,
    )
    assert len(result2) >= 1


# ══════════════════════════════════════════════════════════════════════════
# 10. min_cameras=1 retorna coincidências de 1 câmera (para teste via curl)
# ══════════════════════════════════════════════════════════════════════════
def test_min_cameras_1_returns_single_camera():
    """
    Com min_cameras=1, basta 1 câmera para formar grupo.
    A e B juntos em cam1 → deve retornar grupo.
    """
    rows = [
        ("cam1", "Câmera 1", "AAA1111", _dt(0)),
        ("cam1", "Câmera 1", "BBB2222", _dt(1)),
    ]
    cur = FakeCursor(rows)
    result = _detect(
        cur,
        t_from=_dt(-10),
        t_to=_dt(60),
        window_s=300,
        max_trip_gap_s=3600,
        min_cameras=1,
    )
    assert len(result) >= 1, "min_cameras=1 deve retornar grupo de 1 câmera"
    assert result[0]["cameras_count"] == 1


def test_min_cameras_2_rejects_single_camera():
    """
    Com min_cameras=2 (padrão), A e B juntos em 1 câmera NÃO basta.
    """
    rows = [
        ("cam1", "Câmera 1", "AAA1111", _dt(0)),
        ("cam1", "Câmera 1", "BBB2222", _dt(1)),
    ]
    cur = FakeCursor(rows)
    result = _detect(
        cur,
        t_from=_dt(-10),
        t_to=_dt(60),
        window_s=300,
        max_trip_gap_s=3600,
        min_cameras=2,
    )
    assert len(result) == 0, "min_cameras=2 rejeita grupo de 1 câmera"


# ══════════════════════════════════════════════════════════════════════════
# 11. Cameras diferentes ao mesmo tempo NÃO conta como comboio
# ══════════════════════════════════════════════════════════════════════════
def test_different_cameras_not_convoy():
    """
    A em cam1 e B em cam2 ao mesmo tempo → NÃO são parceiros.
    Parceiro exige mesma câmera.
    """
    rows = [
        ("cam1", "Câmera 1", "AAA1111", _dt(0)),
        ("cam2", "Câmera 2", "BBB2222", _dt(0)),
        ("cam3", "Câmera 3", "AAA1111", _dt(30)),
        ("cam4", "Câmera 4", "BBB2222", _dt(30)),
    ]
    cur = FakeCursor(rows)
    result = _detect(
        cur,
        t_from=_dt(-10),
        t_to=_dt(60),
        window_s=300,
        max_trip_gap_s=3600,
        min_cameras=2,
    )
    assert len(result) == 0, "Câmeras diferentes não formam parceria"


# ══════════════════════════════════════════════════════════════════════════
# 13. Parceiro diferente por câmera → vazio quando min_cameras=2
# ══════════════════════════════════════════════════════════════════════════
def test_different_partner_per_camera():
    """
    A+B em cam1, A+C em cam2 (B nunca aparece em cam2, C nunca em cam1).
    Par (A,B) = 1 câmera, Par (A,C) = 1 câmera → nenhum par atinge 2 câmeras.
    Deve retornar vazio com min_cameras=2.
    """
    rows = [
        ("cam1", "Câmera 1", "AAA1111", _dt(0)),
        ("cam1", "Câmera 1", "BBB2222", _dt(1)),
        ("cam2", "Câmera 2", "AAA1111", _dt(30)),
        ("cam2", "Câmera 2", "CCC3333", _dt(31)),
    ]
    cur = FakeCursor(rows)
    result = _detect(
        cur,
        t_from=_dt(-10),
        t_to=_dt(60),
        window_s=300,
        max_trip_gap_s=3600,
        min_cameras=2,
    )
    assert len(result) == 0, "Parceiro diferente por câmera não forma comboio"


# ══════════════════════════════════════════════════════════════════════════
# 14. Veículo sozinho em 2+ câmeras NÃO gera resultado
# ══════════════════════════════════════════════════════════════════════════
def test_solo_vehicle_multiple_cameras():
    """
    A sozinho em cam1 e cam2 → nenhum parceiro → nenhum grupo.
    """
    rows = [
        ("cam1", "Câmera 1", "AAA1111", _dt(0)),
        ("cam2", "Câmera 2", "AAA1111", _dt(30)),
        ("cam3", "Câmera 3", "AAA1111", _dt(50)),
    ]
    cur = FakeCursor(rows)
    result = _detect(
        cur,
        t_from=_dt(-10),
        t_to=_dt(60),
        window_s=300,
        max_trip_gap_s=3600,
        min_cameras=2,
    )
    assert len(result) == 0, "Veículo sozinho em 2+ câmeras não é comboio"
