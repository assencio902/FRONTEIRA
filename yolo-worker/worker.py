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
    "van":        "Van/Kombi",
    "truck":      "Caminhão",
    "pickup":     "Caminhonete",
    "bicycle":    "Bicicleta",
    "person":     "Pessoa",
}

# Limites de fração da altura da imagem para distinguir caminhonete de caminhão
# Caminhões grandes e ônibus ocupam mais da imagem verticalmente
PICKUP_MAX_HEIGHT_FRAC = float(os.getenv("PICKUP_MAX_HEIGHT_FRAC", "0.45"))
PICKUP_MAX_AREA_FRAC   = float(os.getenv("PICKUP_MAX_AREA_FRAC",   "0.28"))
# Limites para distinguir van/kombi de ônibus real
VAN_MAX_HEIGHT_FRAC    = float(os.getenv("VAN_MAX_HEIGHT_FRAC",    "0.40"))
VAN_MAX_AREA_FRAC      = float(os.getenv("VAN_MAX_AREA_FRAC",      "0.20"))


def _normalize_rect(rect: dict, img_w: int, img_h: int,
                    pic_w: int = 10000, pic_h: int = 10000) -> list:
    """
    Converte rect normalizado (0-picW x 0-picH) Hikvision para pixels reais.
    Retorna [x1, y1, x2, y2] em pixels da imagem.
    Hikvision usa coordenadas 0-10000 por padrão.
    """
    x1 = int(rect["x"] / pic_w * img_w)
    y1 = int(rect["y"] / pic_h * img_h)
    x2 = int((rect["x"] + rect["w"]) / pic_w * img_w)
    y2 = int((rect["y"] + rect["h"]) / pic_h * img_h)
    return [max(0, x1), max(0, y1), min(img_w, x2), min(img_h, y2)]


def _iou(boxA: list, boxB: list) -> float:
    """Intersection over Union entre dois bounding boxes [x1,y1,x2,y2]."""
    xA = max(boxA[0], boxB[0])
    yA = max(boxA[1], boxB[1])
    xB = min(boxA[2], boxB[2])
    yB = min(boxA[3], boxB[3])
    inter = max(0, xB - xA) * max(0, yB - yA)
    if inter == 0:
        return 0.0
    areaA = (boxA[2]-boxA[0]) * (boxA[3]-boxA[1])
    areaB = (boxB[2]-boxB[0]) * (boxB[3]-boxB[1])
    return inter / (areaA + areaB - inter)


def _find_target_vehicle(vehicle_details: list, lpr_meta: dict,
                         img_w: int, img_h: int) -> "dict | None":
    """
    Identifica qual veículo detectado corresponde à placa lida.
    Estratégias (por prioridade):
      1. vehicleRect do XML  → maior IoU com bbox YOLO
      2. plateRect do XML    → bbox YOLO que contém o centro da placa
      3. Fallback             → maior bbox (mais próximo da câmera = veículo principal)
    """
    if not vehicle_details:
        return None

    pic_w = lpr_meta.get("pic_size", {}).get("w", 10000)
    pic_h = lpr_meta.get("pic_size", {}).get("h", 10000)

    # 1. vehicleRect → IoU direto com YOLO
    vrect = lpr_meta.get("vehicle_rect")
    if vrect:
        ref = _normalize_rect(vrect, img_w, img_h, pic_w, pic_h)
        best = max(vehicle_details, key=lambda v: _iou(v["xyxy"], ref))
        if _iou(best["xyxy"], ref) > 0.10:  # IoU mínimo
            return best

    # 2. plateRect → qual bbox YOLO contém o centro da placa
    prect = lpr_meta.get("plate_rect")
    if prect:
        # Centro da placa em pixels
        cx = int((prect["x"] + prect["w"] / 2) / pic_w * img_w)
        cy = int((prect["y"] + prect["h"] / 2) / pic_h * img_h)
        for v in vehicle_details:
            x1, y1, x2, y2 = v["xyxy"]
            if x1 <= cx <= x2 and y1 <= cy <= y2:
                return v
        # Nenhum contém o centro → mais próximo
        best = min(vehicle_details, key=lambda v: (
            (((v["xyxy"][0]+v["xyxy"][2])/2 - cx)**2 +
             ((v["xyxy"][1]+v["xyxy"][3])/2 - cy)**2) ** 0.5
        ))
        return best

    # 3. Fallback: maior área (veículo dominante da cena)
    return max(vehicle_details, key=lambda v: (
        (v["xyxy"][2]-v["xyxy"][0]) * (v["xyxy"][3]-v["xyxy"][1])
    ))


def _classify_truck_subtype(xyxy: list, img_bgr) -> str:
    """
    Distingue caminhonete de caminhão com base no tamanho relativo do bounding
    box em relação à imagem. Caminhonetes são menores que caminhões grandes.
    Retorna 'pickup' ou 'truck'.
    """
    h_img, w_img = img_bgr.shape[:2]
    x1, y1, x2, y2 = [int(v) for v in xyxy]
    altura_box  = y2 - y1
    largura_box = x2 - x1
    frac_altura = altura_box / h_img
    area_relat  = (altura_box * largura_box) / (h_img * w_img)
    if frac_altura < PICKUP_MAX_HEIGHT_FRAC and area_relat < PICKUP_MAX_AREA_FRAC:
        return "pickup"
    return "truck"


def _classify_bus_subtype(xyxy: list, img_bgr) -> str:
    """
    Distingue Van/Kombi de ônibus real com base no tamanho do bounding box.
    Kombis e vans são menores que ônibus rodoviários/urbanos.
    Retorna 'van' ou 'bus'.
    """
    h_img, w_img = img_bgr.shape[:2]
    x1, y1, x2, y2 = [int(v) for v in xyxy]
    frac_altura = (y2 - y1) / h_img
    area_relat  = ((y2 - y1) * (x2 - x1)) / (h_img * w_img)
    if frac_altura < VAN_MAX_HEIGHT_FRAC and area_relat < VAN_MAX_AREA_FRAC:
        return "van"
    return "bus"

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


# ── Tabela de cores (Lab d65) — centro aproximado em BGR para mapeamento ──────────
# Mapeamos os centros dos clusters K-means de volta para cor usando distância no espaço HSV.
_COR_RANGES = [
    # (nome,    h_min, h_max, s_min, s_max, v_min, v_max)
    ("Vermelho",  0,   10,  25, 255,  30, 255),
    ("Laranja",  10,   22,  25, 255,  40, 255),
    ("Amarelo",  22,   35,  25, 255,  50, 255),
    ("Verde",    35,   85,  22, 255,  25, 255),
    ("Azul",     85,  130,  22, 255,  25, 255),
    ("Roxo",    130,  165,  22, 255,  25, 255),
    ("Vermelho",165,  180,  25, 255,  30, 255),  # wraparound
]


def _hsv_cluster_to_name(h: float, s: float, v: float) -> "str | None":
    """
    Mapeia um cluster HSV (float OpenCV: H 0-179, S/V 0-255) para nome de cor.
    Retorna None se o cluster for fundo (asfalto, céu, sombra profunda).
    """
    # Descarta fundo: pixels muito escuros (asfalto/sombra interna do carro)
    if v < 35:
        return None
    # Descarta fundo: saturasão muito alta + brilho alto = ceu/superexposto
    # (raro, mas evita confundir iluminação com cor do veículo)

    # Preto genuino: escuro e dessaturado
    if v < 70 and s < 40:
        return "Preto"
    # Branco: muito brilhante e dessaturado
    if s < 35 and v > 175:
        return "Branco"
    # Prata/Cinza: dessaturado em qualquer brilho intermediário
    if s < 45:
        return "Prata/Cinza"
    # Cores saturadas
    for nome, h_min, h_max, s_min, s_max, v_min, v_max in _COR_RANGES:
        if h_min <= h <= h_max and s_min <= s <= s_max and v_min <= v <= v_max:
            return nome
    # Residual dessaturado
    return "Prata/Cinza"


def _detect_vehicle_color(img_bgr, xyxy: list) -> str:
    """
    Detecta a cor dominante do veículo usando K-means no espaço HSV.
    Foca no corpo do veículo (evita capô reflexivo, pneus e fundo).
    """
    import cv2
    import numpy as np

    h_img, w_img = img_bgr.shape[:2]
    x1, y1, x2, y2 = [int(v) for v in xyxy]
    x1, x2 = max(0, x1), min(w_img, x2)
    y1, y2 = max(0, y1), min(h_img, y2)

    altura  = y2 - y1
    largura = x2 - x1
    if altura < 10 or largura < 10:
        return "Indeterminada"

    # Corpo do veículo: evita capô (top 18%), pneus/placa (bottom 22%), bordas (10%)
    crop = img_bgr[
        y1 + int(altura  * 0.18) : y1 + int(altura  * 0.78),
        x1 + int(largura * 0.10) : x2 - int(largura * 0.10),
    ]
    if crop.size == 0:
        return "Indeterminada"

    # Redimensiona para 80×80 — bom equilíbrio entre velocidade e representação
    small = cv2.resize(crop, (80, 80), interpolation=cv2.INTER_AREA)
    hsv   = cv2.cvtColor(small, cv2.COLOR_BGR2HSV).reshape(-1, 3).astype(np.float32)

    # Remove pixels muito escuros (sombra/asfalto visível) antes do K-means
    mask = hsv[:, 2] > 30
    hsv_f = hsv[mask]
    if len(hsv_f) < 20:
        return "Preto"

    # K-means com k=4 clusters — boa cobertura sem over-split
    K = 4
    criteria = (cv2.TERM_CRITERIA_EPS + cv2.TERM_CRITERIA_MAX_ITER, 15, 1.0)
    try:
        _, labels, centers = cv2.kmeans(
            hsv_f, K, None, criteria, attempts=3,
            flags=cv2.KMEANS_PP_CENTERS,
        )
    except Exception:
        return "Indeterminada"

    # Conta pixels por cluster e ordena por tamanho
    counts  = np.bincount(labels.flatten(), minlength=K)
    total   = counts.sum()
    ordered = sorted(zip(counts, centers), key=lambda x: -x[0])

    # Tenta identificar uma cor não-fundo suficientemente dominante
    for count, center in ordered:
        if count / total < 0.12:   # cluster com < 12% dos pixels — descarta
            continue
        h, s, v = float(center[0]), float(center[1]), float(center[2])
        nome = _hsv_cluster_to_name(h, s, v)
        if nome is not None:
            return nome

    return "Indeterminada"


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


def job_analyze_event(image_path: str, plate_raw: str = "",
                      lpr_meta: "dict | None" = None) -> dict:
    """
    Recebe o caminho da imagem, a placa bruta e metadados LPR (plate_rect, vehicle_rect).
    Foca a análise YOLO no veículo que corresponde à placa detectada.
    Retorna dict com vehicle_count, vehicle_types, vehicle_details, target_vehicle,
    image_quality, sem_placa_motivo, model, conf_threshold.
    Também salva um .yolo.json ao lado da imagem e atualiza o banco.
    """
    print(f"[YOLO] Job iniciado: {image_path} | plate={plate_raw or '?'} | meta={bool(lpr_meta)}", flush=True)

    lpr_meta = lpr_meta or {}

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
        img_h, img_w  = img_bgr.shape[:2]

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

                # Refina tipo via heurísticas de tamanho do bounding box
                effective_class = cls_name
                if cls_name == "truck":
                    effective_class = _classify_truck_subtype(xyxy, img_bgr)
                elif cls_name == "bus":
                    effective_class = _classify_bus_subtype(xyxy, img_bgr)

                vehicle_types[effective_class] = vehicle_types.get(effective_class, 0) + 1

                # Cor e análise de placa somente para o veículo-alvo (feito abaixo)
                vehicle_details.append({
                    "class":          effective_class,
                    "class_pt":       VEHICLE_CLASS_PT.get(effective_class, effective_class),
                    "conf":           round(conf_val, 4),
                    "cor":            None,
                    "plate_analysis": None,
                    "xyxy":           xyxy,
                })

            if cls_id == 0:
                person_count += 1

        # ── Identifica o veículo da placa ─────────────────────────────────
        target_vehicle = _find_target_vehicle(vehicle_details, lpr_meta, img_w, img_h)

        # Análise profunda somente no veículo-alvo (cor + região da placa)
        if target_vehicle is not None:
            target_vehicle["cor"]            = _detect_vehicle_color(img_bgr, target_vehicle["xyxy"])
            target_vehicle["plate_analysis"] = _analyze_plate_region(img_bgr, target_vehicle["xyxy"])

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
            "image_path":        image_path,
            "vehicle_count":     vehicle_count,
            "vehicle_types":     vehicle_types,
            "person_count":      person_count,
            "detections":        detections,
            "vehicle_details":   vehicle_details,
            "target_vehicle":    target_vehicle,   # veículo da placa
            "image_quality":     image_quality,
            "sem_placa_motivo":  sem_placa_motivo,
            "model":             MODEL_PATH,
            "conf_threshold":    CONFIDENCE,
        }

        # ── Salvar JSON ao lado da imagem ─────────────────────────────────
        json_path = p.with_suffix(".yolo.json")
        json_path.write_text(json.dumps(output, ensure_ascii=False, indent=2))

        tv             = target_vehicle or (vehicle_details[0] if vehicle_details else None)
        cor_str        = tv["cor"]     if tv else "-"
        tipo_str       = tv["class_pt"] if tv else "-"
        motivo_str     = f" | motivo={sem_placa_motivo}" if sem_placa_motivo else ""
        print(
            f"[YOLO] OK — {vehicle_count} veic | alvo: {tipo_str} cor={cor_str} | "
            f"{person_count} pessoa(s) | blur={image_quality['blur_score']}"
            f"{motivo_str} — {json_path.name}",
            flush=True,
        )

        _update_db(image_path, output)
        return output

    except Exception as exc:
        tb = traceback.format_exc()
        print(f"[YOLO][ERRO] {exc}\n{tb}", flush=True)
        return {"error": str(exc), "image_path": image_path}
