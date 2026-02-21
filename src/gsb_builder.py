import getpass
import subprocess
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

DESKTOP = Path.home() / "Desktop"

# Her şey tek klasörde: Desktop\GSB\
BASE_DIR = DESKTOP / "GSB"
ASSETS_DIR = BASE_DIR / "GSB_Dosyalar"
ICONS_DIR = ASSETS_DIR / "icons"
TEMP_DIR = ASSETS_DIR / "temp"
OUTPUT_DIR = BASE_DIR

LOGO_PNG = ICONS_DIR / "favicon.png"

PORTAL_URL = "https://wifi.gsb.gov.tr"
LOGIN_PAGE_URL = "https://wifi.gsb.gov.tr/login.html"
AUTH_URL = "https://wifi.gsb.gov.tr/j_spring_security_check"
LOGOUT_URL = "https://wifi.gsb.gov.tr/logout"


LOGIN_TEMPLATE = '''
import re
import socket
import time
from typing import Dict, List
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

USERNAME = {username}
PASSWORD = {password}
LOGIN_PAGE_URL = {login_page_url}
AUTH_URL = {auth_url}
QUOTA_URL = ""

CONNECT_TIMEOUT = 4
READ_TIMEOUT = 8
MAX_LOGIN_ATTEMPT = 4


def build_session() -> requests.Session:
    session = requests.Session()

    retries = Retry(
        total=5,
        connect=5,
        read=3,
        backoff_factor=0.4,
        status_forcelist=[429, 500, 502, 503, 504],
        allowed_methods=["GET", "POST"],
    )
    adapter = HTTPAdapter(max_retries=retries, pool_connections=10, pool_maxsize=10)
    session.mount("http://", adapter)
    session.mount("https://", adapter)

    session.trust_env = False
    session.headers.update(
        {{
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "tr-TR,tr;q=0.9,en-US;q=0.8,en;q=0.7",
            "Connection": "keep-alive",
        }}
    )
    return session


def extract_hidden_inputs(html_text: str) -> Dict[str, str]:
    soup = BeautifulSoup(html_text, "html.parser")
    data: Dict[str, str] = {{}}
    for element in soup.select("input[type='hidden'][name]"):
        data[element.get("name", "")] = element.get("value", "")
    return data


def resolve_auth_url(html_text: str, fallback_url: str) -> str:
    if AUTH_URL:
        return AUTH_URL

    soup = BeautifulSoup(html_text, "html.parser")
    form = soup.find("form")
    if not form:
        return urljoin(fallback_url, "/j_spring_security_check")

    action = (form.get("action") or "").strip()
    if not action:
        return urljoin(fallback_url, "/j_spring_security_check")

    return urljoin(fallback_url, action)


def extract_quota_info(html_text: str) -> str:
    soup = BeautifulSoup(html_text, "html.parser")
    plain_text = " ".join(soup.stripped_strings)

    patterns = [
        r"(kalan\\s*kota[^\\d]{{0,20}}\\d+[\\.,]?\\d*\\s*(?:mb|gb))",
        r"(kota[^\\d]{{0,20}}\\d+[\\.,]?\\d*\\s*(?:mb|gb))",
        r"(kullan[ıi]m[^\\d]{{0,20}}\\d+[\\.,]?\\d*\\s*(?:mb|gb))",
    ]

    for pattern in patterns:
        match = re.search(pattern, plain_text, flags=re.IGNORECASE)
        if match:
            return match.group(1)

    return "Kota bilgisi HTML içinde otomatik bulunamadı."


def discover_quota_urls(html_text: str, base_url: str) -> List[str]:
    soup = BeautifulSoup(html_text, "html.parser")
    keywords = ("kota", "kalan", "kullanım", "kullanim", "internet", "paket")
    urls: List[str] = []

    def add_url(raw_url: str) -> None:
        if not raw_url:
            return
        full = urljoin(base_url, raw_url.strip())
        if full.startswith("javascript:"):
            return
        if full not in urls:
            urls.append(full)

    for link in soup.find_all("a", href=True):
        label = f"{{link.get_text(' ', strip=True)}} {{link.get('href', '')}}".lower()
        if any(word in label for word in keywords):
            add_url(link.get("href", ""))

    for form in soup.find_all("form"):
        action = form.get("action", "")
        label = f"{{form.get_text(' ', strip=True)}} {{action}}".lower()
        if any(word in label for word in keywords):
            add_url(action)

    for element in soup.find_all(attrs={{"onclick": True}}):
        onclick = element.get("onclick", "")
        if any(word in onclick.lower() for word in keywords):
            match = re.search(r"['\"]([^'\"]+)['\"]", onclick)
            if match:
                add_url(match.group(1))

    return urls


def print_quota_info(session: requests.Session, login_response_text: str, current_url: str) -> None:
    print("\\n--- Kota Bilgisi ---")
    initial = extract_quota_info(login_response_text)
    print(initial)

    candidate_urls: List[str] = []
    if QUOTA_URL:
        candidate_urls.append(QUOTA_URL)

    candidate_urls.extend(discover_quota_urls(login_response_text, current_url))

    if initial == "Kota bilgisi HTML içinde otomatik bulunamadı." and candidate_urls:
        print("Aday kota sayfaları kontrol ediliyor...")

    for candidate in candidate_urls[:8]:
        try:
            quota_resp = session.get(
                candidate,
                timeout=(CONNECT_TIMEOUT, READ_TIMEOUT),
                allow_redirects=True,
            )
            quota_resp.raise_for_status()
            parsed = extract_quota_info(quota_resp.text)
            if parsed != "Kota bilgisi HTML içinde otomatik bulunamadı.":
                print(f"Kota bulundu ({{candidate}}): {{parsed}}")
                return
        except Exception as exc:
            print(f"Kota adayı okunamadı ({{candidate}}): {{exc}}")


def login_once(session: requests.Session) -> bool:
    start = time.perf_counter()

    login_page = session.get(
        LOGIN_PAGE_URL,
        timeout=(CONNECT_TIMEOUT, READ_TIMEOUT),
        allow_redirects=True,
    )
    login_page.raise_for_status()

    auth_url = resolve_auth_url(login_page.text, LOGIN_PAGE_URL)

    payload = extract_hidden_inputs(login_page.text)
    payload.update(
        {{
            "j_username": USERNAME,
            "j_password": PASSWORD,
            "submit": "Login",
        }}
    )

    response = session.post(
        auth_url,
        data=payload,
        timeout=(CONNECT_TIMEOUT, READ_TIMEOUT),
        allow_redirects=True,
        headers={{"Referer": LOGIN_PAGE_URL, "Content-Type": "application/x-www-form-urlencoded"}},
    )

    elapsed = time.perf_counter() - start

    body_lower = response.text.lower()
    login_form_back = "j_spring_security_check" in body_lower or "j_username" in body_lower
    success = response.status_code in (200, 302, 303) and not login_form_back

    print(f"Durum: {{response.status_code}} | Süre: {{elapsed:.2f}}s | POST: {{auth_url}}")
    if success:
        print_quota_info(session, response.text, response.url)
    return success


def dns_precheck(url: str) -> None:
    host = url.split("//", 1)[-1].split("/", 1)[0]
    socket.getaddrinfo(host, 443)


def fast_login() -> None:
    try:
        dns_precheck(LOGIN_PAGE_URL)
    except Exception:
        print("⚠️ DNS çözümü başarısız. Bağlı ağda bu normal olabilir, denemeye devam ediliyor...")

    session = build_session()

    for attempt in range(1, MAX_LOGIN_ATTEMPT + 1):
        try:
            print(f"Giriş deneniyor ({{attempt}}/{{MAX_LOGIN_ATTEMPT}})...")
            if login_once(session):
                print("✅ Giriş başarılı")
                return
            print("⚠️ Giriş doğrulanamadı, tekrar denenecek...")
        except Exception as exc:
            print(f"❌ Hata: {{exc}}")

        time.sleep(min(0.6 * attempt, 2.0))

    print("⛔ Maksimum deneme sayısına ulaşıldı.")


if __name__ == "__main__":
    fast_login()
'''


LOGOUT_TEMPLATE = '''
import socket
import time

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

PORTAL_URL = {portal_url}
LOGOUT_URL = {logout_url}
CONNECT_TIMEOUT = 4
READ_TIMEOUT = 8
MAX_ATTEMPT = 4


def build_session() -> requests.Session:
    session = requests.Session()

    retries = Retry(
        total=5,
        connect=5,
        read=3,
        backoff_factor=0.4,
        status_forcelist=[429, 500, 502, 503, 504],
        allowed_methods=["GET", "POST"],
    )
    adapter = HTTPAdapter(max_retries=retries, pool_connections=10, pool_maxsize=10)
    session.mount("http://", adapter)
    session.mount("https://", adapter)

    session.trust_env = False
    session.headers.update(
        {{
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "tr-TR,tr;q=0.9,en-US;q=0.8,en;q=0.7",
            "Connection": "keep-alive",
        }}
    )
    return session


def dns_precheck(url: str) -> None:
    host = url.split("//", 1)[-1].split("/", 1)[0]
    socket.getaddrinfo(host, 443)


def logout_flow() -> None:
    try:
        dns_precheck(PORTAL_URL)
    except Exception:
        print("⚠️ DNS çözümü başarısız, yine de çıkış denenecek...")

    session = build_session()

    for attempt in range(1, MAX_ATTEMPT + 1):
        try:
            print(f"Çıkış deneniyor ({{attempt}}/{{MAX_ATTEMPT}})...")
            response = session.get(
                LOGOUT_URL,
                timeout=(CONNECT_TIMEOUT, READ_TIMEOUT),
                allow_redirects=True,
                headers={{"Referer": PORTAL_URL}},
            )
            final_url = response.url
            print(f"Durum: {{response.status_code}} | Final URL: {{final_url}}")

            if response.status_code in (200, 302, 303):
                print("✅ Çıkış başarılı")
                return

            print("⚠️ Çıkış doğrulanamadı, tekrar denenecek...")
        except Exception as exc:
            print(f"❌ Hata: {{exc}}")

        time.sleep(min(0.6 * attempt, 2.0))

    print("⛔ Çıkış yapılamadı.")


if __name__ == "__main__":
    logout_flow()
'''


def ensure_dirs() -> None:
    BASE_DIR.mkdir(parents=True, exist_ok=True)
    ICONS_DIR.mkdir(parents=True, exist_ok=True)
    TEMP_DIR.mkdir(parents=True, exist_ok=True)


def load_font(size: int) -> ImageFont.ImageFont:
    try:
        return ImageFont.truetype("arial.ttf", size)
    except Exception:
        return ImageFont.load_default()


def load_logo_image() -> Image.Image:
    if not LOGO_PNG.exists():
        raise FileNotFoundError(f"Logo PNG bulunamadı: {LOGO_PNG}")
    logo = Image.open(LOGO_PNG).convert("RGBA")
    return logo


def create_themed_icon(
    output_ico_path: Path,
    theme: str,
    badge_text: str | None = None,
) -> None:
    size = 256
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    if theme == "login":
        outer = (11, 117, 59, 255)
        inner = (16, 150, 76, 255)
    elif theme == "logout":
        outer = (190, 24, 24, 255)
        inner = (220, 38, 38, 255)
    else:
        raise ValueError("theme must be 'login' or 'logout'")

    draw.ellipse((8, 8, 248, 248), fill=outer)
    draw.ellipse((28, 28, 228, 228), fill=inner)

    logo = load_logo_image()
    # Logoyu iç dairenin içine sığdır
    max_logo = 150
    logo.thumbnail((max_logo, max_logo), Image.Resampling.LANCZOS)
    x = (size - logo.width) // 2
    y = (size - logo.height) // 2
    img.alpha_composite(logo, (x, y))

    if badge_text:
        # Köşeye rozet (beyaz kenarlıklı kırmızı daire + beyaz yazı)
        badge_outer = (255, 255, 255, 255)
        badge_inner = (220, 38, 38, 255)
        bx0, by0, bx1, by1 = (164, 12, 248, 96)
        draw.ellipse((bx0, by0, bx1, by1), fill=badge_outer)
        draw.ellipse((bx0 + 4, by0 + 4, bx1 - 4, by1 - 4), fill=badge_inner)

        font = load_font(48)
        cx = (bx0 + bx1) // 2
        cy = (by0 + by1) // 2
        bbox = draw.textbbox((0, 0), badge_text, font=font)
        tw = bbox[2] - bbox[0]
        th = bbox[3] - bbox[1]
        draw.text((cx - tw / 2, cy - th / 2 - 2), badge_text, fill=(255, 255, 255, 255), font=font)

    # Pillow ICO için çoklu boyut desteğini `sizes=` ile sağlar.
    # (PIL'de frame olarak görünmeyebilir ama ICO içinde gömülür.)
    img.save(
        output_ico_path,
        format="ICO",
        sizes=[(256, 256), (128, 128), (64, 64), (32, 32), (16, 16)],
    )


def create_login_icon(path: Path, with_badge_two: bool = False) -> None:
    create_themed_icon(path, theme="login", badge_text="2" if with_badge_two else None)


def create_logout_icon(path: Path) -> None:
    create_themed_icon(path, theme="logout", badge_text=None)


def build_exe(script_content: str, exe_name: str, icon_path: Path) -> bool:
    script_path = TEMP_DIR / f"{exe_name}.py"
    script_path.write_text(script_content, encoding="utf-8")

    cmd = [
        sys.executable,
        "-m",
        "PyInstaller",
        "--onefile",
        "--name",
        exe_name,
        "--icon",
        str(icon_path),
        "--distpath",
        str(OUTPUT_DIR),
        "--workpath",
        str(TEMP_DIR / f"build_{exe_name}"),
        "--specpath",
        str(TEMP_DIR),
        str(script_path),
    ]

    print("\nBuild başlatıldı:", " ".join(cmd))
    result = subprocess.run(cmd)
    if result.returncode == 0:
        print(f"✅ EXE hazır: {OUTPUT_DIR / (exe_name + '.exe')}")
        return True

    print("⛔ Build başarısız.")
    return False


def create_giris(version: int) -> None:
    tc = input("TC/username gir: ").strip()
    sifre = getpass.getpass("Şifre gir (gizli): ").strip()

    if not tc or not sifre:
        print("⛔ TC ve şifre boş olamaz.")
        return

    exe_name = "GSB_Giriş" if version == 1 else "GSB_Giriş2"
    icon_path = ICONS_DIR / ("GSB_Giris.ico" if version == 1 else "GSB_Giris2.ico")
    create_login_icon(icon_path, with_badge_two=(version == 2))

    script_content = LOGIN_TEMPLATE.format(
        username=repr(tc),
        password=repr(sifre),
        login_page_url=repr(LOGIN_PAGE_URL),
        auth_url=repr(AUTH_URL),
    )

    build_exe(script_content, exe_name, icon_path)


def create_cikis() -> None:
    exe_name = "GSB_Çıkış"
    icon_path = ICONS_DIR / "GSB_Cikis.ico"
    create_logout_icon(icon_path)

    script_content = LOGOUT_TEMPLATE.format(
        portal_url=repr(PORTAL_URL),
        logout_url=repr(LOGOUT_URL),
    )

    build_exe(script_content, exe_name, icon_path)


def menu() -> None:
    ensure_dirs()

    while True:
        print("\n==== GSB EXE OLUŞTURUCU ====")
        print("1) GSB_Giriş oluştur")
        print("2) GSB_Giriş2 oluştur")
        print("3) GSB_Çıkış oluştur")
        print("4) Çık")
        choice = input("Seçim: ").strip()

        if choice == "1":
            create_giris(version=1)
        elif choice == "2":
            create_giris(version=2)
        elif choice == "3":
            create_cikis()
        elif choice == "4":
            print("Çıkılıyor...")
            return
        else:
            print("Geçersiz seçim.")


if __name__ == "__main__":
    menu()
