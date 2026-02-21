import os
import re
import socket
import time
from typing import Dict, List
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

USERNAME = os.getenv("WIFI_USERNAME", "14933986294")
PASSWORD = os.getenv("WIFI_PASSWORD", "Ahmet+100")

# Login sayfası (GET) ve form post endpoint'i (POST)
LOGIN_PAGE_URL = os.getenv("WIFI_LOGIN_PAGE_URL", "https://wifi.gsb.gov.tr/login.html")
AUTH_URL = os.getenv("WIFI_AUTH_URL", "")
QUOTA_URL = os.getenv("WIFI_QUOTA_URL", "")

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

	# Windows proxy/env ayarlarını bypass eder (bazı ağlarda gecikmeyi azaltır)
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


def extract_quota_info(html_text: str) -> str:
	soup = BeautifulSoup(html_text, "html.parser")
	plain_text = " ".join(soup.stripped_strings)

	patterns = [
		r"(kalan\s*kota[^\d]{0,20}\d+[\.,]?\d*\s*(?:mb|gb))",
		r"(kota[^\d]{0,20}\d+[\.,]?\d*\s*(?:mb|gb))",
		r"(kullan[ıi]m[^\d]{0,20}\d+[\.,]?\d*\s*(?:mb|gb))",
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


def print_quota_info(session: requests.Session, login_response_text: str, current_url: str) -> None:
	print("\n--- Kota Bilgisi ---")
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
				print(f"Kota bulundu ({candidate}): {parsed}")
				return
		except Exception as exc:
			print(f"Kota adayı okunamadı ({candidate}): {exc}")


def login_once(session: requests.Session) -> bool:
	start = time.perf_counter()

	if not LOGIN_PAGE_URL:
		raise ValueError("LOGIN_PAGE_URL boş olamaz.")

	login_page = session.get(
		LOGIN_PAGE_URL,
		timeout=(CONNECT_TIMEOUT, READ_TIMEOUT),
		allow_redirects=True,
	)
	login_page.raise_for_status()

	auth_url = resolve_auth_url(login_page.text, LOGIN_PAGE_URL)

	payload = extract_hidden_inputs(login_page.text)
	payload.update(
		{
			"j_username": USERNAME,
			"j_password": PASSWORD,
			"submit": "Login",
		}
	)

	response = session.post(
		auth_url,
		data=payload,
		timeout=(CONNECT_TIMEOUT, READ_TIMEOUT),
		allow_redirects=True,
		headers={"Referer": LOGIN_PAGE_URL, "Content-Type": "application/x-www-form-urlencoded"},
	)

	elapsed = time.perf_counter() - start

	# Basit başarı kontrolü: login formu tekrar görünmüyorsa başarılı kabul et
	body_lower = response.text.lower()
	login_form_back = "j_spring_security_check" in body_lower or "j_username" in body_lower
	success = response.status_code in (200, 302, 303) and not login_form_back

	print(f"Durum: {response.status_code} | Süre: {elapsed:.2f}s | POST: {auth_url}")
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
			print(f"Giriş deneniyor ({attempt}/{MAX_LOGIN_ATTEMPT})...")
			if login_once(session):
				print("✅ Giriş başarılı")
				return
			print("⚠️ Giriş doğrulanamadı, tekrar denenecek...")
		except Exception as exc:
			print(f"❌ Hata: {exc}")

		time.sleep(min(0.6 * attempt, 2.0))

	print("⛔ Maksimum deneme sayısına ulaşıldı.")


if __name__ == "__main__":
	fast_login()