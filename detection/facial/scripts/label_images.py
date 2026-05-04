"""
Image labeler — flip through all images and mark each as face or no-face.

  LEFT ARROW  = no face
  RIGHT ARROW = face
  BACKSPACE   = undo last label
  Q / Escape  = quit and save

Results are saved to detection/facial/labeling_results.json after every keypress.
Run again to resume — already-labeled images are skipped.
"""

import json
import tkinter as tk
from pathlib import Path
from PIL import Image, ImageTk

IMAGES_ROOT = Path(__file__).parent.parent / "images"
RESULTS_FILE = Path(__file__).parent.parent / "labeling_results.json"

FACE_COLOR = "#2ecc71"
NO_FACE_COLOR = "#e74c3c"
BG_COLOR = "#1a1a2e"
TEXT_COLOR = "#eaeaea"


def gather_images() -> list[Path]:
    imgs = []
    for subdir in ["faces", "no_faces"]:
        imgs.extend(sorted((IMAGES_ROOT / subdir).glob("*.jpg")))
    return imgs


def load_results() -> dict[str, str]:
    if RESULTS_FILE.exists():
        return json.loads(RESULTS_FILE.read_text())
    return {}


def save_results(results: dict[str, str]) -> None:
    RESULTS_FILE.write_text(json.dumps(results, indent=2))


def run_labeler():
    all_images = gather_images()
    if not all_images:
        print("No images found in", IMAGES_ROOT)
        return

    results = load_results()

    # Find first unlabeled image
    unlabeled = [p for p in all_images if p.name not in results]
    queue = unlabeled  # remaining to label
    history: list[tuple[str, str]] = []  # (name, label) for undo

    root = tk.Tk()
    root.title("Image Labeler")
    root.configure(bg=BG_COLOR)
    root.geometry("900x700")
    root.resizable(True, True)

    # ── Layout ──────────────────────────────────────────────────────────────
    top_bar = tk.Frame(root, bg=BG_COLOR)
    top_bar.pack(fill="x", padx=12, pady=(10, 0))

    progress_var = tk.StringVar()
    lbl_progress = tk.Label(top_bar, textvariable=progress_var, bg=BG_COLOR,
                            fg=TEXT_COLOR, font=("Helvetica", 13))
    lbl_progress.pack(side="left")

    filename_var = tk.StringVar()
    lbl_filename = tk.Label(top_bar, textvariable=filename_var, bg=BG_COLOR,
                             fg="#aaaaaa", font=("Helvetica", 11))
    lbl_filename.pack(side="right")

    canvas = tk.Label(root, bg=BG_COLOR)
    canvas.pack(expand=True, fill="both", padx=12, pady=8)

    hint = tk.Label(root,
                    text="← No face    |    Face →    |    Backspace = undo    |    Q = quit",
                    bg=BG_COLOR, fg="#666688", font=("Helvetica", 11))
    hint.pack(pady=(0, 10))

    current_photo = [None]  # keep reference to avoid GC

    def show_current():
        if not queue:
            progress_var.set(f"Done! {len(results)}/{len(all_images)} labeled")
            filename_var.set("")
            canvas.configure(image="", bg=BG_COLOR, text="All done!", fg=TEXT_COLOR,
                              font=("Helvetica", 24))
            return

        path = queue[0]
        done = len(results)
        total = len(all_images)
        remaining = len(queue)
        progress_var.set(f"{done}/{total} labeled  ({remaining} remaining)")
        filename_var.set(f"{path.parent.name}/{path.name}")

        try:
            img = Image.open(path)
            # Fit inside canvas area
            max_w = root.winfo_width() - 24 or 860
            max_h = root.winfo_height() - 120 or 560
            img.thumbnail((max_w, max_h), Image.LANCZOS)
            photo = ImageTk.PhotoImage(img)
            current_photo[0] = photo
            canvas.configure(image=photo, text="")
        except Exception as e:
            canvas.configure(image="", text=f"Error: {e}", fg=TEXT_COLOR,
                             font=("Helvetica", 14))

    def label(value: str):
        if not queue:
            return
        path = queue.pop(0)
        results[path.name] = value
        history.append((path.name, value))
        save_results(results)
        color = FACE_COLOR if value == "face" else NO_FACE_COLOR
        root.configure(bg=color)
        root.after(80, lambda: root.configure(bg=BG_COLOR))
        show_current()

    def undo():
        if not history:
            return
        name, _ = history.pop()
        results.pop(name, None)
        # Put it back at front of queue
        path = next((p for p in all_images if p.name == name), None)
        if path:
            queue.insert(0, path)
        save_results(results)
        show_current()

    def on_key(event):
        if event.keysym == "Left":
            label("no_face")
        elif event.keysym == "Right":
            label("face")
        elif event.keysym == "BackSpace":
            undo()
        elif event.keysym in ("q", "Q", "Escape"):
            save_results(results)
            root.destroy()

    root.bind("<Key>", on_key)
    root.after(100, show_current)  # wait for window to size before first render
    root.mainloop()

    labeled = len(results)
    faces = sum(1 for v in results.values() if v == "face")
    no_faces = sum(1 for v in results.values() if v == "no_face")
    print(f"\nSaved {labeled} labels to {RESULTS_FILE}")
    print(f"  face={faces}  no_face={no_faces}")


if __name__ == "__main__":
    run_labeler()
