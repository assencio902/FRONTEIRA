"""
yolo-worker / worker.py
Processa imagens com YOLOv8 e salva resultados no banco + JSON ao lado da imagem.
Enfileirado pelo serviço ingest via RQ.

Análises disponíveis:
  - Detecção de veículos/pessoas (COCO)
  - Cor dominante do veículo (análise HSV)
  - Qualidade geral da imagem (blur, brilho, contraste)
  - Qualidade da região da placa (blur no terço inferior do veículo)
  - Motivo da falha de leitura de placa (sem_placa_motivo)
"""
import json
import os
import traceback
from pathlib import Path

import psycopg2

# Classes COCO relevantes para veículos
VEHICLE_CLASSES = {
    2:  "car",
    3:  "motorcycle",
    5:  "bus",
    7:  "truck",
    1:  "bicycle",
    0:  "person",
}

# Mapa de classe para nome em português
VEHICLE_CLASS_PT = {
    "car":        "Carro",
    "motorcycle": "Moto",
    "bus":        "Ônibus",
    "truck":      "Caminhão",
    "bicycle":    "Bicicleta",
    "person":     "Pessoa",
}

IMAGES_DIR = Path(os.getenv("IMAGES_DIR", "/app/uploads"))
MODEL_PATH  = os.getenv("YOLO_MODEL", "yolov8n.pt")
CONFIDENCE  = float(os.getenv("YOLO_CONF", "0.35"))

# Limiares de blur (variância do Laplaciano). Abaixo = desfocado.
BLUR_THRESHOLD_GERAL = float(os.getenv("BLUR_THRESHOLD_GERAL", "60.0"))
BLUR_THRESHOLD_PLACA = float(os.getenv("BLUR_THRESHOLD_PLACA", "30.0"))
# Limiares de brilho (0-255)
BRIGHTNESS_MIN = 40
BRIGHTNESS_MAX = 220

# Modelo carregado uma única vez no processo worker (fica na memória entre jobs)
_model = None

def _get_model():
    global _model
    if _model is None:
        from ultralytics import YOLO
        _model = YOLO(MODEL_PATH)
        print(f"[YOLO] Modelo carregado: {MODEL_PATH}", flush=True)
    return _model


# ---------------------------------------------------------------------------
# Funções de análise de imagem
# ---------------------------------------------------------------------------

def _laplacian_blur_score(gray_crop) -> float:
    """Retorna a variância do Laplaciano — quanto menor, mais desfocado."""
    import cv2
    lap = cv2.Laplacian(gray_crop, cv2.CV_64F)
    return float(lap.var())


def _analyze_image_quality(img_bgr) -> dict:
    """
    Analisa qualidade geral da imagem.
    Retorna: blur_score, brightness, contrast, qualidade (str em português).
    """
    import cv2
    import numpy as np

    gray       = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2GRAY)
    blur_score = round(_laplacian_blur_score(gray), 2)
    brightness = round(float(np.mean(gray)), 2)
    contrast   = round(float(np.std(gray)), 2)

    problemas = []
    if blur_score < BLUR_THRESHOLD_GERAL:
        problemas.append("desfocada")
    if brightness < BRIGHTNESS_MIN:
        problemas.append("muito escura")
    elif brightness > BRIGHTNESS_MAX:
        problemas.append("superexposta")

    qualidade = "Boa" if not problemas else "Ruim (" + ", ".join(problemas) + ")"
    return {"blur_score": blur_score, "brightness": brightness,
            "contrast": contrast, "qualidade": qualidade}


def _analyze_plate_region(img_bgr, xyxy: list) -> dict:
    """
    Analisa o terço inferior do bounding box do veículo (região provável da placa).
    Retorna blur_score, brightness e qualidade da placa.
    """
    import cv2
    import numpy as np

    h_img, w_img = img_bgr.shape[:2]
    x1, y1, x2, y2 = [int(v) for v in xyxy]
    x1, x2 = max(0, x1), min(w_img, x2)
    y1, y2 = max(0, y1), min(h_img, y2)

    altura   = y2 - y1
    plate_y1 = y1 + int(altura * 0.60)
    crop     = img_bgr[plate_y1:y2, x1:x2]

    if crop.size == 0:
        return {"blur_score": 0.0, "brightness": 0.0, "qualidade": "Região inválida"}

    gray       = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
    blur_score = round(_laplacian_blur_score(gray), 2)
    brightness = round(float(np.mean(gray)), 2)

    problemas = []
    if blur_score < BLUR_THRESHOLD_PLACA:
        problemas.append("região desfocada")
    if brightness < BRIGHTNESS_MIN:
        problemas.append("região muito escura")
    elif brightness > BRIGHTNESS_MAX:
        problemas.append("região superexposta")

    qualidade = "Legível" if not problemas else "Ilegível (" + ", ".join(problemas) + ")"
    return {"blur_score": blur_score, "brightness": brightness, "qualidade": qualidade}


# Tabela HSV → cor em português (valores em escala OpenCV: H=0-179, S/V=0-255)
# Formato: (nome, h_min, h_max, s_min, v_min)
_COR_RANGES = [
    ("Vermelho",  0,   10, 45, 30),
    ("Laranja",  10,   25, 45, 35),
    ("Amarelo",  25,   35, 45, 40),
    ("Verde",    35,   85, 35, 30),
    ("Azul",     85,  130, 35, 30),
    ("Roxo",    130,  165, 35, 30),
    ("Vermelho",165,  180, 45, 30),  # wraparound vermelho
]

def _hsv_to_color_name(h: int, s: int, v: int) -> str:
    # Preto: somente quando há pouca luz e baixa saturação (carros coloridos escuros ficam fora)
    if v < 45 and s < 80:
        return "Preto"
    # Branco: brilho alto com saturação bem baixa
    if s < 45 and v > 185:
        return "Branco"
    # Prata / Cinza: saturação baixa em qualquer nível de brilho
    if s < 70:
        return "Prata/Cinza"
    # Cores saturadas — busca na tabela de faixas
    for nome, h_min, h_max, s_min, v_min in _COR_RANGES:
        if h_min <= h <= h_max and s >= s_min and v >= v_min:
            return nome
    # Fallback: tons residuais tratados como cinza
    return "Prata/Cinza"


def _detect_vehicle_color(img_bgr, xyxy: list) -> str:
    """
    Detecta a cor dominante do veículo analisando o trecho médio da carroceria
    (evita capô e pneus) usando análise HSV.
    """
    import cv2
    from collections import Counter

    h_img, w_img = img_bgr.shape[:2]
    x1, y1, x2, y2 = [int(v) for v in xyxy]
    x1, x2 = max(0, x1), min(w_img, x2)
    y1, y2 = max(0, y1), min(h_img, y2)

    altura   = y2 - y1
    crop_y1  = y1 + int(altura * 0.20)
    crop_y2  = y1 + int(altura * 0.65)
    crop     = img_bgr[crop_y1:crop_y2, x1:x2]

    if crop.size == 0:
        return "Indeterminada"

    small  = cv2.resize(crop, (32, 32), interpolation=cv2.INTER_AREA)
    hsv    = cv2.cvtColor(small, cv2.COLOR_BGR2HSV)
    pixels = hsv.reshape(-1, 3)

    cores     = [_hsv_to_color_name(int(p[0]), int(p[1]), int(p[2])) for p in pixels]
    contador  = Counter(cores)
    dominante, _ = contador.most_common(1)[0]
    return dominante


def _compute_sem_placa_motivo(output: dict, plate_raw: str) -> "str | None":
    """
    Determina o motivo pelo qual a placa não foi lida.
    Retorna None se a placa foi lida com sucesso.
    """
    plate_ausente = not plate_raw or plate_raw.strip().lower() in ("", "unknown", "none")
    if not plate_ausente:
        return None

    iq         = output.get("image_quality", {})
    blur_geral = iq.get("blur_score", 999)
    bright     = iq.get("brightness", 128)

    if blur_geral < BLUR_THRESHOLD_GERAL:
        return f"Imagem desfocada (blur={blur_geral:.1f})"
    if bright < BRIGHTNESS_MIN:
        return f"Iluminação insuficiente (brilho={bright:.0f})"
    if bright > BRIGHTNESS_MAX:
        return f"Imagem superexposta (brilho={bright:.0f})"

    vcount = output.get("vehicle_count", 0)
    if vcount == 0:
        return "Nenhum veículo identificado na imagem"
    if vcount > 1:
        tipos    = list(output.get("vehicle_types", {}).keys())
        tipos_pt = [VEHICLE_CLASS_PT.get(t, t) for t in tipos]
        return f"Múltiplos veículos na cena ({', '.join(tipos_pt)})"

    # Checar qualidade da região da placa no primeiro veículo
    veiculos = output.get("vehicle_details", [])
    if veiculos:
        pq    = veiculos[0].get("plate_analysis", {})
        pblur = pq.get("blur_score", 999)
        pbright = pq.get("brightness", 128)
        if pblur < BLUR_THRESHOLD_PLACA:
            return f"Placa ilegível — região desfocada (blur={pblur:.1f})"
        if pbright < BRIGHTNESS_MIN:
            return "Placa ilegível — região muito escura"

    return "Placa não localizada na imagem"


# ---------------------------------------------------------------------------
# Banco de dados
# ---------------------------------------------------------------------------

def _update_db(image_path: str, result: dict) -> bool:
    """Salva yolo_result no banco buscando pelo image_path relativo."""
    try:
        # Converte caminho absoluto de volta para relativo (uploads/YYYY-MM-DD/file.jpg)
        p = Path(image_path)
        parts = p.parts
        try:
            uploads_idx = next(i for i, x in enumerate(parts) if x == "uploads")
            # O banco armazena sempre com '/' no início: /uploads/YYYY-MM-DD/file.jpg
            rel_path = "/" + "/".join(parts[uploads_idx:])
        except StopIteration:
            rel_path = image_path

        conn = psycopg2.connect(
            host=os.getenv("POSTGRES_HOST", "postgres"),
            port=os.getenv("POSTGRES_PORT", "5432"),
            dbname=os.getenv("POSTGRES_DB", "monitor"),
            user=os.getenv("POSTGRES_USER", "monitor_user"),
            password=os.getenv("POSTGRES_PASSWORD", "monitor_pass"),
        )
        with conn:
            with conn.cursor() as cur:
                cur.execute(
                    "UPDATE lpr_events SET yolo_result = %s WHERE image_path = %s",
                    (json.dumps(result), rel_path)
                )
                updated = cur.rowcount
        conn.close()
        if updated:
            print(f"[YOLO] DB atualizado: {rel_path}", flush=True)
        else:
            print(f"[YOLO] DB: nenhuma linha com image_path={rel_path}", flush=True)
        return updated > 0
    except Exception as e:
        print(f"[YOLO][DB_ERRO] {e}", flush=True)
        return False


def job_analyze_event(image_path: str, plate_raw: str = "") -> dict:
    """
    Recebe o caminho da imagem e a placa bruta do LPR (opcional).
    Roda YOLOv8 + análises complementares e retorna dict com:
      - vehicle_count        (int)
      - vehicle_types        (dict {class_name: count})
      - person_count         (int)
      - detections           (list de {class, conf, xyxy})
      - vehicle_details      (list com tipo_pt, cor, plate_analysis por veículo)
      - image_quality        (blur_score, brightness, contrast, qualidade)
      - sem_placa_motivo     (str com motivo ou null se placa foi lida)
      - model, conf_threshold
    Também salva um .yolo.json ao lado da imagem e atualiza o banco.
    """
    print(f"[YOLO] Job iniciado: {image_path}", flush=True)

    p = Path(image_path)
    if not p.is_absolute():
        p = IMAGES_DIR / image_path

    if not p.exists():
        msg = f"Imagem nao encontrada: {p}"
        print(f"[YOLO][ERRO] {msg}", flush=True)
        return {"error": msg, "image_path": image_path}

    try:
        import cv2

        img_bgr = cv2.imread(str(p))
        if img_bgr is None:
            return {"error": "Falha ao abrir imagem com OpenCV", "image_path": image_path}

        # ── Qualidade geral da imagem ──────────────────────────────────────
        image_quality = _analyze_image_quality(img_bgr)

        # ── Detecção YOLO ──────────────────────────────────────────────────
        model   = _get_model()
        results = model.predict(source=str(p), conf=CONFIDENCE, verbose=False)
        result  = results[0]

        detections      = []
        vehicle_types   = {}
        vehicle_count   = 0
        person_count    = 0
        vehicle_details = []

        boxes = result.boxes
        for box in boxes:
            cls_id   = int(box.cls[0])
            conf_val = float(box.conf[0])
            xyxy     = [round(float(x), 1) for x in box.xyxy[0].tolist()]
            cls_name = result.names.get(cls_id, str(cls_id))

            detections.append({
                "class":    cls_name,
                "class_id": cls_id,
                "conf":     round(conf_val, 4),
                "xyxy":     xyxy,
            })

            if cls_id in VEHICLE_CLASSES and cls_id != 0:
                vehicle_count += 1
                vehicle_types[cls_name] = vehicle_types.get(cls_name, 0) + 1

                cor            = _detect_vehicle_color(img_bgr, xyxy)
                plate_analysis = _analyze_plate_region(img_bgr, xyxy)

                vehicle_details.append({
                    "class":          cls_name,
                    "class_pt":       VEHICLE_CLASS_PT.get(cls_name, cls_name),
                    "conf":           round(conf_val, 4),
                    "cor":            cor,
                    "plate_analysis": plate_analysis,
                    "xyxy":           xyxy,
                })

            if cls_id == 0:
                person_count += 1

        # ── Motivo de falha na leitura da placa ───────────────────────────
        sem_placa_motivo = _compute_sem_placa_motivo(
            {
                "image_quality":   image_quality,
                "vehicle_count":   vehicle_count,
                "vehicle_types":   vehicle_types,
                "vehicle_details": vehicle_details,
            },
            plate_raw,
        )

        output = {
            "image_path":       image_path,
            "vehicle_count":    vehicle_count,
            "vehicle_types":    vehicle_types,
            "person_count":     person_count,
            "detections":       detections,
            "vehicle_details":  vehicle_details,
            "image_quality":    image_quality,
            "sem_placa_motivo": sem_placa_motivo,
            "model":            MODEL_PATH,
            "conf_threshold":   CONFIDENCE,
        }

        # ── Salvar JSON ao lado da imagem ─────────────────────────────────
        json_path = p.with_suffix(".yolo.json")
        json_path.write_text(json.dumps(output, ensure_ascii=False, indent=2))

        cor_str    = vehicle_details[0]["cor"] if vehicle_details else "-"
        motivo_str = f" | motivo={sem_placa_motivo}" if sem_placa_motivo else ""
        print(
            f"[YOLO] OK — {vehicle_count} veic (cor={cor_str}), "
            f"{person_count} pessoa(s), blur={image_quality['blur_score']}"
            f"{motivo_str} — {json_path.name}",
            flush=True,
        )

        _update_db(image_path, output)
        return output

    except Exception as exc:
        tb = traceback.format_exc()
        print(f"[YOLO][ERRO] {exc}\n{tb}", flush=True)
        return {"error": str(exc), "image_path": image_path}
