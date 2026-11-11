"""
scraper_multi.py - Cào tin phòng trọ Đà Nẵng từ NHIỀU trang, nhanh hơn bản cũ.

NGUỒN (xem dict SITES):
  nhatot       Chợ Tốt (Playwright + __NEXT_DATA__)                          - mặc định BẬT
  phongtro123  phongtro123.com  (cấu trúc URL/link đã đối chiếu HTML thật)   - mặc định BẬT
  phongtro_vn  phongtro.vn      (cấu trúc URL/link đã đối chiếu HTML thật)   - mặc định BẬT
  alonhadat, mogi  CHƯA kiểm chứng -> mặc định TẮT. Muốn dùng: chạy --inspect <tên>,
                   chỉnh SITES cho khớp rồi đổi "enabled": True (hoặc gọi --sites alonhadat).
  (thuephongtro.com không đưa vào: tin mới nhất dừng ở 2025, số liệu giá lỗi đơn vị.)

So với bản cũ: requests song song + trình duyệt dự phòng, độ trễ theo từng tên miền,
SĐT chỉ lấy khi người đăng công khai (thẻ tel:, data-phone, JSON-LD "telephone", hoặc ghi trong
nội dung tin) - KHÔNG đăng nhập / phá "bấm để hiện số". Tôn trọng robots.txt.
Một số trang yêu cầu ghi rõ nguồn khi đăng lại: tool đã lưu cột nguon + url của từng tin.

Ví dụ:
  python scraper_multi.py --inspect phongtro123              # kiểm tra 1 nguồn
  python scraper_multi.py                                    # các nguồn đang bật, 7 quận
  python scraper_multi.py --sites phongtro123,phongtro_vn --districts quan-hai-chau,quan-son-tra
  python scraper_multi.py --max-pages 3 --site-pages 5 --delay 0.5
"""
import argparse
import json
import logging
import queue
import random
import re
import sys
import threading
import time
from concurrent.futures import Future, ThreadPoolExecutor, as_completed
from pathlib import Path
from urllib import robotparser
from urllib.parse import urljoin, urlparse

import requests
from requests.adapters import HTTPAdapter
from bs4 import BeautifulSoup

from phone_utils import clean_phone, extract_phone, extract_contact_links

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("scraper")

RESPECT_ROBOTS = True
OUTPUT_FILE = "raw_listings.jsonl"
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36")
HEADERS = {"User-Agent": UA, "Accept-Language": "vi-VN,vi;q=0.9,en;q=0.5",
           "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"}

DISTRICT_NAME = {
    "quan-hai-chau": "Hải Châu", "quan-thanh-khe": "Thanh Khê", "quan-son-tra": "Sơn Trà",
    "quan-ngu-hanh-son": "Ngũ Hành Sơn", "quan-lien-chieu": "Liên Chiểu",
    "quan-cam-le": "Cẩm Lệ", "huyen-hoa-vang": "Hòa Vang",
}
ALL_DISTRICTS = list(DISTRICT_NAME)

# ---------------------------------------------------------------------------
# CẤU HÌNH NGUỒN
#   type "nextdata": trang Next.js có __NEXT_DATA__ (nhatot) - theo từng quận.
#   type "html"    : trang HTML thường: list_urls ({page}) -> link chi tiết (detail_re)
#                    -> trích xuất từng tin. Các khóa *_sel là CSS selector (tùy chọn),
#                    bỏ trống thì dùng JSON-LD / og:meta / regex.
# ---------------------------------------------------------------------------
SITES = {
    "nhatot": {
        "type": "nextdata", "enabled": True, "domain": "nhatot.com", "base": "https://www.nhatot.com",
        "prefer_browser": True,   # nhatot hay chặn requests -> vào thẳng trình duyệt
    },
    # --- ĐÃ đối chiếu với HTML thật (10/2026) ---
    "phongtro123": {
        "type": "html", "enabled": True, "domain": "phongtro123.com", "base": "https://phongtro123.com",
        # theo từng quận: /tinh-thanh/da-nang/quan-hai-chau?page=2  (slug trùng ALL_DISTRICTS)
        "list_urls": ["https://phongtro123.com/tinh-thanh/da-nang/{district}?page={page}"],
        "link_sel": "h3 a[href]",            # chỉ lấy link tiêu đề trong danh sách (bỏ khối "Tin mới đăng" của tỉnh khác)
        "card_parse": True,
        "detail_re": r"-pr\d+\.html",
        "require_text": "Đà Nẵng",           # loại tin lạc sang tỉnh khác
        "content_sel": None, "phone_sel": None,
        "ignore_phones": ["0909316890", "0917686101"],
        "ignore_contacts": ["phongtro123", "phongtro"],   # hotline của trang
    },
    "phongtro_vn": {
        "type": "html", "enabled": True, "domain": "phongtro.vn", "base": "https://phongtro.vn",
        # cấp thành phố: /cho-thue-phong-tro-tp-da-nang-trang-2
        "list_urls": ["https://phongtro.vn/cho-thue-phong-tro-tp-da-nang-trang-{page}"],
        "link_sel": "h3 a[href]",
        "raw_scan": True,    # nếu link nằm trong JSON nhúng (Next.js) vẫn lấy được
        "card_parse": True,  # lấy giá/diện tích/địa chỉ từ thẻ tin ở trang danh sách (chính xác nhất)
        "detail_re": r"/cho-thue-phong-tro-[a-z0-9\-]+-tp-da-nang/\d+",
        "require_text": "Đà Nẵng",
        "content_sel": None, "phone_sel": None,
        "ignore_phones": ["0974201532"],
        "ignore_contacts": ["phongtro"],
    },
    # --- CHƯA kiểm chứng: mặc định tắt ---
    "alonhadat": {
        "type": "html", "enabled": False, "domain": "alonhadat.com.vn", "base": "https://alonhadat.com.vn",
        "list_urls": ["https://alonhadat.com.vn/nha-dat/cho-thue/phong-tro/da-nang/trang--{page}.html"],
        "link_sel": None, "detail_re": r"/[a-z0-9\-]+-\d{5,}\.html", "require_text": "Đà Nẵng",
        "content_sel": None, "phone_sel": None, "ignore_phones": [],
    },
    "mogi": {
        "type": "html", "enabled": False, "domain": "mogi.vn", "base": "https://mogi.vn",
        "list_urls": ["https://mogi.vn/da-nang/thue-nha-tro-phong-tro?cp={page}"],
        "link_sel": None, "detail_re": r"mogi\.vn/[a-z0-9\-/]+-id\d+", "require_text": "Đà Nẵng",
        "content_sel": None, "phone_sel": None, "ignore_phones": [],
    },
}

_FRAC = r"(?:\d(?!\d*\s*m\s*\^?\s*[2²]))?"      # "3tr5" -> 3,5tr ; nhưng "3 triệu16 m²" -> 3tr + 16m²
PRICE_NEAR = re.compile(r"gi[áa][^\d\n]{0,25}(\d+(?:[.,]\d+)?\s*(?:triệu|tr)(?![a-zà-ỹ])" + _FRAC + ")", re.I)
PRICE_ANY = re.compile(r"(\d+(?:[.,]\d+)?\s*(?:triệu|tr)(?![a-zà-ỹ])" + _FRAC + ")", re.I)

# Thẻ tin trong trang danh sách: "5.5 triệu45 m² Đường Lý Đạo Thành, Sơn Trà, Đà Nẵng" (giá + diện tích dính liền)
# hoặc "4.3 triệu/tháng25 m2 ...". Đây là giá HIỂN THỊ chính thức nên được ưu tiên hơn mọi chỗ khác.
CARD_RE = re.compile(r"(\d+(?:[.,]\d+)?)\s*(triệu|tr|nghìn)\s*(?:/\s*tháng)?\s*(\d+(?:[.,]\d+)?)\s*m\s*\^?\s*[2²]\s*(.*)", re.I | re.S)


def parse_card(text):
    m = CARD_RE.search(" ".join((text or "").split()))
    if not m:
        return None
    num, unit = m.group(1).replace(",", "."), m.group(2).lower()
    return {"price_raw": f"{num}k" if unit == "nghìn" else f"{num} triệu",
            "area_raw": f"{m.group(3).replace(',', '.')}m2", "address": m.group(4).strip()}
PRICE_FULL = re.compile(r"(\d{1,3}(?:\.\d{3}){2}\s*(?:đ|vnđ|vnd))", re.I)
AREA_RE = re.compile(r"(\d+(?:[.,]\d+)?)\s*m\s*\^?\s*(?:2|²)", re.I)
PRICE_NGHIN = re.compile(r"(\d+(?:[.,]\d+)?)\s*nghìn", re.I)   # "600 Nghìn/tháng" -> 600k
LATLNG_RE = [re.compile(r"data-lat(?:itude)?=[\"']?(-?\d+\.\d+)[\"']?[^>]*?data-(?:lng|lon|long|longitude)=[\"']?(-?\d+\.\d+)", re.I),
             re.compile(r"[?&]q=(-?\d+\.\d+),\s*(-?\d+\.\d+)"),
             re.compile(r"@(-?\d+\.\d+),(-?\d+\.\d+)")]


# ---------------------------------------------------------------------------
# TẦNG TẢI TRANG: requests song song + trình duyệt dự phòng + giới hạn theo tên miền
# ---------------------------------------------------------------------------
STRONG_BLOCK = ["attention required! | cloudflare", "checking your browser", "cf-browser-verification",
                "just a moment...", "verify you are human", 'id="challenge-running"', 'id="cf-challenge']


def looks_blocked(html: str) -> bool:
    low = (html or "").lower()
    return len(low) < 1500 or any(s in low for s in STRONG_BLOCK)


class DomainLimiter:
    """Mỗi tên miền chỉ được gọi cách nhau >= min_interval; các tên miền khác nhau chạy song song."""
    def __init__(self, min_interval):
        self.min_interval, self.lock, self.next_ok = min_interval, threading.Lock(), {}

    def wait(self, domain):
        with self.lock:
            now = time.monotonic()
            slot = max(now, self.next_ok.get(domain, 0))
            self.next_ok[domain] = slot + self.min_interval * random.uniform(1.0, 1.4)
        if slot > now:
            time.sleep(slot - now)


class BrowserPool:
    """Vài luồng, mỗi luồng giữ 1 Chromium riêng (Playwright sync không dùng chéo luồng được)."""
    def __init__(self, n):
        self.q = queue.Queue()
        self.threads = [threading.Thread(target=self._run, daemon=True) for _ in range(n)]
        for t in self.threads:
            t.start()

    def _run(self):
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            ctx = browser.new_context(user_agent=UA, locale="vi-VN", viewport={"width": 1366, "height": 768})
            ctx.route("**/*", lambda r: r.abort() if r.request.resource_type in
                      ("image", "media", "font", "stylesheet") else r.continue_())
            page = ctx.new_page()
            while True:
                item = self.q.get()
                if item is None:
                    break
                url, fut = item
                try:
                    page.goto(url, timeout=30000, wait_until="domcontentloaded")
                    fut.set_result(page.content())
                except Exception as e:  # noqa
                    fut.set_exception(e)
            browser.close()

    def get(self, url, timeout=60):
        fut = Future()
        self.q.put((url, fut))
        return fut.result(timeout=timeout)

    def close(self):
        for _ in self.threads:
            self.q.put(None)


class Fetcher:
    def __init__(self, min_interval=0.6, use_browser=True, browser_workers=2, prefer_browser_domains=()):
        self.session = requests.Session()
        ad = HTTPAdapter(pool_connections=16, pool_maxsize=32)
        self.session.mount("https://", ad)
        self.session.mount("http://", ad)
        self.session.headers.update(HEADERS)
        self.limiter = DomainLimiter(min_interval)
        self.use_browser, self.browser_workers = use_browser, browser_workers
        self.browser_domains = set(prefer_browser_domains)
        self._pool, self._pool_lock = None, threading.Lock()
        self._robots, self._robots_lock = {}, threading.Lock()

    def allowed(self, url):
        if not RESPECT_ROBOTS:
            return True
        p = urlparse(url)
        with self._robots_lock:
            rp = self._robots.get(p.netloc)
            if rp is None:
                rp = robotparser.RobotFileParser()
                try:
                    r = self.session.get(f"{p.scheme}://{p.netloc}/robots.txt", timeout=10)
                    rp.parse(r.text.splitlines()) if r.status_code < 400 else rp.parse([])
                except requests.RequestException:
                    rp.parse([])
                self._robots[p.netloc] = rp
        return rp.can_fetch("*", url)

    def _browser(self):
        with self._pool_lock:
            if self._pool is None:
                self._pool = BrowserPool(self.browser_workers)
            return self._pool

    def get(self, url):
        domain = urlparse(url).netloc
        if not self.allowed(url):
            logger.warning(f"robots.txt không cho phép: {url} - bỏ qua")
            return None
        if domain not in self.browser_domains:
            self.limiter.wait(domain)
            status = None
            try:
                r = self.session.get(url, timeout=20)
                status = r.status_code
                if status == 200 and not looks_blocked(r.text):
                    return r.text
                if status == 404:
                    return None
            except requests.RequestException as e:
                logger.warning(f"requests lỗi {url}: {e}")
            if not self.use_browser:
                logger.warning(f"Bị chặn/lỗi ({status}) tại {url} và đã tắt trình duyệt dự phòng")
                return None
            logger.info(f"{domain}: requests bị chặn/lỗi ({status}) -> chuyển sang trình duyệt")
            self.browser_domains.add(domain)
        if not self.use_browser:
            return None
        self.limiter.wait(domain)
        try:
            html = self._browser().get(url)
        except Exception as e:  # noqa
            logger.warning(f"Trình duyệt lỗi {url}: {e}")
            return None
        if looks_blocked(html):
            Path("debug_page.html").write_text(html or "", encoding="utf-8")
            logger.error(f"Nghi ngờ bị chặn tại {url} (đã lưu debug_page.html) - bỏ qua trang này")
            return None
        return html

    def force_browser(self, url):
        """Tải lại bằng trình duyệt (trang render bằng JS) và nhớ tên miền này từ nay dùng trình duyệt."""
        if not self.use_browser:
            return None
        self.browser_domains.add(urlparse(url).netloc)
        return self.get(url)

    def close(self):
        if self._pool:
            self._pool.close()


# ---------------------------------------------------------------------------
# NHATOT (đường dẫn dữ liệu đã xác nhận qua sample_next_data.json)
# ---------------------------------------------------------------------------
NEXT_DATA_RE = re.compile(r'<script id="__NEXT_DATA__" type="application/json">(.*?)</script>', re.DOTALL)


def nhatot_ads(html):
    m = NEXT_DATA_RE.search(html or "")
    if not m:
        return []
    try:
        return json.loads(m.group(1))["props"]["initialState"]["adlisting"]["data"]["ads"] or []
    except (KeyError, TypeError, json.JSONDecodeError):
        return []


def nhatot_record(ad, base):
    title = ad.get("subject")
    if not title:
        return None
    lid = ad.get("list_id") or ad.get("ad_id")
    body = ad.get("body", "") or ""
    phone, src = clean_phone(str(ad.get("phone") or "")), "ad.phone"
    if not phone:
        phone, src = extract_phone(f"{title}\n{body}"), "noi_dung_tin"
    return {
        "title": title, "url": f"{base}/rao-vat/{lid}.htm" if lid else "#",
        "price_raw": str(ad["price"]) if ad.get("price") is not None else "",
        "area_raw": str(ad.get("size") or ad.get("area") or ""),
        "address_raw": ", ".join(p for p in (ad.get("street_name", ""), ad.get("ward_name", ""),
                                             ad.get("area_name", "")) if p),
        "body_raw": body, "phone_raw": phone, "phone_source": src if phone else "",
        "contact_raw": extract_contact_links(f"{title}\n{body}", ("nhatot", "chotot")),
        "vi_do_raw": ad.get("latitude"), "kinh_do_raw": ad.get("longitude"),
        "nguon": "nhatot.com", "scraped_at": time.strftime("%Y-%m-%d %H:%M:%S"),
    }


def scrape_nhatot_district(district, fetcher, max_pages):
    cfg, out, seen = SITES["nhatot"], [], set()
    for pnum in range(1, max_pages + 1):
        url = f"{cfg['base']}/thue-phong-tro-{district}-da-nang" + (f"?offset={(pnum-1)*20}" if pnum > 1 else "")
        html = fetcher.get(url)
        ads = nhatot_ads(html) if html else []
        new = 0
        for ad in ads:
            if ad.get("list_id") in seen:
                continue
            seen.add(ad.get("list_id"))
            rec = nhatot_record(ad, cfg["base"])
            if rec:
                out.append(rec)
                new += 1
        logger.info(f"  nhatot {district} trang {pnum}: {len(ads)} tin ({new} mới)")
        if new == 0:
            break
    return out


# ---------------------------------------------------------------------------
# TRANG HTML TỔNG QUÁT
# ---------------------------------------------------------------------------
def jsonld_objects(soup):
    out = []
    for tag in soup.find_all("script", type="application/ld+json"):
        try:
            stack = [json.loads(tag.string or tag.get_text() or "")]
        except Exception:  # noqa
            continue
        while stack:
            x = stack.pop()
            if isinstance(x, list):
                stack.extend(x)
            elif isinstance(x, dict):
                out.append(x)
                if isinstance(x.get("@graph"), list):
                    stack.extend(x["@graph"])
    return out


def in_danang(lat, lng):
    try:
        return 15.8 <= float(lat) <= 16.35 and 107.7 <= float(lng) <= 108.45
    except (TypeError, ValueError):
        return False


def meta(soup, *names):
    for n in names:
        t = soup.find("meta", attrs={"property": n}) or soup.find("meta", attrs={"name": n})
        if t and t.get("content"):
            return t["content"].strip()
    return ""


def discover_links(html, page_url, cfg, cards=None):
    """Trả danh sách URL chi tiết. Nếu truyền `cards` (dict) và cfg["card_parse"]: điền thêm
    cards[url] = {title, price_raw, area_raw, address} lấy từ thẻ tin ở trang danh sách."""
    soup, pat, seen, out = BeautifulSoup(html, "lxml"), re.compile(cfg["detail_re"]), set(), []

    def add(href, anchor=None):
        if not href:
            return None
        u = urljoin(page_url, href).split("#")[0]
        if cfg["domain"] in urlparse(u).netloc and pat.search(u):
            if u not in seen:
                seen.add(u)
                out.append(u)
            if cards is not None and anchor is not None:
                cards.setdefault(u, {}).setdefault("title", anchor.get_text(" ", strip=True))
            return u
        return None

    if cfg.get("link_sel"):
        for a in soup.select(cfg["link_sel"]):
            add(a.get("href"), a)
    if not out:                       # selector không khớp -> thử mọi thẻ <a>
        for a in soup.find_all("a", href=True):
            add(a["href"], a)
    if not out and cfg.get("raw_scan"):   # trang Next.js/CSR: link nằm trong JSON nhúng
        for m in re.finditer(cfg["detail_re"], html):
            add(m.group(0))

    if cards is not None and cfg.get("card_parse"):
        for a in soup.find_all("a", href=True):
            u = urljoin(page_url, a["href"]).split("#")[0]
            if u in seen:
                info = parse_card(a.get_text(" ", strip=True))
                if info:
                    cards.setdefault(u, {}).update(info)
    return out


def parse_detail(html, url, cfg, site_name):
    soup = BeautifulSoup(html, "lxml")
    ld = jsonld_objects(soup)
    raw_html = html

    for t in soup(["script", "style", "noscript", "nav", "footer"]):
        t.decompose()
    scope = soup.select_one(cfg["content_sel"]) if cfg.get("content_sel") else None
    scope = scope or soup.body or soup
    text = scope.get_text("\n", strip=True)

    h1 = soup.find("h1")
    title = (h1.get_text(" ", strip=True) if h1 else "") or meta(soup, "og:title") or \
            (soup.title.get_text(strip=True) if soup.title else "")
    if not title:
        return None

    ld_desc = next((str(o["description"]) for o in ld if o.get("description")), "")
    desc = ld_desc or meta(soup, "og:description", "description")
    body = text if len(text) > len(desc) else desc
    body = body[:4000]

    head_text = f"{title}\n{text[:2500]}"
    price = ""
    for o in ld:
        offers = o.get("offers")
        if isinstance(offers, dict) and offers.get("price"):
            price = str(offers["price"])
            break
    if not price:
        for o in ld:
            if o.get("priceRange") and re.sub(r"\D", "", str(o["priceRange"])):
                price = re.sub(r"\D", "", str(o["priceRange"]))
                break
    if not price:
        mn = PRICE_NGHIN.search(head_text)
        if mn:
            price = f"{mn.group(1).replace(',', '.')}k"
    if not price:
        for rx in (PRICE_NEAR, PRICE_ANY, PRICE_FULL):
            m = rx.search(head_text)
            if m:
                price = m.group(1)
                break
    m = AREA_RE.search(head_text)
    area = f"{m.group(1)}m2" if m else ""

    address = ""
    for o in ld:
        a = o.get("address")
        if isinstance(a, dict):
            address = ", ".join(str(a.get(k)) for k in ("streetAddress", "addressLocality", "addressRegion") if a.get(k))
        elif isinstance(a, str):
            address = a
        if address:
            break
    if not address:
        m = re.search(r"[^\n]{0,120}Đà Nẵng[^\n]{0,30}", text)
        address = m.group(0).strip() if m else ""
    if not any(n in address for n in DISTRICT_NAME.values()):
        for n in DISTRICT_NAME.values():
            if n.lower() in head_text.lower():
                address = f"{address}, {n}".strip(", ")
                break

    lat = lng = None
    for o in ld:
        g = o.get("geo")
        if isinstance(g, dict) and in_danang(g.get("latitude"), g.get("longitude")):
            lat, lng = float(g["latitude"]), float(g["longitude"])
            break
    if lat is None:
        for rx in LATLNG_RE:
            mm = rx.search(raw_html)
            if mm and in_danang(mm.group(1), mm.group(2)):
                lat, lng = float(mm.group(1)), float(mm.group(2))
                break

    # --- SĐT: thẻ tel:/data-phone trong vùng liên hệ, rồi mới tới nội dung tin ---
    ignore = {clean_phone(p) for p in cfg.get("ignore_phones", [])}
    phone, psrc = "", ""
    phone_scope = soup.select(cfg["phone_sel"]) if cfg.get("phone_sel") else [scope]
    for sc in phone_scope:
        cands = [a["href"] for a in sc.select('a[href^="tel:"]')]
        cands += [e.get(k) for e in sc.select("[data-phone],[data-tel]") for k in ("data-phone", "data-tel") if e.get(k)]
        for c in cands:
            p = clean_phone(c.replace("tel:", ""))
            if p and p not in ignore:
                phone, psrc = p, "the_tel/data-phone"
                break
        if phone:
            break
    if not phone:
        for o in ld:   # dữ liệu có cấu trúc (schema.org) do chính trang công khai
            p = clean_phone(str(o.get("telephone") or ""))
            if p and p not in ignore:
                phone, psrc = p, "json-ld"
                break
    if not phone:
        p = extract_phone(f"{title}\n{body}")
        if p and p not in ignore:
            phone, psrc = p, "noi_dung_tin"

    need = cfg.get("require_text")
    if need and need.lower() not in f"{title} {address} {text[:3000]}".lower():
        return None   # tin không thuộc Đà Nẵng

    hrefs = " ".join(a.get("href", "") for a in scope.select("a[href]"))
    contact = extract_contact_links(f"{title}\n{body}\n{hrefs}", cfg.get("ignore_contacts", ()))

    return {
        "title": title, "url": url, "price_raw": price, "area_raw": area, "address_raw": address,
        "body_raw": body, "phone_raw": phone, "phone_source": psrc, "contact_raw": contact,
        "vi_do_raw": lat, "kinh_do_raw": lng,
        "nguon": cfg["domain"], "scraped_at": time.strftime("%Y-%m-%d %H:%M:%S"),
    }


def scrape_html_site(name, fetcher, site_pages, workers, districts=None, max_pages=2):
    cfg, links, seen, cards = SITES[name], [], set(), {}
    for tmpl in cfg["list_urls"]:
        per_district = "{district}" in tmpl
        scopes = (districts or ALL_DISTRICTS) if per_district else [None]
        pages = max_pages if per_district else site_pages
        for scope in scopes:
            for page in range(1, pages + 1):
                url = tmpl.format(page=page, district=scope or "")
                html = fetcher.get(url)
                if not html:
                    break
                found = discover_links(html, url, cfg, cards)
                if not found and page == 1 and urlparse(url).netloc not in fetcher.browser_domains:
                    logger.info(f"  {name}: requests không thấy link -> thử lại bằng trình duyệt (trang có thể render bằng JS)")
                    html2 = fetcher.force_browser(url)
                    if html2:
                        found = discover_links(html2, url, cfg, cards)
                new = 0
                for l in found:
                    if l not in seen:
                        seen.add(l)
                        links.append(l)
                        new += 1
                logger.info(f"  {name} {scope or 'tp'} trang {page}: +{new} link")
                if new == 0:
                    if page == 1:
                        logger.warning(f"{name}: KHÔNG tìm thấy link chi tiết tại {url} - "
                                       f"kiểm tra list_urls/link_sel/detail_re (chạy --inspect {name})")
                    break
    logger.info(f"{name}: {len(links)} link chi tiết, bắt đầu tải song song")

    def one(u):
        rec = None
        try:
            html = fetcher.get(u)
            rec = parse_detail(html, u, cfg, name) if html else None
        except Exception as e:  # noqa
            logger.warning(f"{name}: lỗi trích xuất {u}: {e}")
        card = cards.get(u) or {}
        if card.get("price_raw"):                     # giá hiển thị ở thẻ tin = chuẩn
            need = cfg.get("require_text")
            if rec is None and card.get("title") and (not need or need.lower() in card.get("address", "").lower()):
                rec = {"title": card["title"], "url": u, "price_raw": "", "area_raw": "", "address_raw": "",
                       "body_raw": "", "phone_raw": "", "phone_source": "", "contact_raw": "", "vi_do_raw": None, "kinh_do_raw": None,
                       "nguon": cfg["domain"], "scraped_at": time.strftime("%Y-%m-%d %H:%M:%S")}
            if rec is not None:
                rec["price_raw"], rec["area_raw"] = card["price_raw"], card["area_raw"]
                if card.get("address"):
                    rec["address_raw"] = card["address"]
        return rec

    out = []
    with ThreadPoolExecutor(max_workers=workers) as ex:
        for f in as_completed([ex.submit(one, u) for u in links]):
            r = f.result()
            if r:
                out.append(r)
    logger.info(f"{name}: trích xuất {len(out)}/{len(links)} tin")
    return out


# ---------------------------------------------------------------------------
# HẬU XỬ LÝ
# ---------------------------------------------------------------------------
def drop_hotline_phones(records):
    """SĐT xuất hiện ở >=60% tin của 1 nguồn (>=10 tin) gần như chắc là hotline của trang."""
    by_site = {}
    for r in records:
        by_site.setdefault(r["nguon"], []).append(r)
    for site, rs in by_site.items():
        if len(rs) < 10:
            continue
        cnt = {}
        for r in rs:
            if r["phone_raw"]:
                cnt[r["phone_raw"]] = cnt.get(r["phone_raw"], 0) + 1
        ccnt = {}
        for r in rs:
            if r.get("contact_raw"):
                ccnt[r["contact_raw"]] = ccnt.get(r["contact_raw"], 0) + 1
        for l, c in ccnt.items():
            if c / len(rs) >= 0.6:
                logger.warning(f"{site}: liên kết {l} xuất hiện ở {c}/{len(rs)} tin -> coi là của trang, bỏ.")
                for r in rs:
                    if r.get("contact_raw") == l:
                        r["contact_raw"] = ""
        for p, c in cnt.items():
            if c / len(rs) >= 0.6:
                logger.warning(f"{site}: {p} xuất hiện ở {c}/{len(rs)} tin -> coi là hotline trang, bỏ.")
                for r in rs:
                    if r["phone_raw"] == p:
                        r["phone_raw"], r["phone_source"] = "", ""


def dedupe(records):
    seen_url, seen_key, out = set(), set(), []
    for r in records:
        digits = re.sub(r"\D", "", r.get("price_raw") or "")
        key = (r["phone_raw"], digits, r.get("area_raw")) if r["phone_raw"] and digits else None
        if r["url"] in seen_url or (key and key in seen_key):
            continue
        seen_url.add(r["url"])
        if key:
            seen_key.add(key)
        out.append(r)
    return out


def district_ok(rec, wanted_names):
    if not wanted_names:
        return True
    blob = f"{rec['address_raw']} {rec['title']}".lower()
    found = [n for n in DISTRICT_NAME.values() if n.lower() in blob]
    return not found or any(n in wanted_names for n in found)


# ---------------------------------------------------------------------------
def inspect_site(name, fetcher):
    cfg = SITES[name]
    if cfg["type"] == "nextdata":
        html = fetcher.get(f"{cfg['base']}/thue-phong-tro-quan-hai-chau-da-nang")
        ads = nhatot_ads(html or "")
        print(f"nhatot: {len(ads)} tin; mẫu:", json.dumps(nhatot_record(ads[0], cfg['base']), ensure_ascii=False, indent=2) if ads else None)
        return
    url = cfg["list_urls"][0].format(page=1, district="quan-hai-chau")
    html = fetcher.get(url)
    if not html:
        print("Không tải được trang danh sách:", url)
        return
    Path(f"debug_{name}_list.html").write_text(html, encoding="utf-8")
    links = discover_links(html, url, cfg)
    print(f"{name}: {len(links)} link chi tiết (đã lưu debug_{name}_list.html)")
    if links:
        d = fetcher.get(links[0])
        if d:
            Path(f"debug_{name}_detail.html").write_text(d, encoding="utf-8")
            print(json.dumps(parse_detail(d, links[0], cfg, name), ensure_ascii=False, indent=2))


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--sites", default="", help="vd: nhatot,phongtro123,phongtro_vn (mặc định: các nguồn đang bật)")
    ap.add_argument("--districts", default="", help="vd: quan-hai-chau,quan-son-tra (mặc định: tất cả)")
    ap.add_argument("--max-pages", type=int, default=2, help="số trang/quận (nhatot, phongtro123: ~20 tin/trang)")
    ap.add_argument("--site-pages", type=int, default=5, help="số trang danh sách cho nguồn cấp thành phố (phongtro.vn...)")
    ap.add_argument("--workers", type=int, default=8, help="số luồng tải trang chi tiết song song")
    ap.add_argument("--delay", type=float, default=0.6, help="giây tối thiểu giữa 2 request cùng tên miền")
    ap.add_argument("--browser-workers", type=int, default=2)
    ap.add_argument("--no-browser", action="store_true", help="tắt Playwright dự phòng")
    ap.add_argument("--output", default=OUTPUT_FILE)
    ap.add_argument("--inspect", default="", help="tên nguồn để kiểm tra selector")
    ap.add_argument("--list-sites", action="store_true", help="liệt kê các nguồn và trạng thái bật/tắt")
    args = ap.parse_args(argv)

    if args.list_sites:
        for k, v in SITES.items():
            print(f"{k:<12} {'BẬT' if v.get('enabled', True) else 'tắt'}  {v['domain']}")
        return

    sites = [s.strip() for s in (args.sites.split(",") if args.sites else [k for k, v in SITES.items() if v.get("enabled", True)]) if s.strip()]
    bad = [s for s in sites if s not in SITES]
    if bad:
        sys.exit(f"Nguồn không có trong SITES: {bad}. Có: {list(SITES)}")
    districts = [d for d in (args.districts.split(",") if args.districts else ALL_DISTRICTS) if d]
    wanted_names = {DISTRICT_NAME[d] for d in districts if d in DISTRICT_NAME} if args.districts else set()

    fetcher = Fetcher(args.delay, not args.no_browser, args.browser_workers,
                      [SITES[s]["domain"] for s in SITES if SITES[s].get("prefer_browser")])
    t0 = time.time()
    try:
        if args.inspect:
            return inspect_site(args.inspect, fetcher)

        records = []
        with ThreadPoolExecutor(max_workers=max(4, len(sites) + len(districts))) as ex:
            futs = {}
            for s in sites:
                if SITES[s]["type"] == "nextdata":
                    for d in districts:
                        futs[ex.submit(scrape_nhatot_district, d, fetcher, args.max_pages)] = f"{s}/{d}"
                else:
                    futs[ex.submit(scrape_html_site, s, fetcher, args.site_pages, args.workers, districts, args.max_pages)] = s
            for f in as_completed(futs):
                try:
                    records += f.result()
                except Exception as e:  # noqa
                    logger.error(f"Nguồn {futs[f]} thất bại: {e}")
    finally:
        fetcher.close()

    records = [r for r in records if district_ok(r, wanted_names)]
    drop_hotline_phones(records)
    records = dedupe(records)
    with open(args.output, "w", encoding="utf-8") as f:
        for r in records:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")

    by = {}
    for r in records:
        s = by.setdefault(r["nguon"], [0, 0, 0])
        s[0] += 1
        s[1] += bool(r["phone_raw"])
        s[2] += bool(r.get("contact_raw")) and not r["phone_raw"]
    for k, (n, p, c) in by.items():
        logger.info(f"  {k}: {n} tin, {p} có SĐT, {c} chỉ có Zalo/Facebook")
    logger.info(f"HOÀN TẤT: {len(records)} tin trong {time.time()-t0:.1f}s -> {args.output}")
    if not records:
        sys.exit(1)


if __name__ == "__main__":
    main()