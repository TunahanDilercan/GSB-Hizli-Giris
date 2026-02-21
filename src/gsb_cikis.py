import socket
import time

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from gsb_ui import run_with_status, show_error, show_info, show_rich_info

PORTAL_URL = "https://wifi.gsb.gov.tr/"
LOGOUT_URL = "https://wifi.gsb.gov.tr/logout"

CONNECT_TIMEOUT = 4
READ_TIMEOUT = 8
MAX_ATTEMPT = 4


def _looks_like_login_page(html_text: str, url: str = "") -> bool:
    body = (html_text or "").lower()
    url_l = (url or "").lower()
    return (
        "j_spring_security_check" in body
        or "j_username" in body
        or "name=\"j_username\"" in body
        or "login.html" in url_l
        or "/login" in url_l
    )


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
        {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "tr-TR,tr;q=0.9,en-US;q=0.8,en;q=0.7",
            "Connection": "keep-alive",
        }
    )
    return session


def dns_precheck(url: str) -> None:
    host = url.split("//", 1)[-1].split("/", 1)[0]
    socket.getaddrinfo(host, 443)


def do_logout():
    try:
        try:
            dns_precheck(LOGOUT_URL)
        except Exception:
            # DNS sorun olsa bile deneyelim
            pass

        session = build_session()

        last_info = ""
        for attempt in range(1, MAX_ATTEMPT + 1):
            resp = session.get(
                LOGOUT_URL,
                timeout=(CONNECT_TIMEOUT, READ_TIMEOUT),
                allow_redirects=True,
                headers={"Referer": PORTAL_URL},
            )

            last_info = f"HTTP {resp.status_code} | final: {resp.url}"
            url_l = resp.url.lower()

            if resp.status_code not in (200, 302, 303):
                time.sleep(min(0.6 * attempt, 2.0))
                continue

            # Net logout sayfası/hinti
            if "logout=1" in url_l or "cikisson" in url_l or "cikis" in url_l:
                return True, "Çıkış başarılı."

            # Login sayfasına düştüysek: ya çıkış yapıldı ya da zaten giriş yok.
            if _looks_like_login_page(resp.text, resp.url):
                # Bu durumda kullanıcıya net bilgi verelim.
                return False, "Çıkış yapılamadı: Aktif oturum bulunamadı (zaten çıkış yapılmış olabilir)."

            # Son kontrol: portal ana sayfası login'e düşüyorsa (oturum yok)
            try:
                check = session.get(PORTAL_URL, timeout=(CONNECT_TIMEOUT, READ_TIMEOUT), allow_redirects=True)
                if _looks_like_login_page(check.text, check.url):
                    return True, "Çıkış başarılı."
            except Exception:
                pass

            time.sleep(min(0.6 * attempt, 2.0))

        return False, f"Çıkış yapılamadı: Sistem beklenen yanıtı vermedi. ({last_info})"
    except Exception as exc:  # noqa: BLE001
        return False, f"Çıkış yapılamadı: Sistem hatası ({exc})."


def main() -> None:
    result = run_with_status("GSB Çıkış", "Çıkış yapılıyor...", do_logout)
    if not result:
        return

    ok, msg = result
    if ok:
        show_rich_info("GSB Çıkış", "✅ Çıkış yapıldı", msg)
    else:
        show_error("GSB Çıkış", f"⛔ {msg}")


if __name__ == "__main__":
    main()
