"""
Serviço de similaridade de rota entre dois alvos/veículos com base em eventos LPR.

Regras de pontuação:
  +2  por camera_id igual (ambos os eventos têm camera_id válido e coincidente)
  +1  por camera_ip igual (quando não há camera_id igual ou câmera não tem id)
  +1  extra se os dois eventos ocorreram dentro da janela de tempo configurável

Classificação textual:
  0           → sem_similaridade
  1–3         → baixa
  4–7         → media
  ≥ 8         → alta
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

# ─────────────────────────────────────────────────────────────────────────────
# Helpers internos
# ─────────────────────────────────────────────────────────────────────────────

def _parse_dt(value: Any) -> datetime | None:
    """Converte string ISO-8601, datetime ou None para datetime aware (UTC)."""
    if value is None:
        return None
    if isinstance(value, datetime):
        dt = value
    else:
        try:
            dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except (ValueError, TypeError):
            return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def _within_window(dt_a: datetime | None, dt_b: datetime | None, window_minutes: int) -> bool:
    """Retorna True se os dois instantes estão dentro da janela de tempo."""
    if dt_a is None or dt_b is None or window_minutes <= 0:
        return False
    diff = abs((dt_a - dt_b).total_seconds())
    return diff <= window_minutes * 60


def _classify(score: int) -> str:
    if score <= 0:
        return "sem_similaridade"
    if score <= 3:
        return "baixa"
    if score <= 7:
        return "media"
    return "alta"


# ─────────────────────────────────────────────────────────────────────────────
# Função principal
# ─────────────────────────────────────────────────────────────────────────────

def calcular_similaridade_rota(
    eventos_a: list[dict],
    eventos_b: list[dict],
    window_minutes: int = 30,
) -> dict:
    """
    Compara dois conjuntos de eventos LPR e calcula um score de similaridade.

    Parâmetros
    ----------
    eventos_a, eventos_b : list[dict]
        Listas de eventos. Cada evento pode conter:
          - camera_id   (str|None)
          - camera_ip   (str|None)
          - occurred_at (str ISO-8601 | datetime | None)
          - direction   (str|None)  — não usado na pontuação, apenas exposto no match
          - city        (str|None)  — idem

    window_minutes : int
        Janela em minutos para o bônus de tempo. Use 0 para desativar.

    Retorno
    -------
    {
        "score": int,
        "classificacao": "sem_similaridade" | "baixa" | "media" | "alta",
        "coincidencias": int,
        "matches": [
            {
                "camera_id":        str|None,
                "camera_ip":        str|None,
                "match_tipo":       "camera_id" | "camera_ip",
                "bonus_tempo":      bool,
                "pontos":           int,
                "evento_a": { ... },
                "evento_b": { ... },
            },
            ...
        ],
        "total_eventos_a":  int,
        "total_eventos_b":  int,
        "window_minutes":   int,
    }
    """
    if not eventos_a or not eventos_b:
        return {
            "score":           0,
            "classificacao":   "sem_similaridade",
            "coincidencias":   0,
            "matches":         [],
            "total_eventos_a": len(eventos_a) if eventos_a else 0,
            "total_eventos_b": len(eventos_b) if eventos_b else 0,
            "window_minutes":  window_minutes,
        }

    total_score = 0
    matches: list[dict] = []

    # Para evitar contar o mesmo par (idx_a, idx_b) mais de uma vez,
    # guardamos índices já usados em cada lista (um evento só entra em um match).
    used_a: set[int] = set()
    used_b: set[int] = set()

    # ── Passo 1: matches por camera_id ──────────────────────────────────────
    # Indexa eventos_b por camera_id para acesso O(1)
    cam_id_index: dict[str, list[int]] = {}
    for idx_b, ev_b in enumerate(eventos_b):
        cid = (ev_b.get("camera_id") or "").strip()
        if cid:
            cam_id_index.setdefault(cid, []).append(idx_b)

    for idx_a, ev_a in enumerate(eventos_a):
        if idx_a in used_a:
            continue
        cid_a = (ev_a.get("camera_id") or "").strip()
        if not cid_a:
            continue
        for idx_b in cam_id_index.get(cid_a, []):
            if idx_b in used_b:
                continue
            ev_b = eventos_b[idx_b]
            dt_a = _parse_dt(ev_a.get("occurred_at"))
            dt_b = _parse_dt(ev_b.get("occurred_at"))
            bonus = _within_window(dt_a, dt_b, window_minutes)
            pontos = 2 + (1 if bonus else 0)
            total_score += pontos
            matches.append({
                "camera_id":  cid_a,
                "camera_ip":  ev_a.get("camera_ip") or ev_b.get("camera_ip"),
                "match_tipo": "camera_id",
                "bonus_tempo": bonus,
                "pontos":     pontos,
                "evento_a":   _evento_resumo(ev_a),
                "evento_b":   _evento_resumo(ev_b),
            })
            used_a.add(idx_a)
            used_b.add(idx_b)
            break  # cada evento_a entra em no máximo um match

    # ── Passo 2: matches por camera_ip (apenas não pareados ainda) ───────────
    # Indexa eventos_b não usados por camera_ip
    cam_ip_index: dict[str, list[int]] = {}
    for idx_b, ev_b in enumerate(eventos_b):
        if idx_b in used_b:
            continue
        cip = (ev_b.get("camera_ip") or "").strip()
        if cip:
            cam_ip_index.setdefault(cip, []).append(idx_b)

    for idx_a, ev_a in enumerate(eventos_a):
        if idx_a in used_a:
            continue
        cip_a = (ev_a.get("camera_ip") or "").strip()
        if not cip_a:
            continue
        for idx_b in cam_ip_index.get(cip_a, []):
            if idx_b in used_b:
                continue
            ev_b = eventos_b[idx_b]
            dt_a = _parse_dt(ev_a.get("occurred_at"))
            dt_b = _parse_dt(ev_b.get("occurred_at"))
            bonus = _within_window(dt_a, dt_b, window_minutes)
            pontos = 1 + (1 if bonus else 0)
            total_score += pontos
            matches.append({
                "camera_id":   ev_a.get("camera_id") or ev_b.get("camera_id"),
                "camera_ip":   cip_a,
                "match_tipo":  "camera_ip",
                "bonus_tempo": bonus,
                "pontos":      pontos,
                "evento_a":    _evento_resumo(ev_a),
                "evento_b":    _evento_resumo(ev_b),
            })
            used_a.add(idx_a)
            used_b.add(idx_b)
            break

    return {
        "score":           total_score,
        "classificacao":   _classify(total_score),
        "coincidencias":   len(matches),
        "matches":         matches,
        "total_eventos_a": len(eventos_a),
        "total_eventos_b": len(eventos_b),
        "window_minutes":  window_minutes,
    }


def _evento_resumo(ev: dict) -> dict:
    """Retorna campos relevantes de um evento para exibição no match."""
    return {
        "camera_id":   ev.get("camera_id"),
        "camera_ip":   ev.get("camera_ip"),
        "occurred_at": ev.get("occurred_at"),
        "direction":   ev.get("direction"),
        "city":        ev.get("city"),
    }
