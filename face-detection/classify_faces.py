"""
Face classification GUI.

Tab 1 — Labels   : add / remove label names (e.g. matthew, john, jacob)
Tab 2 — Classify : flip through face crops, assign a label with a button or
                   keyboard shortcut (1-9), skip with S, mark unknown with U,
                   go back with ← arrow.

Results saved to:  detection/facial/face-labels.json
Faces are read from: mothership/storage/faces/
Run again to resume — already-classified faces are skipped.
"""

import json
import tkinter as tk
from tkinter import ttk, messagebox, simpledialog
from pathlib import Path
from PIL import Image, ImageTk

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

SCRIPT_DIR   = Path(__file__).parent
LABELS_FILE  = SCRIPT_DIR / "face-labels.json"
FACES_ROOT   = SCRIPT_DIR.parent / "mothership" / "storage" / "faces"

# ---------------------------------------------------------------------------
# Persistence
# ---------------------------------------------------------------------------

def load_data() -> dict:
    if LABELS_FILE.exists():
        try:
            return json.loads(LABELS_FILE.read_text())
        except Exception:
            pass
    return {"labels": [], "classifications": {}}


def save_data(data: dict) -> None:
    LABELS_FILE.write_text(json.dumps(data, indent=2))


# ---------------------------------------------------------------------------
# Image scanning
# ---------------------------------------------------------------------------

def scan_faces() -> list[Path]:
    if not FACES_ROOT.exists():
        return []
    return sorted(FACES_ROOT.rglob("*.jpg"))


# ---------------------------------------------------------------------------
# App
# ---------------------------------------------------------------------------

BG       = "#1a1a2e"
PANEL    = "#16213e"
ACCENT   = "#0f3460"
GREEN    = "#2ecc71"
RED      = "#e74c3c"
YELLOW   = "#f39c12"
TEXT     = "#eaeaea"
SUBTEXT  = "#888aaa"
FONT     = ("Helvetica", 12)
FONT_SM  = ("Helvetica", 10)
FONT_LG  = ("Helvetica", 15, "bold")


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Face Classifier")
        self.geometry("960x720")
        self.configure(bg=BG)
        self.resizable(True, True)

        self.data = load_data()

        nb = ttk.Notebook(self)
        nb.pack(expand=True, fill="both", padx=10, pady=10)

        self.tab_labels   = LabelsTab(nb, self.data, on_change=self._on_labels_change)
        self.tab_classify = ClassifyTab(nb, self.data)

        nb.add(self.tab_labels,   text="  Labels  ")
        nb.add(self.tab_classify, text="  Classify  ")

        nb.bind("<<NotebookTabChanged>>", self._on_tab_change)
        self.protocol("WM_DELETE_WINDOW", self._on_close)

    def _on_labels_change(self):
        save_data(self.data)
        self.tab_classify.refresh_label_buttons()

    def _on_tab_change(self, _event):
        self.tab_classify.reload_queue()

    def _on_close(self):
        save_data(self.data)
        self.destroy()


# ---------------------------------------------------------------------------
# Labels Tab
# ---------------------------------------------------------------------------

class LabelsTab(tk.Frame):
    def __init__(self, parent, data: dict, on_change):
        super().__init__(parent, bg=BG)
        self.data      = data
        self.on_change = on_change
        self._build()

    def _build(self):
        tk.Label(self, text="Manage Labels", bg=BG, fg=TEXT,
                 font=FONT_LG).pack(pady=(20, 4))
        tk.Label(self, text="One label per person. Used as buttons in the Classify tab.",
                 bg=BG, fg=SUBTEXT, font=FONT_SM).pack(pady=(0, 16))

        # Entry row
        row = tk.Frame(self, bg=BG)
        row.pack(pady=6)
        self.entry = tk.Entry(row, font=FONT, width=22, bg=PANEL, fg=TEXT,
                              insertbackground=TEXT, relief="flat", bd=6)
        self.entry.pack(side="left", padx=(0, 8))
        self.entry.bind("<Return>", lambda _: self._add())
        tk.Button(row, text="Add Label", command=self._add,
                  bg=GREEN, fg="white", font=FONT, relief="flat",
                  padx=14, pady=6, cursor="hand2").pack(side="left")

        # Label list
        self.list_frame = tk.Frame(self, bg=BG)
        self.list_frame.pack(fill="both", expand=True, padx=40, pady=10)
        self._refresh_list()

    def _refresh_list(self):
        for w in self.list_frame.winfo_children():
            w.destroy()
        for label in self.data["labels"]:
            row = tk.Frame(self.list_frame, bg=PANEL, pady=6, padx=12)
            row.pack(fill="x", pady=3)
            tk.Label(row, text=label, bg=PANEL, fg=TEXT,
                     font=FONT, anchor="w").pack(side="left", expand=True, fill="x")
            count = sum(1 for v in self.data["classifications"].values() if v == label)
            tk.Label(row, text=f"{count} faces", bg=PANEL,
                     fg=SUBTEXT, font=FONT_SM).pack(side="left", padx=12)
            tk.Button(row, text="✕", command=lambda l=label: self._remove(l),
                      bg=RED, fg="white", font=FONT_SM, relief="flat",
                      padx=8, cursor="hand2").pack(side="right")

    def _add(self):
        name = self.entry.get().strip().lower()
        if not name:
            return
        if name in self.data["labels"]:
            messagebox.showwarning("Duplicate", f'"{name}" already exists.')
            return
        self.data["labels"].append(name)
        self.entry.delete(0, "end")
        self._refresh_list()
        self.on_change()

    def _remove(self, label: str):
        count = sum(1 for v in self.data["classifications"].values() if v == label)
        if count and not messagebox.askyesno(
            "Remove label",
            f'"{label}" is assigned to {count} face(s). Remove anyway?\n'
            "Those faces will become unclassified."
        ):
            return
        self.data["labels"].remove(label)
        self.data["classifications"] = {
            k: v for k, v in self.data["classifications"].items() if v != label
        }
        self._refresh_list()
        self.on_change()


# ---------------------------------------------------------------------------
# Classify Tab
# ---------------------------------------------------------------------------

class ClassifyTab(tk.Frame):
    def __init__(self, parent, data: dict):
        super().__init__(parent, bg=BG)
        self.data    = data
        self.queue   : list[Path] = []
        self.history : list[tuple[str, str]] = []  # (rel_key, label)
        self._photo  = None
        self._build()
        self.reload_queue()

    def _build(self):
        # Top bar
        top = tk.Frame(self, bg=BG)
        top.pack(fill="x", padx=16, pady=(14, 0))
        self.lbl_progress = tk.Label(top, text="", bg=BG, fg=TEXT, font=FONT)
        self.lbl_progress.pack(side="left")
        self.lbl_filename = tk.Label(top, text="", bg=BG, fg=SUBTEXT, font=FONT_SM)
        self.lbl_filename.pack(side="right")

        # Image canvas
        self.img_label = tk.Label(self, bg=BG)
        self.img_label.pack(expand=True, fill="both", padx=16, pady=8)

        # Label buttons frame
        self.btn_frame = tk.Frame(self, bg=BG)
        self.btn_frame.pack(fill="x", padx=16, pady=(0, 4))

        # Utility buttons
        util = tk.Frame(self, bg=BG)
        util.pack(fill="x", padx=16, pady=(0, 14))
        tk.Button(util, text="← Undo  (Backspace)", command=self._undo,
                  bg=ACCENT, fg=TEXT, font=FONT_SM, relief="flat",
                  padx=12, pady=6, cursor="hand2").pack(side="left", padx=4)
        tk.Button(util, text="Skip  (S)", command=lambda: self._classify("__skip__"),
                  bg=PANEL, fg=TEXT, font=FONT_SM, relief="flat",
                  padx=12, pady=6, cursor="hand2").pack(side="left", padx=4)
        tk.Button(util, text="Unknown  (U)", command=lambda: self._classify("unknown"),
                  bg=YELLOW, fg="white", font=FONT_SM, relief="flat",
                  padx=12, pady=6, cursor="hand2").pack(side="left", padx=4)

        self.bind_all("<Key>", self._on_key)

    def reload_queue(self):
        all_faces = scan_faces()
        classified = set(self.data["classifications"].keys())
        # Unclassified = not in classifications, or explicitly skipped (excluded from queue)
        self.queue = [
            p for p in all_faces
            if self._key(p) not in classified
        ]
        self._show_current()

    def refresh_label_buttons(self):
        for w in self.btn_frame.winfo_children():
            w.destroy()
        labels = self.data["labels"]
        for i, label in enumerate(labels):
            shortcut = str(i + 1) if i < 9 else ""
            text = f"{shortcut}: {label}" if shortcut else label
            tk.Button(
                self.btn_frame, text=text,
                command=lambda l=label: self._classify(l),
                bg=GREEN, fg="white", font=FONT,
                relief="flat", padx=14, pady=8, cursor="hand2",
            ).pack(side="left", padx=4, pady=4)

    def _key(self, path: Path) -> str:
        try:
            return str(path.relative_to(FACES_ROOT))
        except ValueError:
            return path.name

    def _show_current(self):
        self.refresh_label_buttons()

        total_faces    = len(scan_faces())
        n_classified   = len(self.data["classifications"])
        n_remaining    = len(self.queue)

        if not self.queue:
            self.lbl_progress.config(
                text=f"All done! {n_classified}/{total_faces} classified"
            )
            self.lbl_filename.config(text="")
            self.img_label.config(image="", text="No unclassified faces.",
                                  fg=SUBTEXT, font=FONT_LG)
            return

        path = self.queue[0]
        self.lbl_progress.config(
            text=f"{n_classified}/{total_faces} classified  ({n_remaining} remaining)"
        )
        self.lbl_filename.config(text=path.name)

        try:
            img = Image.open(path)
            max_w = self.winfo_width() - 32 or 900
            max_h = self.winfo_height() - 200 or 460
            img.thumbnail((max_w, max_h), Image.LANCZOS)
            photo = ImageTk.PhotoImage(img)
            self._photo = photo
            self.img_label.config(image=photo, text="")
        except Exception as e:
            self.img_label.config(image="", text=f"Error loading image: {e}",
                                  fg=RED, font=FONT)

    def _classify(self, label: str):
        if not self.queue:
            return
        path  = self.queue.pop(0)
        key   = self._key(path)

        if label != "__skip__":
            self.data["classifications"][key] = label
            self.history.append((key, label))
        else:
            # skip without saving — just move on
            self.history.append((key, "__skip__"))

        save_data(self.data)

        # Flash green/yellow to confirm
        color = GREEN if label not in ("__skip__", "unknown") else (YELLOW if label == "unknown" else PANEL)
        self.configure(bg=color)
        self.after(80, lambda: self.configure(bg=BG))
        self._show_current()

    def _undo(self):
        if not self.history:
            return
        key, label = self.history.pop()
        # Put file back at front of queue
        path = FACES_ROOT / key
        if path.exists():
            self.queue.insert(0, path)
        if label != "__skip__":
            self.data["classifications"].pop(key, None)
        save_data(self.data)
        self._show_current()

    def _on_key(self, event):
        labels = self.data["labels"]
        k = event.keysym
        if k == "BackSpace":
            self._undo()
        elif k.lower() == "s":
            self._classify("__skip__")
        elif k.lower() == "u":
            self._classify("unknown")
        elif k.isdigit() and 1 <= int(k) <= len(labels):
            self._classify(labels[int(k) - 1])


if __name__ == "__main__":
    app = App()
    app.mainloop()
