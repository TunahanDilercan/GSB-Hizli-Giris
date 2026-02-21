import json
import os
import re
import socket
import sys
import time
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from gsb_ui import run_with_status, show_error, show_info, show_rich_info

# Builder tarafından replace edilir: 1 veya 2
ACCOUNT_ID = 1

PORTAL_URL = "https://wifi.gsb.gov.tr"
LOGIN_PAGE_URL = "https://wifi.gsb.gov.tr/login.html"
AUTH_URL = ""  # boşsa form action'dan bulunur

CONNECT_TIMEOUT = 4
READ_TIMEOUT = 8
MAX_LOGIN_ATTEMPT = 4

# SSID kontrolü sadece "ön bilgilendirme" içindir; portal erişimi asıl doğrulamadır.
WIFI_SSID_HINTS = ("GSBWIFI",)


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


def app_base_dir() -> Path:
    # PyInstaller onefile'da kullanıcıya görünen exe klasörü
    if getattr(sys, "frozen", False):
        exe_dir = Path(sys.executable).resolve().parent
        # Preferred layout:
        # - Desktop\GSB\GSB.exe
        # - Desktop\GSB_Sistem\Uygulama\(GSB_Giris.exe, ...)
        # - Desktop\GSB_Sistem\GSB_Dosyalar\config_*.json

        # 1) If we're inside ...\GSB_Sistem\Uygulama
        if (exe_dir.parent / "GSB_Dosyalar").exists():
            return exe_dir.parent

        # 2) If we're directly inside ...\GSB_Sistem
        if (exe_dir / "GSB_Dosyalar").exists():
            return exe_dir

        # 3) If we're next to Desktop\GSB, look for Desktop\GSB_Sistem
        sibling = exe_dir.parent / "GSB_Sistem"
        if (sibling / "GSB_Dosyalar").exists():
            return sibling

        # 4) Backward-compatible legacy layout (GSB_Dosyalar next to EXE or parent)
        if (exe_dir / "GSB_Dosyalar").exists():
            return exe_dir
        if (exe_dir.parent / "GSB_Dosyalar").exists():
            return exe_dir.parent

        return exe_dir

    # Source run: this file lives in ...\GSB_Dosyalar\src\
    return Path(__file__).resolve().parents[2]


def config_path() -> Path:
    # Config'i exe'nin yanındaki GSB_Dosyalar altında tutuyoruz
    base = app_base_dir()
    cfg_dir = base / "GSB_Dosyalar"
    cfg_dir.mkdir(parents=True, exist_ok=True)
    return cfg_dir / f"config_giris{ACCOUNT_ID}.json"


def read_credentials() -> Optional[Dict[str, str]]:
    path = config_path()
    if path.exists():
        data = json.loads(path.read_text(encoding="utf-8"))
        if data.get("username") and data.get("password"):
            return {"username": str(data["username"]), "password": str(data["password"])}

    show_error(
        "GSB Giriş",
        "Kullanıcı bilgisi bulunamadı.\n\nÖnce GSB_Ayar.exe ile 1. veya 2. hesabı kaydet.",
    )
    return None


def extract_hidden_inputs(html_text: str) -> Dict[str, str]:
    soup = BeautifulSoup(html_text, "html.parser")
    data: Dict[str, str] = {}
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


def dns_precheck(url: str) -> None:
    host = url.split("//", 1)[-1].split("/", 1)[0]
    socket.getaddrinfo(host, 443)


def _run_hidden(argv: List[str], timeout: float = 3.0) -> Tuple[int, str, str]:
    import subprocess

    creationflags = 0
    startupinfo = None
    try:
        creationflags = subprocess.CREATE_NO_WINDOW
        startupinfo = subprocess.STARTUPINFO()
        startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        startupinfo.wShowWindow = 0
    except Exception:
        pass

    p = subprocess.run(
        argv,
        capture_output=True,
        text=True,
        timeout=timeout,
        creationflags=creationflags,
        startupinfo=startupinfo,
    )
    return p.returncode, p.stdout or "", p.stderr or ""


def get_wifi_ssid() -> str:
    if sys.platform != "win32":
        return ""
    try:
        code, out, _ = _run_hidden(["netsh", "wlan", "show", "interfaces"], timeout=2.5)
        if code != 0:
            return ""
        ssid = ""
        for line in out.splitlines():
            line_s = line.strip()
            # SSID satırı (BSSID değil)
            if line_s.lower().startswith("ssid") and not line_s.lower().startswith("bssid"):
                parts = line_s.split(":", 1)
                if len(parts) == 2:
                    ssid = parts[1].strip()
                    break
        return ssid
    except Exception:
        return ""


def preflight_check() -> Tuple[bool, str]:
    ssid = get_wifi_ssid()
    if sys.platform == "win32" and not ssid:
        return False, "WiFi bağlantısı bulunamadı. Önce GSB WiFi ağına bağlan."

    # SSID doğru ağa işaret ediyorsa DNS hatası bloklamamalı.
    ssid_ok = bool(ssid and any(h.lower() in ssid.lower() for h in WIFI_SSID_HINTS))

    # DNS + portal erişimi (asıl doğrulama)
    dns_ok = True
    try:
        dns_precheck(LOGIN_PAGE_URL)
    except Exception:
        dns_ok = False
        if not ssid_ok:
            hint = f" (SSID: {ssid})" if ssid else ""
            return False, "Portal DNS çözümlenemedi. GSB WiFi ağına bağlı olmayabilirsin" + hint
        # SSID doğru — DNS geçici sorun olabilir, HTTP deneyelim.

    try:
        s = build_session()
        r = s.get(LOGIN_PAGE_URL, timeout=(CONNECT_TIMEOUT, READ_TIMEOUT), allow_redirects=True)
        if r.status_code not in (200, 302, 303):
            return False, f"Portal erişimi başarısız (HTTP {r.status_code})."
    except Exception as exc:
        hint = f" (SSID: {ssid})" if ssid else ""
        return False, f"Portal erişilemiyor. GSB WiFi'a bağlı olmayabilirsin{hint}. ({exc})"

    # SSID uyarısı (bloklamaz)
    if ssid and not any(h.lower() in ssid.lower() for h in WIFI_SSID_HINTS):
        return True, f"Bağlı ağ: {ssid} (GSB WiFi olmayabilir)"

    return True, ""


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


def _extract_error_message(html_text: str) -> str:
    soup = BeautifulSoup(html_text or "", "html.parser")

    selectors = [
        "div[role='alert']",
        ".alert",
        ".error",
        ".errors",
        ".message",
        "#error",
        "#errors",
        "#message",
        ".text-danger",
        ".text-warning",
    ]

    candidates: List[str] = []
    for sel in selectors:
        for el in soup.select(sel):
            txt = " ".join(el.stripped_strings)
            if not txt:
                continue
            # çok uzun HTML bloklarını basmayalım
            txt = re.sub(r"\s+", " ", txt).strip()
            if 4 <= len(txt) <= 260:
                candidates.append(txt)

    # Form çevresindeki metinlerde de hata olabilir
    text = " ".join(soup.stripped_strings)
    text_l = text.lower()
    keywords = (
        "hatalı",
        "yanlış",
        "geçersiz",
        "başarısız",
        "kilitl",
        "deneme",
        "invalid",
        "failed",
        "error",
    )
    if any(k in text_l for k in keywords):
        # En olası hata cümlesini yakalamaya çalış
        for m in re.finditer(r"[^.]{0,120}(hatalı|yanlış|geçersiz|başarısız|invalid|failed|error)[^.]{0,120}", text_l):
            snippet = text[m.start() : m.end()].strip()
            snippet = re.sub(r"\s+", " ", snippet)
            if 6 <= len(snippet) <= 260:
                candidates.append(snippet)

    # En uzun/ayrıntılı adayı seç
    if candidates:
        candidates.sort(key=lambda s: (len(s), s), reverse=True)
        return candidates[0]
    return ""


def _guess_login_failure_reason(html_text: str) -> str:
    try:
        soup = BeautifulSoup(html_text, "html.parser")
        text = " ".join(soup.stripped_strings).lower()
    except Exception:
        text = (html_text or "").lower()

    # Çok genel ama kullanıcı açısından faydalı mesajlar
    invalid_hints = (
        "hatalı",
        "yanlış",
        "geçersiz",
        "invalid",
        "başarısız",
        "failed",
        "kullanıcı",
        "şifre",
        "sifre",
    )

    if any(h in text for h in invalid_hints):
        return "Giriş yapılamadı: TC/şifre yanlış olabilir."

    return "Giriş doğrulanamadı: GSB WiFi ağına bağlı olmayabilirsin veya sistem geçici olarak yanıt vermiyor olabilir."


def _extract_quota_info(html_text: str) -> str:
    soup = BeautifulSoup(html_text or "", "html.parser")
    plain_text = " ".join(soup.stripped_strings)

    # Önce tablo/etiket formatını yapısal olarak topla (en güvenilir yol)
    # Örn satırlar:
    #   Toplam Kalan Kota (MB): 892.0
    #   Toplam Kota (MB): 32768.0
    #   Oturum Süresi: ...
    # Bu, PrimeFaces/JSF çıktısı gibi görünüyor (mainPanel:kota...)
    fields: Dict[str, str] = {}
    try:
        for tr in soup.select("tr"):
            tds = tr.find_all("td")
            if len(tds) < 2:
                continue
            left = " ".join(tds[0].stripped_strings)
            right = " ".join(tds[1].stripped_strings)
            left = re.sub(r"\s+", " ", left).strip()
            right = re.sub(r"\s+", " ", right).strip()
            if not left or not right:
                continue
            # "X:" formatı
            if left.endswith(":"):
                key = left[:-1].strip()
                fields[key] = right
    except Exception:
        fields = {}

    if fields:
        # Kullanıcıya kısa ama faydalı özet
        preferred_order = [
            "Toplam Kalan Kota (MB)",
            "Toplam Kota (MB)",
            "Kalan Kota Zamanı",
            "Sona Erme Tarihi",
            "Oturum Süresi",
            "Login Zamanı",
        ]
        lines: List[str] = []
        for k in preferred_order:
            if k in fields:
                lines.append(f"{k}: {fields[k]}")

        # En azından kalan/toplamı göster
        if not lines:
            # herhangi 2-4 alan
            for k, v in list(fields.items())[:4]:
                lines.append(f"{k}: {v}")

        return "\n".join(lines)

    # Yedek: düz metin regex (tablo parse çalışmazsa)
    norm = re.sub(r"\s+", " ", plain_text).strip()

    def _num(s: str) -> str:
        return s.replace(",", ".").strip()

    m_left = re.search(r"Toplam\s*Kalan\s*Kota\s*\(\s*(MB|GB)\s*\)\s*:\s*([0-9]+(?:[\.,][0-9]+)?)", norm, flags=re.IGNORECASE)
    m_total = re.search(r"Toplam\s*Kota\s*\(\s*(MB|GB)\s*\)\s*:\s*([0-9]+(?:[\.,][0-9]+)?)", norm, flags=re.IGNORECASE)
    if m_left:
        left_unit = m_left.group(1).upper()
        left_val = _num(m_left.group(2))
        if m_total:
            total_unit = m_total.group(1).upper()
            total_val = _num(m_total.group(2))
            # Aynı birimde değilse bile olduğu gibi yaz.
            return f"Toplam Kalan Kota: {left_val} {left_unit} / Toplam: {total_val} {total_unit}"
        return f"Toplam Kalan Kota: {left_val} {left_unit}"

    patterns = [
        r"(kalan\s*kota[^\d]{0,20}\d+[\.,]?\d*\s*(?:mb|gb))",
        r"(kota[^\d]{0,20}\d+[\.,]?\d*\s*(?:mb|gb))",
        r"(kullan[ıi]m[^\d]{0,20}\d+[\.,]?\d*\s*(?:mb|gb))",
    ]

    for pattern in patterns:
        match = re.search(pattern, plain_text, flags=re.IGNORECASE)
        if match:
            return match.group(1)

    return ""


def _extract_quota_fields(html_text: str) -> Dict[str, str]:
    soup = BeautifulSoup(html_text or "", "html.parser")
    fields: Dict[str, str] = {}
    try:
        for tr in soup.select("tr"):
            tds = tr.find_all("td")
            if len(tds) < 2:
                continue
            left = " ".join(tds[0].stripped_strings)
            right = " ".join(tds[1].stripped_strings)
            left = re.sub(r"\s+", " ", left).strip()
            right = re.sub(r"\s+", " ", right).strip()
            if not left or not right:
                continue
            if left.endswith(":"):
                fields[left[:-1].strip()] = right
    except Exception:
        return {}
    return fields


def _quota_headline_and_details(html_text: str) -> Tuple[str, str]:
    fields = _extract_quota_fields(html_text)
    remaining = fields.get("Toplam Kalan Kota (MB)") or fields.get("Toplam Kalan Kota (GB)")
    unit = "MB" if "Toplam Kalan Kota (MB)" in fields else ("GB" if "Toplam Kalan Kota (GB)" in fields else "")
    if remaining:
        headline = f"Kalan Kota: {remaining} {unit}".strip()
    else:
        # regex fallback
        quota_summary = _extract_quota_info(html_text)
        headline = "Kalan Kota" if not quota_summary else "Kota Bilgileri"

    details_lines: List[str] = []
    order = [
        "Toplam Kalan Kota (MB)",
        "Toplam Kota (MB)",
        "Kalan Kota Zamanı",
        "Sona Erme Tarihi",
        "Oturum Süresi",
        "Login Zamanı",
    ]
    for k in order:
        if k in fields:
            details_lines.append(f"{k}: {fields[k]}")

    if not details_lines:
        # yedek olarak eski özet
        summary = _extract_quota_info(html_text)
        if summary:
            details_lines.append(summary)

    return headline, "\n".join(details_lines)


def _discover_quota_urls(html_text: str, base_url: str) -> List[str]:
    soup = BeautifulSoup(html_text or "", "html.parser")
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
        label = f"{link.get_text(' ', strip=True)} {link.get('href', '')}".lower()
        if any(word in label for word in keywords):
            add_url(link.get("href", ""))

    for form in soup.find_all("form"):
        action = form.get("action", "")
        label = f"{form.get_text(' ', strip=True)} {action}".lower()
        if any(word in label for word in keywords):
            add_url(action)

    for element in soup.find_all(attrs={"onclick": True}):
        onclick = element.get("onclick", "")
        if any(word in onclick.lower() for word in keywords):
            match = re.search(r"['\"]([^'\"]+)['\"]", onclick)
            if match:
                add_url(match.group(1))

    return urls


def _extract_name_info(html_text: str) -> str:
    soup = BeautifulSoup(html_text or "", "html.parser")
    text = " ".join(soup.stripped_strings)

    # Örn: "Hoşgeldiniz Ahmet Yılmaz" veya "Sayın Ahmet Yılmaz"
    m = re.search(r"hoş\s*geldiniz\s*[:\-]?\s*([^\n\r]{3,60})", text, flags=re.IGNORECASE)
    if m:
        return m.group(1).strip()

    m = re.search(r"sayın\s+([^\n\r]{3,60})", text, flags=re.IGNORECASE)
    if m:
        return m.group(1).strip()

    return ""


def login_once(session: requests.Session, username: str, password: str) -> Tuple[bool, str, str]:
    start = time.perf_counter()

    login_page = session.get(LOGIN_PAGE_URL, timeout=(CONNECT_TIMEOUT, READ_TIMEOUT), allow_redirects=True)
    if login_page.status_code not in (200, 302, 303):
        return False, "", f"Giriş sayfası alınamadı (HTTP {login_page.status_code})."

    # Bazı durumlarda zaten giriş yapılmış olur ve login formu dönmez.
    if not _looks_like_login_page(login_page.text, login_page.url):
        # Zaten giriş yapılmış olabilir; isim/kota varsa göster.
        # Zaten giriş yapılmış olabilir; kota ekranını öne çıkar.
        headline, details = _quota_headline_and_details(login_page.text)
        if details:
            details = "Zaten giriş yapılmış görünüyor.\n" + details
        else:
            details = "Zaten giriş yapılmış görünüyor."
        return True, headline, details

    auth_url = resolve_auth_url(login_page.text, LOGIN_PAGE_URL)

    payload = extract_hidden_inputs(login_page.text)
    payload.update({"j_username": username, "j_password": password, "submit": "Login"})

    response = session.post(
        auth_url,
        data=payload,
        timeout=(CONNECT_TIMEOUT, READ_TIMEOUT),
        allow_redirects=True,
        headers={"Referer": LOGIN_PAGE_URL, "Content-Type": "application/x-www-form-urlencoded"},
    )

    elapsed = time.perf_counter() - start

    if response.status_code not in (200, 302, 303):
        return False, "", f"Giriş isteği başarısız (HTTP {response.status_code})."

    if _looks_like_login_page(response.text, response.url):
        real_msg = _extract_error_message(response.text)
        if real_msg:
            return False, "", real_msg
        return False, "", _guess_login_failure_reason(response.text)

    # Son bir doğrulama: portal ana sayfası login'e düşüyorsa giriş olmamıştır.
    headline, details = _quota_headline_and_details(response.text)

    # Gerekirse portal ana sayfasından tekrar dene
    try:
        check = session.get(PORTAL_URL, timeout=(CONNECT_TIMEOUT, READ_TIMEOUT), allow_redirects=True)
        if _looks_like_login_page(check.text, check.url):
            real_msg = _extract_error_message(response.text)
            if real_msg:
                return False, "", real_msg
            return False, "", _guess_login_failure_reason(response.text)
        if not details:
            headline, details = _quota_headline_and_details(check.text)

        # Kota linkleri varsa 2-3 tanesini yokla (çok uzatmadan)
        if not details:
            candidates = _discover_quota_urls(check.text, check.url)
            for candidate in candidates[:3]:
                try:
                    qr = session.get(candidate, timeout=(CONNECT_TIMEOUT, READ_TIMEOUT), allow_redirects=True)
                    if qr.status_code in (200, 302, 303):
                        headline, details2 = _quota_headline_and_details(qr.text)
                        if details2:
                            details = details2
                            break
                except Exception:
                    continue
    except Exception:
        # doğrulama başarısız olsa da POST başarılı görünüyorsa kullanıcıyı bloklamayalım
        pass

    msg = f"Giriş başarılı (\u2248 {elapsed:.1f}s)."
    if details:
        msg = msg + "\n" + details
    return True, headline, msg


def main() -> None:
    try:
        dns_precheck(LOGIN_PAGE_URL)
    except Exception:
        # DNS sorun olsa bile denemeye devam
        pass

    creds = read_credentials()
    if not creds:
        return

    session = build_session()

    def task() -> Tuple[bool, str, str]:
        ok_pf, msg_pf = preflight_check()
        if not ok_pf:
            return False, "", msg_pf

        warning = msg_pf.strip()
        last_reason = ""
        for attempt in range(1, MAX_LOGIN_ATTEMPT + 1):
            ok, headline, details_or_reason = login_once(session, creds["username"], creds["password"])
            if ok:
                if warning:
                    # uyarıyı en üste ekle (bloklamaz)
                    details_or_reason = f"Not: {warning}\n{details_or_reason}"
                return True, headline, details_or_reason
            last_reason = details_or_reason
            time.sleep(min(0.6 * attempt, 2.0))
        return False, "", last_reason or "Giriş yapılamadı: Maksimum deneme sayısına ulaşıldı."

    result = run_with_status("GSB Giriş", "Giriş yapılıyor...", task)
    if not result:
        return

    ok, headline, details_or_reason = result
    if ok:
        # Sadece 2 bilgi: giriş + kalan kota (koyu, ortalı UI)
        quota_line = headline.strip() if headline else "Kalan Kota: bulunamadı"
        show_rich_info("GSB Giriş", "✅ Giriş yapıldı", quota_line)
    else:
        show_error("GSB Giriş", f"⛔ {details_or_reason}")


if __name__ == "__main__":
    main()
