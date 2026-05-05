"""
Train a face classifier from labeled face crops.

Reads face-labels.json, extracts ArcFace embeddings via InsightFace (buffalo_sc),
trains an SVM classifier, and saves the model to face-classifiers/.

Output: face-classifiers/face-classifier-{N}.pkl
  N auto-increments from existing files in that directory.

Usage:
  poetry run python train-face-classifier.py
"""

import json
import pickle
import sys
from datetime import datetime
from pathlib import Path

import cv2
import numpy as np
from insightface.model_zoo import get_model as insightface_get_model
from sklearn.preprocessing import LabelEncoder
from sklearn.svm import SVC
from sklearn.model_selection import cross_val_score

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

SCRIPT_DIR      = Path(__file__).parent
LABELS_FILE     = SCRIPT_DIR / "face-labels.json"
FACES_ROOT      = SCRIPT_DIR.parent / "mothership" / "storage" / "faces"
CLASSIFIERS_DIR = SCRIPT_DIR / "models"

SKIP_LABELS = {"__skip__", "unknown"}

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def next_index() -> int:
    CLASSIFIERS_DIR.mkdir(exist_ok=True)
    existing = sorted(CLASSIFIERS_DIR.glob("face-classifier-*.pkl"))
    if not existing:
        return 1
    return int(existing[-1].stem.split("-")[-1]) + 1


def extract_embeddings(
    classifications: dict[str, str], rec_model
) -> tuple[np.ndarray, list[str]]:
    # YuNet already cropped the faces — skip InsightFace's internal detector
    # and feed crops straight to the recognition model.
    embeddings, labels, skipped = [], [], 0

    for rel_path, label in classifications.items():
        img_path = FACES_ROOT / Path(rel_path)
        if not img_path.exists():
            print(f"  MISSING      {rel_path}")
            skipped += 1
            continue

        img = cv2.imread(str(img_path))
        if img is None:
            print(f"  UNREADABLE   {img_path.name}")
            skipped += 1
            continue

        face_112 = cv2.resize(img, (112, 112))
        embedding = rec_model.get_feat([face_112])[0]
        embeddings.append(embedding)
        labels.append(label)
        print(f"  OK  {label:<16}  {img_path.name}")

    print(f"\n  Embedded: {len(embeddings)}   Skipped: {skipped}")
    return np.array(embeddings, dtype=np.float32), labels


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    if not LABELS_FILE.exists():
        sys.exit(f"face-labels.json not found at {LABELS_FILE}")

    data = json.loads(LABELS_FILE.read_text())

    classifications = {
        k: v for k, v in data["classifications"].items()
        if v not in SKIP_LABELS
    }

    label_counts: dict[str, int] = {}
    for v in classifications.values():
        label_counts[v] = label_counts.get(v, 0) + 1

    print("Label counts:")
    for lbl, cnt in sorted(label_counts.items()):
        print(f"  {lbl}: {cnt}")

    if len(label_counts) < 2:
        sys.exit("Need at least 2 labels with classified faces to train.")

    low = {l: c for l, c in label_counts.items() if c < 5}
    if low:
        print(f"\nWARNING: low sample count — {low}. More labeled faces = better accuracy.")

    print("\nLoading InsightFace buffalo_sc recognition model ...")
    model_path = Path.home() / ".insightface" / "models" / "buffalo_sc" / "w600k_mbf.onnx"
    rec_model = insightface_get_model(str(model_path), providers=["CPUExecutionProvider"])
    rec_model.prepare(ctx_id=-1)

    print("\nExtracting embeddings ...")
    X, y = extract_embeddings(classifications, rec_model)

    if len(X) < 2:
        sys.exit("Not enough embeddings extracted. Check that FACES_ROOT is correct.")

    le = LabelEncoder()
    y_enc = le.fit_transform(y)

    print("\nTraining SVM (RBF kernel) ...")
    clf = SVC(kernel="rbf", C=10.0, gamma="scale", probability=True)
    clf.fit(X, y_enc)

    n_folds = min(5, len(X))
    if n_folds >= 2:
        scores = cross_val_score(clf, X, y_enc, cv=n_folds, scoring="accuracy")
        print(f"  Cross-val accuracy ({n_folds}-fold): {scores.mean():.1%} ± {scores.std():.1%}")
    else:
        print("  (too few samples for cross-validation)")

    idx = next_index()
    out_path = CLASSIFIERS_DIR / f"face-classifier-{idx}.pkl"

    payload = {
        "classifier":    clf,
        "label_encoder": le,
        "labels":        list(le.classes_),
        "embed_model":   "insightface/buffalo_sc",
        "trained_at":    datetime.now().isoformat(),
        "sample_counts": label_counts,
        "n_samples":     len(X),
    }
    with open(out_path, "wb") as f:
        pickle.dump(payload, f)

    print(f"\nSaved -> {out_path.relative_to(SCRIPT_DIR)}")
    print(f"Labels: {list(le.classes_)}")


if __name__ == "__main__":
    main()
