import threading
import tkinter as tk
import sys
from pathlib import Path

# ── Renk paleti (tüm ekranlar) ─────────────────────────────────────────────
BG     = "#0f172a"
PANEL  = "#111827"
FG     = "#e5e7eb"
MUTED  = "#94a3b8"
BORDER = "#334155"
BTN_BG = "#1e293b"
BTN_FG = "#f1f5f9"
ERR_FG = "#f87171"
# ──────────────────────────────────────────────────────────────────────────


def center_window(win: tk.Misc, width: int, height: int) -> None:
    win.update_idletasks()
    sw = win.winfo_screenwidth()
    sh = win.winfo_screenheight()
    x  = (sw - width)  // 2
    y  = (sh - height) // 2
    win.geometry(f"{width}x{height}+{x}+{y}")


def _get_icon_path() -> "Path | None":
    """Find favicon.png or icon.ico in standard locations."""
    if getattr(sys, 'frozen', False):
        base = Path(sys.executable).parent
    else:
        base = Path(__file__).resolve().parent

    # Check GSB standard locations - prioritize ICO (more reliable)
    # Layout A: EXE is Desktop\GSB\GSB.exe  -> icons at Desktop\GSB_Sistem\GSB_Dosyalar\icons\
    # Layout B: EXE is Desktop\GSB_Sistem\Uygulama\*.exe -> icons at Desktop\GSB_Sistem\GSB_Dosyalar\icons\
    candidates = [
        base / "icons" / "icon.ico",                                              # same-dir ICO
        base / "icons" / "favicon.png",                                           # same-dir PNG
        base / "GSB_Dosyalar" / "icons" / "icon.ico",                             # subfolder ICO
        base / "GSB_Dosyalar" / "icons" / "favicon.png",                          # subfolder PNG
        base.parent / "GSB_Dosyalar" / "icons" / "icon.ico",                      # Layout B: Uygulama/../GSB_Dosyalar
        base.parent / "GSB_Dosyalar" / "icons" / "favicon.png",                   # Layout B: PNG
        base.parent / "GSB_Dosyalar" / "icons" / "GSB_Giris.ico",                 # Layout B: fallback ICO
        base.parent.parent / "GSB_Sistem" / "GSB_Dosyalar" / "icons" / "icon.ico",# Layout A: GSB/../GSB_Sistem
        base.parent.parent / "GSB_Sistem" / "GSB_Dosyalar" / "icons" / "favicon.png",
        base.parent / "GSB_Sistem" / "GSB_Dosyalar" / "icons" / "icon.ico",       # Layout A alt
        base.parent / "GSB_Sistem" / "GSB_Dosyalar" / "icons" / "favicon.png",
        base.parent / "assets" / "icons" / "icon.ico",                            # dev env ICO
        base.parent / "assets" / "icons" / "icon.png",                            # dev env PNG
    ]
    
    for c in candidates:
        if c.exists():
            return c
    return None


def _make_dark_win(title: str, width: int, height: int,
                   parent: "tk.Misc | None" = None) -> "tk.Tk | tk.Toplevel":
    if parent is None:
        win = tk.Tk()
    else:
        win = tk.Toplevel(parent)
        win.transient(parent)
    
    # Set Icon for ALL windows (both Tk and Toplevel)
    try:
        icon_p = _get_icon_path()
        if icon_p:
            if str(icon_p).endswith('.ico'):
                # Use iconbitmap for ICO files (most reliable on Windows)
                win.iconbitmap(str(icon_p))
            else:
                # Use iconphoto for PNG files
                img = tk.PhotoImage(file=str(icon_p))
                win.iconphoto(True, img)
                # Keep a reference to avoid garbage collection
                win._icon_ref = img 
    except Exception:
        pass

    win.title(title)
    win.resizable(False, False)
    win.configure(bg=BG)
    center_window(win, width, height)
    return win


def _dark_panel(parent_win: tk.Misc) -> tk.Frame:
    """1 px kenarlıklı koyu iç panel."""
    outer = tk.Frame(parent_win, bg=BORDER)
    outer.pack(fill="both", expand=True, padx=14, pady=12)
    inner = tk.Frame(outer, bg=PANEL)
    inner.pack(fill="both", expand=True, padx=1, pady=1)
    return inner


def _dark_button(panel: tk.Frame, text: str, command) -> tk.Button:
    return tk.Button(
        panel, text=text, width=12, command=command,
        bg=BTN_BG, fg=BTN_FG,
        activebackground=BORDER, activeforeground=BTN_FG,
        relief="flat", cursor="hand2",
        font=("Segoe UI", 9),
    )


# ── Yükleniyor ekranı ─────────────────────────────────────────────────────
def run_with_status(title: str, status_text: str, task_fn,
                    parent: "tk.Misc | None" = None):
    done = {"ok": False, "error": None, "result": None}

    def worker():
        try:
            done["result"] = task_fn()
            done["ok"] = True
        except Exception as exc:  # noqa: BLE001
            done["error"] = exc

    t = threading.Thread(target=worker, daemon=True)

    win = _make_dark_win(title, 400, 170, parent)
    panel = _dark_panel(win)

    lbl_main = tk.Label(
        panel, text=status_text,
        font=("Segoe UI", 13, "bold"), fg=FG, bg=PANEL,
        justify="center",
    )
    lbl_main.pack(pady=(28, 6))

    lbl_sub = tk.Label(
        panel, text="Lütfen bekleyin",
        font=("Segoe UI", 9), fg=MUTED, bg=PANEL,
    )
    lbl_sub.pack()

    dots = {"i": 0}

    def animate():
        if done["ok"] or done["error"] is not None:
            return
        dots["i"] = (dots["i"] + 1) % 4
        lbl_sub.configure(text="Lütfen bekleyin" + "." * dots["i"])
        win.after(280, animate)

    def poll():
        if done["ok"] or done["error"] is not None:
            win.destroy()
            return
        win.after(120, poll)

    win.protocol("WM_DELETE_WINDOW", lambda: None)

    try:
        if parent is not None:
            win.grab_set()
    except Exception:
        pass

    t.start()
    win.after(120, poll)
    win.after(280, animate)

    if parent is None:
        win.mainloop()
    else:
        parent.wait_window(win)

    if done["error"] is not None:
        show_error(title, f"Hata: {done['error']}", parent=parent)
        return None

    return done["result"]


# ── Ortak koyu diyalog (info / error) ─────────────────────────────────────
def _show_dialog(title: str, headline: str, details: str = "",
                 headline_fg: str = FG,
                 parent: "tk.Misc | None" = None) -> None:
    has_details = bool(details and details.strip())
    height = 250 if has_details else 190

    win = _make_dark_win(title, 480, height, parent)
    panel = _dark_panel(win)

    lbl_head = tk.Label(
        panel, text=headline, wraplength=440,
        font=("Segoe UI", 12, "bold"), fg=headline_fg, bg=PANEL,
        justify="center",
    )
    lbl_head.pack(fill="x", pady=(24, 6), padx=12)

    if has_details:
        lbl_det = tk.Label(
            panel, text=details, wraplength=440,
            font=("Segoe UI", 10), fg=MUTED, bg=PANEL,
            justify="center",
        )
        lbl_det.pack(fill="x", pady=(0, 8), padx=12)

    actions = tk.Frame(panel, bg=PANEL)
    actions.pack(fill="x", side="bottom", padx=14, pady=(0, 14))

    def close():
        try:
            win.destroy()
        except Exception:
            pass

    btn = _dark_button(actions, "Tamam", close)
    btn.pack(side="right")
    win.protocol("WM_DELETE_WINDOW", close)
    try:
        btn.focus_set()
    except Exception:
        pass

    if parent is None:
        win.mainloop()
    else:
        try:
            win.grab_set()
        except Exception:
            pass
        parent.wait_window(win)


def show_info(title: str, text: str, parent: "tk.Misc | None" = None) -> None:
    _show_dialog(title, text, headline_fg=FG, parent=parent)


def show_error(title: str, text: str, parent: "tk.Misc | None" = None) -> None:
    _show_dialog(title, text, headline_fg=ERR_FG, parent=parent)


def show_rich_info(title: str, headline: str, details: str = "",
                   parent: "tk.Misc | None" = None) -> None:
    """Büyük başlık + kota satırı — giriş/çıkış başarı ekranı."""
    has_details = bool(details and details.strip())
    height = 220 if has_details else 180

    win = _make_dark_win(title, 460, height, parent)
    panel = _dark_panel(win)

    lbl_head = tk.Label(
        panel, text=headline,
        font=("Segoe UI", 16, "bold"), fg=FG, bg=PANEL,
        justify="center",
    )
    lbl_head.pack(fill="x", pady=(28, 8))

    if has_details:
        lbl_sub = tk.Label(
            panel, text=details,
            font=("Segoe UI", 12, "bold"), fg=MUTED, bg=PANEL,
            justify="center",
        )
        lbl_sub.pack(fill="x", pady=(0, 10))

    actions = tk.Frame(panel, bg=PANEL)
    actions.pack(fill="x", side="bottom", padx=14, pady=(0, 14))

    def close():
        try:
            win.destroy()
        except Exception:
            pass

    btn = _dark_button(actions, "Tamam", close)
    btn.pack(side="right")
    win.protocol("WM_DELETE_WINDOW", close)
    try:
        btn.focus_set()
    except Exception:
        pass

    if parent is None:
        win.mainloop()
    else:
        try:
            win.grab_set()
        except Exception:
            pass
        parent.wait_window(win)
