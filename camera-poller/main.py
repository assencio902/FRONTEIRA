"""
Camera Poller — serviço que conecta a câmeras Hikvision no modo escuta HTTP.

Para câmeras em modo 'push': a câmera envia POST diretamente para /api/simple-webhook.
Para câmeras em modo 'listen': este serviço conecta via ISAPI Alert Stream
    (GET /ISAPI/Event/notification/alertStream) e repassa os eventos ao ingest.
"""

import os
import time
import logging
import threading
import xml.etree.ElementTree as ET

# LEGADO: o ambiente atual opera em push e o servico camera-poller
# foi removido do docker-compose. Este modulo fica apenas como referencia.

import requests
from requests.auth import HTTPDigestAuth, HTTPBasicAuth
import psycopg2

# ── Configuração ──────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-8s %(name)s — %(message)s",
)
log = logging.getLogger("camera-poller")

INGEST_URL   = os.environ.get("INGEST_URL", "http://ingest:8000")
DB_HOST      = os.environ.get("POSTGRES_HOST", "postgres")
DB_PORT      = int(os.environ.get("POSTGRES_PORT", "5432"))
DB_NAME      = os.environ.get("POSTGRES_DB", "monitor")
DB_USER      = os.environ.get("POSTGRES_USER", "monitor_user")
DB_PASS      = os.environ.get("POSTGRES_PASSWORD", "monitor_pass")
RECONNECT_DELAY = int(os.environ.get("RECONNECT_DELAY", "10"))   # segundos entre reconexões
REFRESH_INTERVAL = int(os.environ.get("REFRESH_INTERVAL", "60")) # verificar novas câmeras a cada N segundos

# ── Banco de dados ─────────────────────────────────────────────────────────────

def _dsn():
    return f"host={DB_HOST} port={DB_PORT} dbname={DB_NAME} user={DB_USER} password={DB_PASS}"


def get_listen_cameras() -> list[dict]:
    """Retorna câmeras ativas no modo 'listen' cadastradas no banco."""
    try:
        conn = psycopg2.connect(_dsn())
        cur = conn.cursor()
        cur.execute("""
            SELECT camera_id, ip::text, usuario, senha, nome
            FROM cameras
            WHERE ativa = TRUE
              AND modo_integracao = 'listen'
              AND ip IS NOT NULL
              AND usuario IS NOT NULL
              AND senha IS NOT NULL
        """)
        rows = cur.fetchall()
        cur.close()
        conn.close()
        return [
            {"camera_id": r[0], "ip": r[1], "usuario": r[2], "senha": r[3], "nome": r[4]}
            for r in rows
        ]
    except Exception as exc:
        log.error("Erro ao buscar câmeras no banco: %s", exc)
        return []


# ── Envio ao ingest ────────────────────────────────────────────────────────────

def _inject_ip_if_missing(xml_bytes: bytes, camera_ip: str) -> bytes:
    """Injeta <ipAddress> no XML se o campo estiver ausente."""
    try:
        if b"<ipAddress>" in xml_bytes:
            return xml_bytes  # já tem, não precisa injetar
        root = ET.fromstring(xml_bytes)
        ns = "http://www.isapi.org/ver20/XMLSchema"
        tag = f"{{{ns}}}ipAddress"
        if root.find(f".//{tag}") is None:
            el = ET.SubElement(root, tag)
            el.text = camera_ip
        return ET.tostring(root, encoding="unicode").encode()
    except Exception:
        return xml_bytes  # se falhar, retorna original sem modificação


def forward_to_ingest(xml_bytes: bytes, images: list[tuple[str, bytes]], camera_id: str, camera_ip: str = ""):
    """Envia o evento XML (+imagens opcionais) para /api/simple-webhook."""
    try:
        if camera_ip:
            xml_bytes = _inject_ip_if_missing(xml_bytes, camera_ip)

        files: list = [("file0", ("event.xml", xml_bytes, "application/xml"))]
        for i, (fname, data) in enumerate(images):
            files.append((f"image{i}", (fname, data, "image/jpeg")))

        headers = {}
        if camera_ip:
            headers["X-Camera-IP"] = camera_ip

        resp = requests.post(
            f"{INGEST_URL}/api/simple-webhook",
            files=files,
            headers=headers,
            timeout=15,
        )
        if resp.status_code == 200:
            result = resp.json()
            plate = result.get("plate", "?")
            log.info("[%s] Evento entregue ao ingest — placa: %s", camera_id, plate)
        else:
            log.warning("[%s] Ingest retornou %s: %s", camera_id, resp.status_code, resp.text[:200])
    except Exception as exc:
        log.error("[%s] Falha ao enviar para ingest: %s", camera_id, exc)


# ── Parser do multipart stream Hikvision ──────────────────────────────────────

def _extract_boundary(content_type: str) -> str | None:
    for part in content_type.split(";"):
        part = part.strip()
        if part.lower().startswith("boundary="):
            return part[9:].strip().strip('"')
    return None


def parse_alert_stream(response: requests.Response, camera_id: str, camera_ip: str = ""):
    """
    Lê o multipart stream ISAPI da câmera e encaminha eventos ANPR ao ingest.
    Agrupa XML + imagem(ns) do mesmo evento antes de encaminhar.
    Bloqueia até a conexão ser encerrada ou erro.
    """
    content_type = response.headers.get("content-type", "")
    boundary = _extract_boundary(content_type)

    if not boundary:
        log.warning("[%s] Boundary não encontrado no header, aguardando dados...", camera_id)

    buffer = b""
    boundary_bytes = f"--{boundary}".encode() if boundary else None

    # Estado do evento em curso (XML pendente aguardando imagem)
    pending_xml: bytes | None = None
    pending_images: list[tuple[str, bytes]] = []

    def _flush_pending():
        """Encaminha o evento pendente (XML + imagens coletadas até agora)."""
        nonlocal pending_xml, pending_images
        if pending_xml is not None:
            forward_to_ingest(pending_xml, pending_images, camera_id, camera_ip=camera_ip)
        pending_xml = None
        pending_images = []

    for chunk in response.iter_content(chunk_size=4096):
        if not chunk:
            continue
        buffer += chunk

        # Detectar boundary dinamicamente se não veio no header
        if boundary_bytes is None and b"--" in buffer:
            idx = buffer.index(b"--")
            end = buffer.find(b"\r\n", idx)
            if end != -1:
                boundary_bytes = buffer[idx:end]
                boundary = boundary_bytes[2:].decode(errors="ignore")
                log.info("[%s] Boundary detectado dinamicamente: %s", camera_id, boundary)

        if boundary_bytes is None:
            continue

        # Processar partes completas no buffer
        while boundary_bytes in buffer:
            idx = buffer.index(boundary_bytes)
            part = buffer[:idx]
            buffer = buffer[idx + len(boundary_bytes):]

            # Pula linhas vazias após boundary
            if part.strip() in (b"", b"--"):
                continue

            # Separar headers do corpo
            if b"\r\n\r\n" not in part:
                continue
            headers_raw, body = part.split(b"\r\n\r\n", 1)
            body = body.strip(b"\r\n")

            if not body:
                continue

            headers_lower = headers_raw.lower()

            # ── Parte XML ────────────────────────────────────────────────────
            if b"application/xml" in headers_lower or b"text/xml" in headers_lower:
                is_anpr = b"licensePlate" in body or b"ANPR" in body

                if is_anpr:
                    # Novo evento ANPR: envia o pendente anterior (se existir) e inicia novo
                    _flush_pending()
                    pending_xml = body
                    pending_images = []
                    log.debug("[%s] XML ANPR recebido (%d bytes) — aguardando imagem...", camera_id, len(body))
                else:
                    # XML sem placa (heartbeat, motion, etc.) — descarta pendente sem imagem
                    _flush_pending()

            # ── Parte imagem ─────────────────────────────────────────────────
            elif b"image/jpeg" in headers_lower or b"image/png" in headers_lower or b"image/" in headers_lower:
                if pending_xml is not None:
                    # Extrai nome do arquivo do Content-Disposition, se disponível
                    fname = "image.jpg"
                    for line in headers_raw.split(b"\r\n"):
                        if b"filename" in line.lower():
                            try:
                                fname = line.split(b"filename=")[1].strip().strip(b'"').decode(errors="ignore")
                            except Exception:
                                pass
                    pending_images.append((fname, body))
                    log.debug("[%s] Imagem associada ao evento (%d bytes)", camera_id, len(body))
                    # Hikvision normalmente envia 1 imagem por evento — encaminha imediatamente
                    _flush_pending()
                else:
                    log.debug("[%s] Imagem recebida sem XML par — descartada (%d bytes)", camera_id, len(body))


# ── Worker por câmera ──────────────────────────────────────────────────────────

def camera_worker(cam: dict):
    """
    Thread dedicada a uma câmera em modo escuta.
    Reconecta automaticamente ao ISAPI Alert Stream.
    """
    camera_id = cam["camera_id"]
    ip        = cam["ip"]
    usuario   = cam["usuario"]
    senha     = cam["senha"]

    stream_url = f"http://{ip}/ISAPI/Event/notification/alertStream"
    log.info("[%s] Worker iniciado → %s", camera_id, stream_url)

    while True:
        try:
            # Tenta Digest Auth primeiro (padrão Hikvision moderno)
            for auth in (HTTPDigestAuth(usuario, senha), HTTPBasicAuth(usuario, senha)):
                resp = requests.get(
                    stream_url,
                    auth=auth,
                    stream=True,
                    timeout=(10, None),   # 10s connect, sem timeout de leitura
                    headers={"Accept": "multipart/mixed"},
                )
                if resp.status_code == 401:
                    log.debug("[%s] Auth %s recusada, tentando próxima...", camera_id, type(auth).__name__)
                    continue
                break

            if resp.status_code == 200:
                log.info("[%s] Stream ISAPI conectado (HTTP 200)", camera_id)
                parse_alert_stream(resp, camera_id, camera_ip=ip)
                log.warning("[%s] Stream encerrado pela câmera", camera_id)
            elif resp.status_code == 401:
                log.error("[%s] Autenticação falhou (401) — verifique usuário/senha", camera_id)
                time.sleep(60)  # Espera mais antes de tentar de novo
            elif resp.status_code == 404:
                log.error("[%s] Endpoint não encontrado (404) — câmera pode não suportar alertStream", camera_id)
                time.sleep(120)
            else:
                log.warning("[%s] HTTP %s ao conectar stream", camera_id, resp.status_code)

        except requests.exceptions.ConnectTimeout:
            log.warning("[%s] Timeout de conexão para %s", camera_id, ip)
        except requests.exceptions.ConnectionError as exc:
            log.warning("[%s] Erro de conexão: %s", camera_id, exc)
        except Exception as exc:
            log.error("[%s] Erro inesperado: %s", camera_id, exc)

        log.info("[%s] Reconectando em %ds...", camera_id, RECONNECT_DELAY)
        time.sleep(RECONNECT_DELAY)


# ── Loop principal ─────────────────────────────────────────────────────────────

def main():
    log.warning("camera-poller legado: ambiente atual opera apenas em push.")
    log.info("=" * 60)
    log.info("Camera Poller iniciando")
    log.info("  INGEST_URL      : %s", INGEST_URL)
    log.info("  DB_HOST         : %s", DB_HOST)
    log.info("  RECONNECT_DELAY : %ds", RECONNECT_DELAY)
    log.info("  REFRESH_INTERVAL: %ds", REFRESH_INTERVAL)
    log.info("=" * 60)

    # Aguarda banco e ingest subirem
    log.info("Aguardando serviços ficarem prontos (15s)...")
    time.sleep(15)

    active_threads: dict[str, threading.Thread] = {}

    while True:
        cameras = get_listen_cameras()

        if cameras:
            log.info("Câmeras em modo listen encontradas: %d", len(cameras))
        else:
            log.info("Nenhuma câmera em modo listen configurada. Aguardando...")

        for cam in cameras:
            key = cam["camera_id"]
            existing = active_threads.get(key)
            if existing and existing.is_alive():
                continue  # já rodando

            log.info("Iniciando worker para câmera '%s' (%s)", cam["nome"], cam["ip"])
            t = threading.Thread(
                target=camera_worker,
                args=(cam,),
                daemon=True,
                name=f"poller-{key}",
            )
            t.start()
            active_threads[key] = t

        # Limpa threads mortas do dicionário
        active_threads = {k: v for k, v in active_threads.items() if v.is_alive()}

        time.sleep(REFRESH_INTERVAL)


if __name__ == "__main__":
    main()
