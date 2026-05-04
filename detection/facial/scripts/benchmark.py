"""
Benchmark face detectors on the downloaded image sets.

Metrics per model:
  - TPR  : true positive rate on face images  (detect ≥1 face)
  - FPR  : false positive rate on no-face images (detect ≥1 face)
  - mean_ms : average inference time per image
  - model_mb : model file size on disk (where determinable)

Usage:
    python scripts/benchmark.py [--models all|yunet|mediapipe|insightface|retinaface]

Results are written to detection/facial/benchmark_results.json and printed as a table.
"""

import os
import sys
import time
import json
import argparse
import traceback
from pathlib import Path

import cv2
import numpy as np

IMAGES_DIR = Path(__file__).parent.parent / "images"
FACES_DIR = IMAGES_DIR / "faces"
NO_FACES_DIR = IMAGES_DIR / "no_faces"
RESULTS_FILE = Path(__file__).parent.parent / "benchmark_results.json"

ALL_MODELS = ["yunet", "mediapipe", "insightface", "retinaface"]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def load_images(directory: Path) -> list[np.ndarray]:
    imgs = []
    for p in sorted(directory.glob("*.jpg")):
        img = cv2.imread(str(p))
        if img is not None:
            imgs.append(img)
    return imgs


def run_benchmark(detector_fn, images: list[np.ndarray]) -> tuple[float, list[int]]:
    """Returns (mean_ms, list_of_detection_counts)."""
    counts = []
    times = []
    for img in images:
        t0 = time.perf_counter()
        n = detector_fn(img)
        t1 = time.perf_counter()
        counts.append(n)
        times.append((t1 - t0) * 1000)
    mean_ms = float(np.mean(times)) if times else 0.0
    return mean_ms, counts


def metrics(face_counts: list[int], no_face_counts: list[int]) -> dict:
    tpr = sum(1 for c in face_counts if c > 0) / max(len(face_counts), 1)
    fpr = sum(1 for c in no_face_counts if c > 0) / max(len(no_face_counts), 1)
    return {"tpr": round(tpr, 4), "fpr": round(fpr, 4)}


# ---------------------------------------------------------------------------
# YuNet  (requires explicit ONNX model file — downloaded on first run)
# ---------------------------------------------------------------------------

YUNET_MODEL_URL = (
    "https://github.com/opencv/opencv_zoo/raw/main/models/"
    "face_detection_yunet/face_detection_yunet_2023mar.onnx"
)
YUNET_MODEL_PATH = Path(__file__).parent.parent / "models" / "face_detection_yunet_2023mar.onnx"


def _ensure_yunet_model() -> str:
    if not YUNET_MODEL_PATH.exists():
        import urllib.request
        YUNET_MODEL_PATH.parent.mkdir(parents=True, exist_ok=True)
        print(f"  Downloading YuNet model -> {YUNET_MODEL_PATH} ...", flush=True)
        urllib.request.urlretrieve(YUNET_MODEL_URL, YUNET_MODEL_PATH)
    return str(YUNET_MODEL_PATH)


def build_yunet():
    model_path = _ensure_yunet_model()
    detector = cv2.FaceDetectorYN_create(
        model=model_path,
        config="",
        input_size=(320, 320),
        score_threshold=0.6,
        nms_threshold=0.3,
        top_k=5000,
    )

    def detect(img: np.ndarray) -> int:
        h, w = img.shape[:2]
        detector.setInputSize((w, h))
        _, faces = detector.detect(img)
        return 0 if faces is None else len(faces)

    mb = YUNET_MODEL_PATH.stat().st_size / 1e6
    return detect, round(mb, 2)


# ---------------------------------------------------------------------------
# MediaPipe  (new tasks API, requires tflite model download on first run)
# ---------------------------------------------------------------------------

MEDIAPIPE_MODEL_URL = (
    "https://storage.googleapis.com/mediapipe-models/face_detector/"
    "blaze_face_short_range/float16/1/blaze_face_short_range.tflite"
)
MEDIAPIPE_MODEL_PATH = Path(__file__).parent.parent / "models" / "blaze_face_short_range.tflite"


def _ensure_mediapipe_model() -> str:
    if not MEDIAPIPE_MODEL_PATH.exists():
        import urllib.request
        MEDIAPIPE_MODEL_PATH.parent.mkdir(parents=True, exist_ok=True)
        print(f"  Downloading MediaPipe model -> {MEDIAPIPE_MODEL_PATH} ...", flush=True)
        urllib.request.urlretrieve(MEDIAPIPE_MODEL_URL, MEDIAPIPE_MODEL_PATH)
    return str(MEDIAPIPE_MODEL_PATH)


def build_mediapipe():
    import mediapipe as mp
    from mediapipe.tasks.python import vision
    from mediapipe.tasks.python.core import base_options as bo

    model_path = _ensure_mediapipe_model()
    options = vision.FaceDetectorOptions(
        base_options=bo.BaseOptions(model_asset_path=model_path),
        min_detection_confidence=0.5,
    )
    detector = vision.FaceDetector.create_from_options(options)

    def detect(img: np.ndarray) -> int:
        rgb = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
        mp_img = mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb)
        result = detector.detect(mp_img)
        return len(result.detections)

    mb = MEDIAPIPE_MODEL_PATH.stat().st_size / 1e6
    return detect, round(mb, 2)


# ---------------------------------------------------------------------------
# InsightFace SCRFD-500MF
# ---------------------------------------------------------------------------

def build_insightface():
    import insightface
    from insightface.app import FaceAnalysis

    app = FaceAnalysis(
        name="buffalo_sc",
        allowed_modules=["detection"],
        providers=["CPUExecutionProvider"],
    )
    app.prepare(ctx_id=-1, det_size=(640, 640))

    def detect(img: np.ndarray) -> int:
        faces = app.get(img)
        return len(faces)

    # buffalo_sc det model ~2 MB
    model_path = Path.home() / ".insightface" / "models" / "buffalo_sc"
    mb = sum(f.stat().st_size for f in model_path.rglob("*") if f.is_file()) / 1e6 if model_path.exists() else 2.0
    return detect, round(mb, 2)


# ---------------------------------------------------------------------------
# RetinaFace
# ---------------------------------------------------------------------------

def build_retinaface():
    from retinaface import RetinaFace

    def detect(img: np.ndarray) -> int:
        faces = RetinaFace.detect_faces(img)
        if isinstance(faces, dict):
            return len(faces)
        return 0

    return detect, 1.7


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

BUILDERS = {
    "yunet": build_yunet,
    "mediapipe": build_mediapipe,
    "insightface": build_insightface,
    "retinaface": build_retinaface,
}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--models", default="all", help="Comma-separated model names or 'all'")
    args = parser.parse_args()

    models = ALL_MODELS if args.models == "all" else [m.strip() for m in args.models.split(",")]

    face_images = load_images(FACES_DIR)
    no_face_images = load_images(NO_FACES_DIR)
    print(f"Loaded {len(face_images)} face images, {len(no_face_images)} no-face images\n")

    if not face_images or not no_face_images:
        print("ERROR: Missing images. Run download_images.py first.")
        sys.exit(1)

    results = {}

    for name in models:
        print(f"--- {name.upper()} ---")
        try:
            builder = BUILDERS[name]
            detect_fn, model_mb = builder()

            mean_ms_face, face_counts = run_benchmark(detect_fn, face_images)
            mean_ms_no, no_face_counts = run_benchmark(detect_fn, no_face_images)
            mean_ms = round((mean_ms_face + mean_ms_no) / 2, 1)

            m = metrics(face_counts, no_face_counts)
            results[name] = {
                "tpr": m["tpr"],
                "fpr": m["fpr"],
                "mean_ms": mean_ms,
                "model_mb": model_mb,
            }
            print(f"  TPR={m['tpr']:.1%}  FPR={m['fpr']:.1%}  {mean_ms:.1f}ms/frame  {model_mb:.2f}MB")
        except Exception:
            print(f"  FAILED:")
            traceback.print_exc()
            results[name] = {"error": traceback.format_exc()}
        print()

    # Write JSON
    RESULTS_FILE.write_text(json.dumps(results, indent=2))
    print(f"Results saved -> {RESULTS_FILE}\n")

    # Print ranked table
    valid = {k: v for k, v in results.items() if "error" not in v}
    if valid:
        print(f"{'Model':<16} {'TPR':>6} {'FPR':>6} {'ms/frame':>10} {'MB':>6}")
        print("-" * 50)
        for name, r in sorted(valid.items(), key=lambda x: (-x[1]["tpr"], x[1]["fpr"], x[1]["mean_ms"])):
            print(f"{name:<16} {r['tpr']:>6.1%} {r['fpr']:>6.1%} {r['mean_ms']:>10.1f} {r['model_mb']:>6.2f}")


if __name__ == "__main__":
    main()
