"""
yolo-worker / worker.py
Processa imagens com YOLOv8 e salva resultados no banco + JSON ao lado da imagem.
Enfileirado pelo serviço ingest via RQ.
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

IMAGES_DIR = Path(os.getenv("IMAGES_DIR", "/app/uploads"))
MODEL_PATH  = os.getenv("YOLO_MODEL", "yolov8n.pt")
CONFIDENCE  = float(os.getenv("YOLO_CONF", "0.35"))

# Modelo carregado uma única vez no processo worker (fica na memória entre jobs)
_model = None

def _get_model():
    global _model
    if _model is None:
        from ultralytics import YOLO
        _model = YOLO(MODEL_PATH)
        print(f"[YOLO] Modelo carregado: {MODEL_PATH}", flush=True)
    return _model


def _update_db(image_path: str, result: dict) -> bool:
    """Salva yolo_result no banco buscando pelo image_path relativo."""
    try:
        # Converte caminho absoluto de volta para relativo (uploads/YYYY-MM-DD/file.jpg)
        p = Path(image_path)
        parts = p.parts
        try:
            uploads_idx = next(i for i, x in enumerate(parts) if x == "uploads")
            rel_path = "/".join(parts[uploads_idx:])
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


def job_analyze_event(image_path: str) -> dict:
    """
    Recebe o caminho relativo à IMAGES_DIR (ex: "uploads/2026-02-21/img.jpg")
    ou absoluto. Roda YOLOv8 e retorna dict com:
      - vehicle_count  (int)
      - vehicle_types  (dict {class_name: count})
      - person_count   (int)
      - detections     (list de {class, conf, xyxy})
      - image_path     (str, o mesmo recebido)
    Também salva um .json ao lado da imagem.
    """
    print(f"[YOLO] Job iniciado: {image_path}", flush=True)

    # Resolver caminho absoluto
    p = Path(image_path)
    if not p.is_absolute():
        p = IMAGES_DIR / image_path

    if not p.exists():
        msg = f"Imagem nao encontrada: {p}"
        print(f"[YOLO][ERRO] {msg}", flush=True)
        return {"error": msg, "image_path": image_path}

    try:
        model = _get_model()
        results = model.predict(source=str(p), conf=CONFIDENCE, verbose=False)
        result  = results[0]

        detections      = []
        vehicle_types   = {}
        vehicle_count   = 0
        person_count    = 0

        boxes = result.boxes
        for box in boxes:
            cls_id   = int(box.cls[0])
            conf_val = float(box.conf[0])
            xyxy     = [round(float(x), 1) for x in box.xyxy[0].tolist()]
            cls_name = result.names.get(cls_id, str(cls_id))

            detections.append({
                "class": cls_name,
                "class_id": cls_id,
                "conf": round(conf_val, 4),
                "xyxy": xyxy,
            })

            if cls_id in VEHICLE_CLASSES and cls_id != 0:
                vehicle_count += 1
                vehicle_types[cls_name] = vehicle_types.get(cls_name, 0) + 1
            if cls_id == 0:
                person_count += 1

        output = {
            "image_path":    image_path,
            "vehicle_count": vehicle_count,
            "vehicle_types": vehicle_types,
            "person_count":  person_count,
            "detections":    detections,
            "model":         MODEL_PATH,
            "conf_threshold": CONFIDENCE,
        }

        # Salvar JSON ao lado da imagem: <nome>.yolo.json
        json_path = p.with_suffix(".yolo.json")
        json_path.write_text(json.dumps(output, ensure_ascii=False, indent=2))
        print(f"[YOLO] OK — {vehicle_count} veic, {person_count} pessoa(s) — {json_path.name}", flush=True)

        # Salvar no banco de dados
        _update_db(image_path, output)

        return output

    except Exception as exc:
        tb = traceback.format_exc()
        print(f"[YOLO][ERRO] {exc}\n{tb}", flush=True)
        return {"error": str(exc), "image_path": image_path}
