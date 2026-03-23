"""
cleanup_background.py — Worker de retencao de dados do LPR Monitor.

Variaveis de ambiente:
  CLEANUP_ENABLED          true|false            (default: true)
  CLEANUP_INTERVAL_SECONDS int                   (default: 600 = 10 min)
  CLEANUP_DRY_RUN          true|false            (default: false)
  RETENTION_DAYS_IMAGES    int                   (default: 7)
  RETENTION_DAYS_EVENTS    int                   (default: 30)
  MAX_UPLOADS_GB           float  0=sem limite   (default: 50)
  CLEANUP_MAX_USAGE_PERCENT float 0=desabilitado (default: 0)
  UPLOADS_DIR              path                  (default: /app/uploads)
"""

import os
import shutil
import subprocess
import threading
import time
import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path

logger = logging.getLogger("uvicorn.error")
# fallback para quando rodado fora do uvicorn (testes, etc.)
if not logger.handlers:
    _h = logging.StreamHandler()
    _h.setFormatter(logging.Formatter("%(asctime)s %(levelname)-8s %(name)s: %(message)s"))
    logger.addHandler(_h)
    logger.setLevel(logging.INFO)

# ---------------------------------------------------------------------------
# Configuracao via env
# ---------------------------------------------------------------------------
CLEANUP_ENABLED          = os.getenv("CLEANUP_ENABLED", "true").lower()  == "true"
CLEANUP_INTERVAL_SECONDS = int(os.getenv("CLEANUP_INTERVAL_SECONDS", "600"))
CLEANUP_DRY_RUN          = os.getenv("CLEANUP_DRY_RUN", "false").lower() == "true"
RETENTION_DAYS_IMAGES    = int(os.getenv("RETENTION_DAYS_IMAGES", "7"))
RETENTION_DAYS_EVENTS    = int(os.getenv("RETENTION_DAYS_EVENTS", "30"))
MAX_UPLOADS_GB           = float(os.getenv("MAX_UPLOADS_GB", "50"))   # 0 = sem limite
CLEANUP_MAX_USAGE_PERCENT = float(os.getenv("CLEANUP_MAX_USAGE_PERCENT", "0"))
UPLOADS_DIR              = Path(os.getenv("UPLOADS_DIR", "/app/uploads"))

_stop_event = threading.Event()


def _dry(msg: str) -> None:
    logger.info("[DRY-RUN] %s", msg)


# ---------------------------------------------------------------------------
# Helpers de disco
# ---------------------------------------------------------------------------
def _free_gb(path: Path) -> float:
    try:
        return shutil.disk_usage(str(path)).free / (1024 ** 3)
    except Exception:
        return 999.0


def _used_gb(path: Path) -> float:
    """Tamanho total da pasta em GB via 'du -sb' (rapido, sem rglob)."""
    try:
        result = subprocess.run(
            ["du", "-sb", str(path)],
            capture_output=True, text=True, timeout=15,
        )
        if result.returncode == 0:
            return int(result.stdout.split()[0]) / (1024 ** 3)
    except Exception:
        pass
    return 0.0


def _usage_percent(path: Path) -> float:
    try:
        usage = shutil.disk_usage(str(path))
        if usage.total <= 0:
            return 0.0
        return (usage.used / usage.total) * 100.0
    except Exception:
        return 0.0


# ---------------------------------------------------------------------------
# Limpeza de IMAGENS
# ---------------------------------------------------------------------------
def cleanup_images(conn_factory) -> None:
    """
    Apaga pastas YYYY-MM-DD em UPLOADS_DIR cujo dia seja anterior ao
    limite de RETENTION_DAYS_IMAGES. Nunca apaga o dia atual.
    Remove as referencias do banco (lpr_events) ANTES de deletar os arquivos.
    """
    today  = datetime.now(timezone.utc).date()
    cutoff = today - timedelta(days=RETENTION_DAYS_IMAGES)

    removed_dirs = 0

    if not UPLOADS_DIR.exists():
        return

    for day_dir in sorted(UPLOADS_DIR.iterdir()):
        if not day_dir.is_dir():
            continue
        try:
            dir_date = datetime.strptime(day_dir.name, "%Y-%m-%d").date()
        except ValueError:
            continue  # pasta com nome inesperado

        if dir_date >= today:
            continue  # nunca apagar o dia atual
        if dir_date > cutoff:
            continue  # dentro do periodo de retencao

        if CLEANUP_DRY_RUN:
            _dry(f"IMAGENS: removeria pasta {day_dir} (data {dir_date})")
            continue

        # Remover referencias do banco ANTES de deletar arquivos
        rel_prefix = f"/uploads/{day_dir.name}/"
        try:
            with conn_factory() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        "DELETE FROM lpr_events WHERE image_path LIKE %s",
                        (rel_prefix + "%",),
                    )
                    rows = cur.rowcount
            logger.info("IMAGENS[%s]: %d evento(s) removidos do banco.", day_dir.name, rows)
        except Exception as exc:
            logger.error("IMAGENS[%s]: erro ao limpar banco, pulando pasta: %s", day_dir.name, exc)
            continue  # consistencia: nao apaga arquivo se banco falhou

        # Remover pasta no disco
        try:
            shutil.rmtree(day_dir)
            removed_dirs += 1
            logger.info("IMAGENS[%s]: pasta removida.", day_dir.name)
        except Exception as exc:
            logger.error("IMAGENS[%s]: erro ao remover pasta: %s", day_dir.name, exc)

    if removed_dirs:
        logger.info("IMAGENS: ciclo concluido — %d pasta(s) apagadas.", removed_dirs)


# ---------------------------------------------------------------------------
# Limpeza de EVENTOS sem imagem
# ---------------------------------------------------------------------------
def cleanup_events(conn_factory) -> None:
    """
    Apaga registros de lpr_events sem image_path (ou com imagem ja removida)
    cujo occurred_at/ts seja anterior a RETENTION_DAYS_EVENTS.
    """
    cutoff = datetime.now(timezone.utc) - timedelta(days=RETENTION_DAYS_EVENTS)

    if CLEANUP_DRY_RUN:
        _dry(
            f"EVENTOS: removeria lpr_events sem imagem com ts < {cutoff.date()} "
            f"(RETENTION_DAYS_EVENTS={RETENTION_DAYS_EVENTS})"
        )
        return

    try:
        with conn_factory() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    DELETE FROM lpr_events
                    WHERE COALESCE(occurred_at, ts) < %s
                      AND (image_path IS NULL OR image_path = '')
                    """,
                    (cutoff,),
                )
                rows = cur.rowcount
        if rows:
            logger.info("EVENTOS: %d registro(s) sem imagem removidos (ts < %s).", rows, cutoff.date())
    except Exception as exc:
        logger.error("EVENTOS: erro ao limpar lpr_events: %s", exc)


# ---------------------------------------------------------------------------
# Limpeza por pressao de disco (fallback de emergencia)
# ---------------------------------------------------------------------------
def cleanup_by_disk_pressure(conn_factory) -> None:
    """
    Se MAX_UPLOADS_GB > 0 OU CLEANUP_MAX_USAGE_PERCENT > 0 e o uso da pasta
    uploads / filesystem ultrapassar o limite, apaga as pastas de dia mais
    antigas ate voltar abaixo do limite.
    """
    use_gb_limit = MAX_UPLOADS_GB > 0
    use_percent_limit = CLEANUP_MAX_USAGE_PERCENT > 0
    if not use_gb_limit and not use_percent_limit:
        return

    used = _used_gb(UPLOADS_DIR)
    usage_percent = _usage_percent(UPLOADS_DIR)
    over_gb_limit = use_gb_limit and used > MAX_UPLOADS_GB
    over_percent_limit = use_percent_limit and usage_percent > CLEANUP_MAX_USAGE_PERCENT
    if not over_gb_limit and not over_percent_limit:
        return

    reasons: list[str] = []
    if over_gb_limit:
        reasons.append(f"uploads usando {used:.1f} GB > limite {MAX_UPLOADS_GB:.1f} GB")
    if over_percent_limit:
        reasons.append(
            f"filesystem em {usage_percent:.1f}% > limite {CLEANUP_MAX_USAGE_PERCENT:.1f}%"
        )
    logger.warning("DISCO: %s. Iniciando limpeza de pressao.", " | ".join(reasons))

    def _still_over_limit() -> bool:
        current_used = _used_gb(UPLOADS_DIR)
        current_percent = _usage_percent(UPLOADS_DIR)
        return (
            (use_gb_limit and current_used > MAX_UPLOADS_GB)
            or (use_percent_limit and current_percent > CLEANUP_MAX_USAGE_PERCENT)
        )

    today = datetime.now(timezone.utc).date()
    day_dirs = sorted(
        (d for d in UPLOADS_DIR.iterdir() if d.is_dir()),
        key=lambda d: d.name,
    )

    for day_dir in day_dirs:
        if not _still_over_limit():
            break
        try:
            dir_date = datetime.strptime(day_dir.name, "%Y-%m-%d").date()
        except ValueError:
            continue
        if dir_date >= today:
            continue  # nunca apagar o dia atual

        if CLEANUP_DRY_RUN:
            _dry(f"DISCO: removeria {day_dir} para liberar espaco")
            continue

        rel_prefix = f"/uploads/{day_dir.name}/"
        try:
            with conn_factory() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        "DELETE FROM lpr_events WHERE image_path LIKE %s",
                        (rel_prefix + "%",),
                    )
        except Exception as exc:
            logger.error("DISCO[%s]: erro ao limpar banco: %s", day_dir.name, exc)
            continue

        try:
            shutil.rmtree(day_dir)
            logger.warning(
                "DISCO[%s]: pasta removida por pressao de disco (%.1f GB usados, %.1f%% do filesystem).",
                day_dir.name,
                _used_gb(UPLOADS_DIR),
                _usage_percent(UPLOADS_DIR),
            )
        except Exception as exc:
            logger.error("DISCO[%s]: erro ao remover: %s", day_dir.name, exc)


# ---------------------------------------------------------------------------
# Loop principal
# ---------------------------------------------------------------------------
def _cleanup_loop(conn_factory) -> None:
    logger.info(
        "Cleanup worker iniciado — interval=%ds images=%dd events=%dd "
        "max_gb=%.0f max_usage_percent=%.1f dry_run=%s",
        CLEANUP_INTERVAL_SECONDS,
        RETENTION_DAYS_IMAGES,
        RETENTION_DAYS_EVENTS,
        MAX_UPLOADS_GB,
        CLEANUP_MAX_USAGE_PERCENT,
        CLEANUP_DRY_RUN,
    )

    # Primeira execucao apos 60s (deixa o app e o banco subirem)
    _stop_event.wait(timeout=60)

    while not _stop_event.is_set():
        try:
            free = _free_gb(UPLOADS_DIR)
            used = _used_gb(UPLOADS_DIR)
            logger.info(
                "Cleanup ciclo — disco livre: %.1f GB | uploads: %.2f GB | uso_fs: %.1f%%",
                free, used,
                _usage_percent(UPLOADS_DIR),
            )
            cleanup_images(conn_factory)
            cleanup_events(conn_factory)
            cleanup_by_disk_pressure(conn_factory)
            logger.info("Cleanup ciclo concluido.")
        except Exception as exc:
            logger.error("Cleanup: erro inesperado no ciclo: %s", exc)

        _stop_event.wait(timeout=CLEANUP_INTERVAL_SECONDS)

    logger.info("Cleanup worker encerrado.")


# ---------------------------------------------------------------------------
# API publica
# ---------------------------------------------------------------------------
def start_cleanup_background(conn_factory) -> "threading.Thread | None":
    """
    Inicia o worker de cleanup em thread daemon.

    Args:
        conn_factory: callable que retorna um context-manager psycopg2
                      (ex.: a funcao _conn de main.py).
    Returns:
        Thread iniciada, ou None se CLEANUP_ENABLED=false.
    """
    if not CLEANUP_ENABLED:
        logger.info("Cleanup desabilitado via CLEANUP_ENABLED=false.")
        return None

    _stop_event.clear()
    t = threading.Thread(
        target=_cleanup_loop,
        args=(conn_factory,),
        daemon=True,
        name="lpr-cleanup",
    )
    t.start()
    return t


def stop_cleanup_background() -> None:
    """Sinaliza o worker para encerrar graciosamente."""
    _stop_event.set()
    logger.info("Cleanup worker: sinal de parada enviado.")
