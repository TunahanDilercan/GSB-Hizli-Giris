import json
import sys
from pathlib import Path


def base_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


def cfg_dir() -> Path:
    d = base_dir() / "GSB_Dosyalar"
    d.mkdir(parents=True, exist_ok=True)
    return d


def cfg_path(account_id: int) -> Path:
    return cfg_dir() / f"config_giris{account_id}.json"


def main() -> None:
    print("==== GSB Ayar ====")
    print("1) 1. hesap bilgisi kaydet")
    print("2) 2. hesap bilgisi kaydet")
    choice = input("Seçim (1/2): ").strip()

    if choice not in {"1", "2"}:
        print("Geçersiz seçim.")
        return

    account_id = int(choice)

    username = input("TC/username: ").strip()
    password = input("Şifre: ").strip()

    if not username or not password:
        print("TC ve şifre boş olamaz.")
        return

    path = cfg_path(account_id)
    path.write_text(json.dumps({"username": username, "password": password}, ensure_ascii=False), encoding="utf-8")
    print(f"✅ Kaydedildi: {path}")


if __name__ == "__main__":
    main()
