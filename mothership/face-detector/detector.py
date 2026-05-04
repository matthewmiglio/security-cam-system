"""
Face detector sidecar for Frigate NVR.

Polls Frigate's REST API for new person events, runs YuNet on each snapshot,
crops detected faces, and saves them to disk for later classification.

Storage layout:
  /media/frigate/faces/YYYY-MM-DD/
    {camera}__{event_id}__{timestamp}__face{n}.jpg
    {camera}__{event_id}__{timestamp}__face{n}.json

Config via environment variables:
  FRIGATE_URL      Base URL for Frigate API  (default: http://frigate:8971)
  POLL_INTERVAL    Seconds between polls     (default: 8)
  MIN_FACE_SCORE   YuNet confidence cutoff   (default: 0.6)
  FACE_PADDING     Fractional bbox padding   (default: 0.2)
"""

import json
import logging
import os
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

import cv2
import numpy as np

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

FRIGATE_URL   = os.environ.get("FRIGATE_URL", "http://frigate:8971")
POLL_INTERVAL = int(os.environ.get("POLL_INTERVAL", "8"))
MIN_SCORE     = float(os.environ.get("MIN_FACE_SCORE", "0.6"))
FACE_PADDING  = float(os.environ.get("FACE_PADDING", "0.2"))

FACES_ROOT  = Path("/media/frigate/faces")
STATE_FILE  = FACES_ROOT / ".state.json"
MODEL_URL   = (
    "https://github.com/opencv/opencv_zoo/raw/main/models/"
    "face_detection_yunet/face_detection_yunet_2023mar.onnx"
)
MODEL_PATH  = Path("/app/models/face_detection_yunet_2023mar.onnx")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [face-detector] %(levelname)s %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# State persistence
# ---------------------------------------------------------------------------

def load_state() -> dict:
    if STATE_FILE.exists():
        try:
            return json.loads(STATE_FILE.read_text())
        except Exception:
            pass
    return {"last_ts": 0, "processed": []}


def save_state(state: dict) -> None:
    FACES_ROOT.mkdir(parents=True, exist_ok=True)
    # Keep processed list bounded to last 10 000 event IDs
    state["processed"] = state["processed"][-10_000:]
    STATE_FILE.write_text(json.dumps(state))


# ---------------------------------------------------------------------------
# YuNet model
# ---------------------------------------------------------------------------

def ensure_model() -> str:
    if not MODEL_PATH.exists():
        MODEL_PATH.parent.mkdir(parents=True, exist_ok=True)
        log.info("Downloading YuNet model...")
        urllib.request.urlretrieve(MODEL_URL, MODEL_PATH)
        log.info("Model downloaded -> %s", MODEL_PATH)
    return str(MODEL_PATH)


def build_detector(model_path: str) -> cv2.FaceDetectorYN:
    return cv2.FaceDetectorYN_create(
        model=model_path,
        config="",
        input_size=(320, 320),
        score_threshold=MIN_SCORE,
        nms_threshold=0.3,
        top_k=5000,
    )


def detect_faces(detector: cv2.FaceDetectorYN, img: np.ndarray) -> list[dict]:
    h, w = img.shape[:2]
    detector.setInputSize((w, h))
    _, raw = detector.detect(img)
    if raw is None:
        return []
    faces = []
    for row in raw:
        x, y, fw, fh, score = int(row[0]), int(row[1]), int(row[2]), int(row[3]), float(row[4])
        faces.append({"x": x, "y": y, "w": fw, "h": fh, "score": round(score, 4)})
    return faces


# ---------------------------------------------------------------------------
# Frigate API helpers
# ---------------------------------------------------------------------------

def frigate_get(path: str, binary: bool = False):
    url = f"{FRIGATE_URL}{path}"
    req = urllib.request.Request(url, headers={"Accept": "*/*"})
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return resp.read() if binary else json.loads(resp.read())
    except Exception as e:
        log.warning("Frigate request failed %s: %s", path, e)
        return None


def fetch_events(after: float) -> list[dict]:
    # Fetch recent person events that have snapshots. No `after` filter —
    # Frigate's timestamp comparison has edge cases; we use the processed-ID
    # set to skip already-handled events instead.
    data = frigate_get("/api/events?label=person&has_snapshot=1&limit=100")
    if not isinstance(data, list):
        return []
    # Only return events newer than our bookmark to avoid re-scanning forever
    return [e for e in data if e.get("start_time", 0) > after]


def fetch_snapshot(event_id: str) -> np.ndarray | None:
    raw = frigate_get(f"/api/events/{event_id}/snapshot.jpg", binary=True)
    if raw is None:
        return None
    arr = np.frombuffer(raw, dtype=np.uint8)
    return cv2.imdecode(arr, cv2.IMREAD_COLOR)


# ---------------------------------------------------------------------------
# Face saving
# ---------------------------------------------------------------------------

def padded_crop(img: np.ndarray, x: int, y: int, w: int, h: int) -> np.ndarray:
    ih, iw = img.shape[:2]
    pad_x = int(w * FACE_PADDING)
    pad_y = int(h * FACE_PADDING)
    x1 = max(0, x - pad_x)
    y1 = max(0, y - pad_y)
    x2 = min(iw, x + w + pad_x)
    y2 = min(ih, y + h + pad_y)
    return img[y1:y2, x1:x2]


def save_faces(event: dict, img: np.ndarray, faces: list[dict]) -> int:
    camera    = event.get("camera", "unknown")
    event_id  = event["id"]
    start_ts  = event.get("start_time", time.time())
    dt        = datetime.fromtimestamp(start_ts, tz=timezone.utc).astimezone()
    date_str  = dt.strftime("%Y-%m-%d")
    ts_str    = dt.strftime("%Y%m%dT%H%M%S")

    out_dir = FACES_ROOT / date_str
    out_dir.mkdir(parents=True, exist_ok=True)

    stem = f"{camera}__{event_id}__{ts_str}"
    saved = 0

    for n, face in enumerate(faces):
        crop = padded_crop(img, face["x"], face["y"], face["w"], face["h"])
        if crop.size == 0:
            continue

        jpg_path  = out_dir / f"{stem}__face{n}.jpg"
        json_path = out_dir / f"{stem}__face{n}.json"

        cv2.imwrite(str(jpg_path), crop)
        json_path.write_text(json.dumps({
            "event_id":  event_id,
            "camera":    camera,
            "timestamp": dt.isoformat(),
            "face_index": n,
            "bbox":      face,
            "image":     jpg_path.name,
        }, indent=2))
        saved += 1

    return saved


# ---------------------------------------------------------------------------
# Main loop
# ---------------------------------------------------------------------------

def main():
    log.info("Starting — polling Frigate at %s every %ds", FRIGATE_URL, POLL_INTERVAL)

    model_path = ensure_model()
    detector   = build_detector(model_path)
    state      = load_state()
    processed  = set(state["processed"])
    # Default to 1 hour ago on first run — avoids passing epoch 0 which Frigate rejects
    last_ts    = state["last_ts"] or (time.time() - 3600)

    log.info("Resuming from timestamp %d, %d events already processed", int(last_ts), len(processed))

    while True:
        events = fetch_events(after=last_ts)

        for event in events:
            event_id = event.get("id")
            if not event_id or event_id in processed:
                continue

            img = fetch_snapshot(event_id)
            if img is None:
                log.debug("No snapshot for event %s, skipping", event_id)
                processed.add(event_id)
                continue

            faces = detect_faces(detector, img)

            if faces:
                n_saved = save_faces(event, img, faces)
                log.info(
                    "event=%s camera=%s faces=%d saved=%d",
                    event_id[:8], event.get("camera", "?"), len(faces), n_saved,
                )
            else:
                log.debug("event=%s no faces detected", event_id[:8])

            processed.add(event_id)
            ts = event.get("start_time", 0)
            if ts > last_ts:
                last_ts = ts

        state["last_ts"]   = last_ts
        state["processed"] = list(processed)
        save_state(state)

        time.sleep(POLL_INTERVAL)


if __name__ == "__main__":
    main()
