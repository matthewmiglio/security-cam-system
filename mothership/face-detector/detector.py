"""
Face detector sidecar for Frigate NVR.

Samples each camera's live frame on a fast interval, runs YuNet, and saves
cropped face images to disk. A per-camera cooldown prevents flooding identical
frames when someone stands still.

Storage layout:
  /media/frigate/faces/YYYY-MM-DD/
    {camera}__{timestamp}__face{n}.jpg
    {camera}__{timestamp}__face{n}.json

Config via environment variables:
  FRIGATE_URL      Frigate API base URL          (default: http://frigate:5000)
  CAMERAS          Comma-separated camera names  (default: auto-discover)
  SAMPLE_INTERVAL  Seconds between frame grabs   (default: 2)
  SAVE_COOLDOWN    Min seconds between saves per camera (default: 3)
  MIN_FACE_SCORE   YuNet confidence cutoff        (default: 0.6)
  FACE_PADDING     Fractional bbox padding        (default: 0.2)
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

FRIGATE_URL     = os.environ.get("FRIGATE_URL", "http://frigate:5000")
CAMERAS_ENV     = os.environ.get("CAMERAS", "")
SAMPLE_INTERVAL = float(os.environ.get("SAMPLE_INTERVAL", "2"))
SAVE_COOLDOWN   = float(os.environ.get("SAVE_COOLDOWN", "3"))
MIN_SCORE       = float(os.environ.get("MIN_FACE_SCORE", "0.6"))
FACE_PADDING    = float(os.environ.get("FACE_PADDING", "0.2"))

FACES_ROOT = Path("/media/frigate/faces")
MODEL_URL  = (
    "https://github.com/opencv/opencv_zoo/raw/main/models/"
    "face_detection_yunet/face_detection_yunet_2023mar.onnx"
)
MODEL_PATH = Path("/app/models/face_detection_yunet_2023mar.onnx")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [face-detector] %(levelname)s %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Model
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
# Frigate API
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


def discover_cameras() -> list[str]:
    config = frigate_get("/api/config")
    if isinstance(config, dict) and "cameras" in config:
        names = list(config["cameras"].keys())
        log.info("Auto-discovered cameras: %s", names)
        return names
    log.warning("Could not auto-discover cameras from /api/config")
    return []


def fetch_latest_frame(camera: str) -> np.ndarray | None:
    raw = frigate_get(f"/api/{camera}/latest.jpg", binary=True)
    if raw is None:
        return None
    arr = np.frombuffer(raw, dtype=np.uint8)
    return cv2.imdecode(arr, cv2.IMREAD_COLOR)


# ---------------------------------------------------------------------------
# Saving
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


def save_faces(camera: str, img: np.ndarray, faces: list[dict]) -> int:
    now     = time.time()
    dt      = datetime.fromtimestamp(now, tz=timezone.utc).astimezone()
    out_dir = FACES_ROOT / dt.strftime("%Y-%m-%d")
    out_dir.mkdir(parents=True, exist_ok=True)
    ts_str  = dt.strftime("%Y%m%dT%H%M%S_%f")[:-3]  # ms precision
    stem    = f"{camera}__{ts_str}"
    saved   = 0

    for n, face in enumerate(faces):
        crop = padded_crop(img, face["x"], face["y"], face["w"], face["h"])
        if crop.size == 0:
            continue
        jpg_path  = out_dir / f"{stem}__face{n}.jpg"
        json_path = out_dir / f"{stem}__face{n}.json"
        cv2.imwrite(str(jpg_path), crop)
        json_path.write_text(json.dumps({
            "camera":     camera,
            "timestamp":  dt.isoformat(),
            "face_index": n,
            "bbox":       face,
            "image":      jpg_path.name,
        }, indent=2))
        saved += 1

    return saved


# ---------------------------------------------------------------------------
# Main loop
# ---------------------------------------------------------------------------

def main():
    log.info(
        "Starting — Frigate=%s  sample=%.1fs  cooldown=%.1fs",
        FRIGATE_URL, SAMPLE_INTERVAL, SAVE_COOLDOWN,
    )

    model_path = ensure_model()
    detector   = build_detector(model_path)

    # Resolve camera list
    if CAMERAS_ENV:
        cameras = [c.strip() for c in CAMERAS_ENV.split(",") if c.strip()]
        log.info("Using cameras from env: %s", cameras)
    else:
        cameras = []
        while not cameras:
            cameras = discover_cameras()
            if not cameras:
                log.info("Waiting for Frigate to become ready...")
                time.sleep(5)

    # Per-camera last-save timestamp for cooldown
    last_saved: dict[str, float] = {cam: 0.0 for cam in cameras}

    log.info("Sampling %d camera(s) every %.1fs", len(cameras), SAMPLE_INTERVAL)

    while True:
        for camera in cameras:
            img = fetch_latest_frame(camera)
            if img is None:
                continue

            faces = detect_faces(detector, img)
            if not faces:
                continue

            now = time.time()
            if now - last_saved[camera] < SAVE_COOLDOWN:
                continue  # too soon since last save for this camera

            n_saved = save_faces(camera, img, faces)
            if n_saved:
                last_saved[camera] = now
                log.info("camera=%s faces=%d saved=%d", camera, len(faces), n_saved)

        time.sleep(SAMPLE_INTERVAL)


if __name__ == "__main__":
    main()
