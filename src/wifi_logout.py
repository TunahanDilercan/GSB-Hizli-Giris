import os
import re
import socket
import time
from typing import Dict, List, Optional, Tuple
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

PORTAL_URL = os.getenv("WIFI_PORTAL_URL", "https://wifi.gsb.gov.tr")
LOGIN_PAGE_URL = os.getenv("WIFI_LOGIN_PAGE_URL", "https://wifi.gsb.gov.tr/login.html")
LOGOUT_URL = os.getenv("WIFI_LOGOUT_URL", "https://wifi.gsb.gov.tr/logout")

CONNECT_TIMEOUT = 4
READ_TIMEOUT = 8
MAX_ATTEMPT = 4
LOGOUT_SUCCESS_HINTS = ("logout=1", "cikisson", "login.html")


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


def hidden_inputs(form) -> Dict[str, str]:
    data: Dict[str, str] = {}
    for item in form.select("input[type='hidden'][name]"):
        data[item.get("name", "")] = item.get("value", "")
    return data


def discover_logout_actions(html_text: str, base_url: str) -> List[Tuple[str, str, Dict[str, str]]]:
    soup = BeautifulSoup(html_text, "html.parser")
    keywords = ("logout", "log out", "çıkış", "cikis", "oturumu kapat", "güvenli çıkış")
    actions: List[Tuple[str, str, Dict[str, str]]] = []

    def add_action(url: str, method: str = "GET", payload: Optional[Dict[str, str]] = None) -> None:
        if not url:
            return
        full_url = urljoin(base_url, url.strip())
        if full_url.startswith("javascript:"):
            return
        method_u = method.upper()
        item = (full_url, method_u, payload or {})
        if item not in actions:
            actions.append(item)

    for link in soup.find_all("a", href=True):
        label = f"{link.get_text(' ', strip=True)} {link.get('href', '')}".lower()
        if any(word in label for word in keywords):
            add_action(link.get("href", ""), "GET")

    for button in soup.find_all(["button", "input"]):
        text_blob = (
            f"{button.get_text(' ', strip=True)} "
            f"{button.get('value', '')} {button.get('id', '')} {button.get('name', '')}"
        ).lower()
        if any(word in text_blob for word in keywords):
            form = button.find_parent("form")
            if form:
                action = form.get("action", "")
                method = form.get("method", "POST")
                payload = hidden_inputs(form)
                if button.get("name"):
                    payload[button.get("name")] = button.get("value", "")
                add_action(action, method, payload)

    for form in soup.find_all("form"):
        action = form.get("action", "")
        text_blob = f"{form.get_text(' ', strip=True)} {action}".lower()
        if any(word in text_blob for word in keywords):
            method = form.get("method", "POST")
            payload = hidden_inputs(form)
            add_action(action, method, payload)

    for item in soup.find_all(attrs={"onclick": True}):
        onclick = item.get("onclick", "")
        onclick_l = onclick.lower()
        if any(word in onclick_l for word in keywords):
            match = re.search(r"['\"]([^'\"]+)['\"]", onclick)
            if match:
                add_action(match.group(1), "GET")

    return actions


def try_logout(session: requests.Session, method: str, url: str, payload: Dict[str, str]) -> Tuple[bool, str]:
    if method == "POST":
        resp = session.post(
            url,
            data=payload,
            timeout=(CONNECT_TIMEOUT, READ_TIMEOUT),
            allow_redirects=True,
            headers={"Referer": PORTAL_URL, "Content-Type": "application/x-www-form-urlencoded"},
        )
    else:
        resp = session.get(url, timeout=(CONNECT_TIMEOUT, READ_TIMEOUT), allow_redirects=True)

    code_ok = resp.status_code in (200, 302, 303)
    final_url = resp.url.lower()
    body = resp.text.lower()
    looks_logged_out = (
        "j_spring_security_check" in body
        or "j_username" in body
        or "login" in body
        or "giriş" in body
        or any(hint in final_url for hint in LOGOUT_SUCCESS_HINTS)
    )

    message = f"{method} {url} -> {resp.status_code} | final: {resp.url}"
    return (code_ok and looks_logged_out), message


def logout_flow() -> None:
    try:
        dns_precheck(PORTAL_URL)
    except Exception:
        print("⚠️ DNS çözümü başarısız, yine de logout denenecek...")

    session = build_session()

    for attempt in range(1, MAX_ATTEMPT + 1):
        try:
            print(f"Çıkış deneniyor ({attempt}/{MAX_ATTEMPT})...")

            if LOGOUT_URL:
                ok, msg = try_logout(session, "GET", LOGOUT_URL, {})
                print(msg)
                if ok:
                    print("✅ Çıkış başarılı")
                    return

            page = session.get(PORTAL_URL, timeout=(CONNECT_TIMEOUT, READ_TIMEOUT), allow_redirects=True)
            actions = discover_logout_actions(page.text, page.url)

            if not actions:
                page2 = session.get(LOGIN_PAGE_URL, timeout=(CONNECT_TIMEOUT, READ_TIMEOUT), allow_redirects=True)
                actions = discover_logout_actions(page2.text, page2.url)

            if not actions:
                print("⚠️ Çıkış aksiyonu bulunamadı.")
            else:
                for url, method, payload in actions[:10]:
                    ok, msg = try_logout(session, method, url, payload)
                    print(msg)
                    if ok:
                        print("✅ Çıkış başarılı")
                        return

            print("⚠️ Çıkış doğrulanamadı, tekrar denenecek...")
        except Exception as exc:
            print(f"❌ Hata: {exc}")

        time.sleep(min(0.6 * attempt, 2.0))

    print("⛔ Çıkış yapılamadı. F12 > Network > logout isteğini paylaş, URL'i sabitleyelim.")


if __name__ == "__main__":
    logout_flow()
