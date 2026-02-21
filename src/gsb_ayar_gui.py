import json
import subprocess
import sys
import tempfile
import uuid
from pathlib import Path
import ctypes
from ctypes import wintypes

import tkinter as tk
from tkinter import messagebox

from gsb_ui import center_window, run_with_status, show_error, show_info

from PIL import Image, ImageTk


def base_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    # Source run: this file lives in ...\GSB_Dosyalar\src\
    return Path(__file__).resolve().parents[2]


def gsb_root() -> Path:
    # GSB.exe Desktop\\GSB altında
    return base_dir()


def system_root() -> Path:
    """User-facing root stays clean.

    Preferred layout:
    - Desktop\\GSB\\GSB.exe
    - Desktop\\GSB_Sistem\\(GSB_Dosyalar, Uygulama, build, ...)

    Backward compatible with old layout where GSB_Dosyalar was under gsb_root().
    """
    root = gsb_root()
    legacy_assets = root / "GSB_Dosyalar"
    sibling = root.parent / "GSB_Sistem"

    if legacy_assets.exists():
        return root

    sibling.mkdir(parents=True, exist_ok=True)
    return sibling


def cfg_dir() -> Path:
    d = system_root() / "GSB_Dosyalar"
    d.mkdir(parents=True, exist_ok=True)
    return d


def cfg_path(account_id: int) -> Path:
    return cfg_dir() / f"config_giris{account_id}.json"


def get_icon_path() -> "Path | None":
    """Find icon.ico or icon.png in standard locations."""
    candidates = [
        cfg_dir() / "icons" / "icon.ico",           # primary ICO (GSB_Sistem/GSB_Dosyalar/icons/)
        cfg_dir() / "icons" / "GSB_Giris.ico",      # fallback ICO
        cfg_dir() / "icons" / "favicon.png",        # primary PNG
        cfg_dir() / "icons" / "icon.png",           # alt PNG
        base_dir().parent / "GSB_Sistem" / "GSB_Dosyalar" / "icons" / "icon.ico",  # Layout A
        base_dir().parent / "GSB_Sistem" / "GSB_Dosyalar" / "icons" / "favicon.png",
        base_dir() / "assets" / "icons" / "icon.ico",  # dev env
        base_dir() / "assets" / "icons" / "icon.png",
    ]
    for c in candidates:
        if c.exists():
            return c
    return None


def create_shortcut(shortcut_name: str, target_path: Path, icon_path: Path) -> None:
    desktop = Path.home() / "Desktop"
    lnk = desktop / f"{shortcut_name}.lnk"

    # PowerShell bazı sistemlerde arkaplanda da olsa konsol penceresi gösterebiliyor.
    # Bu yüzden VBS + wscript ile (GUI mod) kısayol oluştur.
    vbs_lines = [
        'Set oWS = CreateObject("WScript.Shell")',
        f'Set oLnk = oWS.CreateShortcut("{str(lnk)}")',
        f'oLnk.TargetPath = "{str(target_path)}"',
        f'oLnk.WorkingDirectory = "{str(target_path.parent)}"',
        f'oLnk.IconLocation = "{str(icon_path)}"',
        'oLnk.Save',
    ]

    vbs_path = Path(tempfile.gettempdir()) / f"gsb_mklnk_{uuid.uuid4().hex}.vbs"
    # wscript.exe VBS dosyalarını pratikte ANSI/UTF-16 ile sorunsuz okur;
    # UTF-8 (BOM'suz) bazı sistemlerde Türkçe karakterleri bozabiliyor.
    vbs_path.write_text("\r\n".join(vbs_lines) + "\r\n", encoding="utf-16")
    try:
        creationflags = 0
        startupinfo = None
        try:
            creationflags = subprocess.CREATE_NO_WINDOW
            startupinfo = subprocess.STARTUPINFO()
            startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            startupinfo.wShowWindow = 0
        except Exception:
            pass

        r = subprocess.run(
            ["wscript.exe", "//nologo", str(vbs_path)],
            capture_output=True,
            text=True,
            creationflags=creationflags,
            startupinfo=startupinfo,
        )
        if r.returncode != 0:
            raise RuntimeError((r.stderr or r.stdout or "Kısayol oluşturulamadı").strip())
    finally:
        try:
            vbs_path.unlink(missing_ok=True)
        except Exception:
            pass


def shortcut_path(shortcut_name: str) -> Path:
    return (Path.home() / "Desktop") / f"{shortcut_name}.lnk"


def main() -> None:
    root = tk.Tk()
    root.title("GSB Bağlantı Ayarları")
    root.resizable(False, False)
    # Daha kompakt (header tamamen kaldırıldı)
    center_window(root, 430, 320)

    BG = "#0f172a"
    PANEL = "#111827"
    FG = "#e5e7eb"
    MUTED = "#cbd5e1"
    ENTRY_BG = "#0b1220"
    ENTRY_FG = "#f9fafb"
    BTN_BG = "#1f2937"
    BTN_FG = "#f9fafb"
    HEADER_BG = "#0b1220"
    HEADER_FG = "#f9fafb"
    BORDER = "#334155"
    ACC_OFF_BG = "#0b1220"
    ACC_ON_BG = "#334155"

    root.configure(bg=BG)

    # Windows title bar (kapat/küçült alanı) rengi: best-effort
    def _hex_to_bgr_dword(hex_color: str) -> int:
        # '#RRGGBB' -> 0x00BBGGRR
        hex_color = hex_color.lstrip("#")
        r = int(hex_color[0:2], 16)
        g = int(hex_color[2:4], 16)
        b = int(hex_color[4:6], 16)
        return (b << 16) | (g << 8) | r

    def _set_windows_titlebar() -> None:
        if sys.platform != "win32":
            return
        try:
            hwnd = wintypes.HWND(root.winfo_id())
            dwm = ctypes.windll.dwmapi

            # Dark mode (Win10/11) - DWMWA_USE_IMMERSIVE_DARK_MODE
            for attr in (20, 19):
                value = wintypes.BOOL(1)
                dwm.DwmSetWindowAttribute(hwnd, attr, ctypes.byref(value), ctypes.sizeof(value))

            # Caption color (Win11) - DWMWA_CAPTION_COLOR
            caption = wintypes.DWORD(_hex_to_bgr_dword(HEADER_BG))
            dwm.DwmSetWindowAttribute(hwnd, 35, ctypes.byref(caption), ctypes.sizeof(caption))

            # Text color (Win11) - DWMWA_TEXT_COLOR
            text = wintypes.DWORD(_hex_to_bgr_dword("#f9fafb"))
            dwm.DwmSetWindowAttribute(hwnd, 36, ctypes.byref(text), ctypes.sizeof(text))
        except Exception:
            return

    # Açılışta kısa fade-in (daha profesyonel görünüm)
    try:
        root.attributes("-alpha", 0.0)
        def _fade(step: int = 0) -> None:
            alpha = min(1.0, 0.15 + step * 0.12)
            root.attributes("-alpha", alpha)
            if alpha < 1.0:
                root.after(16, lambda: _fade(step + 1))
        root.after(10, _fade)
    except Exception:
        pass

    # Pencere handle hazır olunca title bar ayarla
    root.after(60, _set_windows_titlebar)

    # Pencere ikonu - after() ile pencere hazır olduktan sonra yükle
    def _set_icon() -> None:
        icon_p = get_icon_path()
        if not icon_p:
            return
        try:
            if str(icon_p).endswith('.ico'):
                root.iconbitmap(str(icon_p))
            else:
                logo_img = Image.open(icon_p).convert("RGBA")
                logo_img.thumbnail((32, 32), Image.Resampling.LANCZOS)
                logo_tk = ImageTk.PhotoImage(logo_img)
                root.iconphoto(True, logo_tk)
                root._logo_ref = logo_tk  # type: ignore[attr-defined]
        except Exception:
            pass
    root.after(1, _set_icon)

    panel_outer = tk.Frame(root, bg=BORDER)
    panel_outer.pack(fill="both", expand=True, padx=14, pady=12)
    panel = tk.Frame(panel_outer, bg=PANEL)
    panel.pack(fill="both", expand=True, padx=1, pady=1)

    tk.Label(panel, text="Hesap", font=("Segoe UI", 10, "bold"), fg=FG, bg=PANEL).grid(
        row=0, column=0, sticky="w", padx=14, pady=(14, 6)
    )
    account_var = tk.StringVar(value="1")

    # Hesap seçimi (buton gibi)
    account_frame = tk.Frame(panel, bg=PANEL)
    account_frame.grid(row=0, column=1, columnspan=2, sticky="w", pady=(12, 6), padx=(0, 14))

    btn_style = {
        "font": ("Segoe UI", 9, "bold"),
        "fg": BTN_FG,
        "activeforeground": BTN_FG,
        "relief": "flat",
        "bd": 0,
        "highlightthickness": 0,
        "padx": 12,
        "pady": 6,
    }

    def apply_account_styles() -> None:
        selected = account_var.get()
        if selected == "1":
            btn_acc1.configure(bg=ACC_ON_BG, activebackground=ACC_ON_BG)
            btn_acc2.configure(bg=ACC_OFF_BG, activebackground=ACC_OFF_BG)
        else:
            btn_acc1.configure(bg=ACC_OFF_BG, activebackground=ACC_OFF_BG)
            btn_acc2.configure(bg=ACC_ON_BG, activebackground=ACC_ON_BG)

    def set_account(value: str) -> None:
        account_var.set(value)
        apply_account_styles()

    btn_acc1 = tk.Button(account_frame, text="1. Hesap", command=lambda: set_account("1"), **btn_style)
    btn_acc2 = tk.Button(account_frame, text="2. Hesap", command=lambda: set_account("2"), **btn_style)

    # 2. hesap çok kişi tarafından kullanıldığı için varsayılan gizli.
    show_second = {"value": False}

    def toggle_second() -> None:
        show_second["value"] = not show_second["value"]
        if show_second["value"]:
            btn_acc2.pack(side="left", padx=(10, 0))
            btn_plus.configure(text="–")
        else:
            # 2. hesap seçiliyse 1'e dön
            if account_var.get() == "2":
                set_account("1")
            btn_acc2.pack_forget()
            btn_plus.configure(text="+")

        apply_account_styles()

    btn_acc1.pack(side="left")

    btn_plus = tk.Button(
        account_frame,
        text="+",
        command=toggle_second,
        bg=ACC_OFF_BG,
        fg=BTN_FG,
        activebackground=ACC_ON_BG,
        activeforeground=BTN_FG,
        relief="flat",
        bd=0,
        highlightthickness=0,
        padx=10,
        pady=6,
        font=("Segoe UI", 9, "bold"),
    )
    btn_plus.pack(side="left", padx=(10, 0))

    # btn_acc2 burada pack edilmez (gizli başlar)
    apply_account_styles()

    tk.Label(panel, text="TC", font=("Segoe UI", 10), fg=FG, bg=PANEL).grid(
        row=1, column=0, sticky="w", padx=14, pady=(10, 6)
    )
    # Daha modern giriş kutusu: border + padding
    user_outer = tk.Frame(panel, bg=BORDER)
    user_outer.grid(row=1, column=1, columnspan=2, sticky="we", padx=(0, 14), pady=(10, 6))
    user_inner = tk.Frame(user_outer, bg=ENTRY_BG)
    user_inner.pack(fill="both", expand=True, padx=1, pady=1)
    username = tk.Entry(
        user_inner,
        bg=ENTRY_BG,
        fg=ENTRY_FG,
        insertbackground=ENTRY_FG,
        relief="flat",
        bd=0,
        highlightthickness=0,
        font=("Segoe UI", 10),
    )
    username.pack(fill="x", padx=10, pady=8)

    tk.Label(panel, text="Şifre", font=("Segoe UI", 10), fg=FG, bg=PANEL).grid(
        row=2, column=0, sticky="w", padx=14, pady=(0, 6)
    )
    pass_outer = tk.Frame(panel, bg=BORDER)
    pass_outer.grid(row=2, column=1, columnspan=2, sticky="we", padx=(0, 14), pady=(0, 6))
    pass_inner = tk.Frame(pass_outer, bg=ENTRY_BG)
    pass_inner.pack(fill="both", expand=True, padx=1, pady=1)
    password = tk.Entry(
        pass_inner,
        show="*",
        bg=ENTRY_BG,
        fg=ENTRY_FG,
        insertbackground=ENTRY_FG,
        relief="flat",
        bd=0,
        highlightthickness=0,
        font=("Segoe UI", 10),
    )
    password.pack(fill="x", padx=10, pady=8)

    def save():
        acc = int(account_var.get())
        u = username.get().strip()
        p = password.get().strip()
        if not u or not p:
            messagebox.showerror("GSB", "TC ve şifre boş olamaz")
            return

        def task():
            path = cfg_path(acc)
            path.write_text(json.dumps({"username": u, "password": p}, ensure_ascii=False), encoding="utf-8")

            # Seçilen hesap için masaüstüne kısayol oluştur
            sys_root = system_root()
            icons = sys_root / "GSB_Dosyalar" / "icons"
            app = sys_root / "Uygulama"

            if acc == 1:
                # 1. hesap: giriş kısayolu her zaman güncellensin (son kayıt geçerli)
                create_shortcut("GSB_Hızlı Giriş", app / "GSB_Giris.exe", icons / "GSB_Giris.ico")

                # Çıkış kısayolu sadece bir kere oluşturulsun
                if not shortcut_path("GSB_Çıkış").exists():
                    create_shortcut("GSB_Çıkış", app / "GSB_Cikis.exe", icons / "GSB_Cikis.ico")
            else:
                # 2. hesap: sadece kendi giriş kısayolunu güncelle; çıkış kısayoluna dokunma
                create_shortcut("GSB_Hızlı Giriş 2", app / "GSB_Giris2.exe", icons / "GSB_Giris2.ico")

            return True

        try:
            ok = run_with_status("GSB", "Kaydediliyor...", task, parent=root)
            if ok:
                show_info("GSB", "✅ Kaydedildi", parent=root)
                # Bildirimden sonra otomatik kapat
                try:
                    root.destroy()
                except Exception:
                    pass
            else:
                show_error("GSB", "❌ Kaydedilemedi", parent=root)
        except Exception as e:
            show_error("GSB", f"❌ Hata: {e}", parent=root)

    actions = tk.Frame(panel, bg=PANEL)
    actions.grid(row=3, column=0, columnspan=3, sticky="e", padx=14, pady=(10, 6))

    tk.Button(
        actions,
        text="Kaydet",
        width=12,
        command=save,
        bg=BTN_BG,
        fg=BTN_FG,
        activebackground=BTN_BG,
        activeforeground=BTN_FG,
        relief="flat",
    ).pack(side="right", padx=(8, 0))
    tk.Button(
        actions,
        text="Kapat",
        width=12,
        command=root.destroy,
        bg=BTN_BG,
        fg=BTN_FG,
        activebackground=BTN_BG,
        activeforeground=BTN_FG,
        relief="flat",
    ).pack(side="right")

    note = (
        "Kaydettikten sonra masaüstüne hızlı giriş kısayolu oluşturulacaktır.\n"
        "Bu uygulama, GSB WiFi giriş sitesinin yüklenmesini bekleme gibi gecikmeler yaşanmaması için tasarlanmıştır.\n"
        "Şifreniz yalnızca bu bilgisayarda yerel dosyada saklanır ve internete gönderilmez."
    )

    # Not alanı: responsive sarma + tam görünürlük
    note_msg = tk.Message(
        panel,
        text=note,
        font=("Segoe UI", 9),
        fg=MUTED,
        bg=PANEL,
        justify="left",
        width=380,
    )
    note_msg.grid(row=4, column=0, columnspan=3, sticky="we", padx=14, pady=(6, 14))

    def _update_note_wrap(_event=None) -> None:
        # panel iç genişliğine göre sarma (padding'i düş)
        try:
            w = max(260, panel.winfo_width() - 40)
            note_msg.configure(width=w)
        except Exception:
            pass

    panel.bind("<Configure>", _update_note_wrap)

    panel.grid_columnconfigure(1, weight=1)
    panel.grid_columnconfigure(2, weight=1)

    username.focus_set()

    root.mainloop()


if __name__ == "__main__":
    main()
