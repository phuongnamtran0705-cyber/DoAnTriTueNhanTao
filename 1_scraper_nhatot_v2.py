import json
import re
import sys
import time
import random
import logging
import argparse
from pathlib import Path
 
from playwright.sync_api import sync_playwright
 
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)
 
BASE = "https://www.nhatot.com"
 
DISTRICTS = [
    "quan-hai-chau",
    "quan-thanh-khe",
    "quan-son-tra",
    "quan-ngu-hanh-son",
    "quan-lien-chieu",
    "quan-cam-le",
    "huyen-hoa-vang",
]
 
MAX_LIST_PAGES_PER_DISTRICT = 2   # mỗi trang ~20 tin => tối đa ~40 tin/quận
DELAY_RANGE = (4.0, 8.0)
OUTPUT_FILE = "raw_listings.jsonl"
 
NEXT_DATA_RE = re.compile(
    r'<script id="__NEXT_DATA__" type="application/json">(.*?)</script>',
    re.DOTALL,
)
 
STRONG_BLOCK_SIGNALS = [
    "attention required! | cloudflare",
    "checking your browser before accessing",
    "cf-browser-verification",
    "just a moment...",
    "verify you are human",
    "please complete the security check",
    'id="challenge-running"',
    'id="cf-challenge',
]
 
 
def check_blocked(html: str) -> bool:
    lower = html.lower()
    for sig in STRONG_BLOCK_SIGNALS:
        if sig in lower:
            logger.warning(f"Dấu hiệu chặn rõ ràng: '{sig}'")
            return True
    if len(html) < 2000:
        logger.warning(f"HTML trả về quá ngắn ({len(html)} ký tự).")
        return True
    return False
 
 
def extract_next_data(html: str) -> dict | None:
    m = NEXT_DATA_RE.search(html)
    if not m:
        return None
    try:
        return json.loads(m.group(1))
    except json.JSONDecodeError:
        return None
 
 
def extract_ads_from_next_data(data: dict) -> list[dict]:
    """Đi đúng đường dẫn đã xác nhận qua sample_next_data.json thật."""
    try:
        return data["props"]["initialState"]["adlisting"]["data"]["ads"] or []
    except (KeyError, TypeError):
        return []
 
 
def ad_to_raw_record(ad: dict) -> dict | None:
    title = ad.get("subject")
    if not title:
        return None
 
    list_id = ad.get("list_id") or ad.get("ad_id")
    url = f"{BASE}/rao-vat/{list_id}.htm" if list_id else "#"
 
    address_parts = [
        ad.get("street_name", ""),
        ad.get("ward_name", ""),
        ad.get("area_name", ""),
    ]
    address_raw = ", ".join(p for p in address_parts if p)
 
    return {
        "title": title,
        "url": url,
        "price_raw": str(ad.get("price", "")) if ad.get("price") is not None else "",
        "area_raw": str(ad.get("size") or ad.get("area") or ""),
        "address_raw": address_raw,
        "body_raw": ad.get("body", ""),      # mô tả thật, đầy đủ - ưu tiên dùng cái này
        "phone_raw": "",                      # cố tình để trống - xem ghi chú đầu file
        "vi_do_raw": ad.get("latitude"),
        "kinh_do_raw": ad.get("longitude"),
        "nguon": "nhatot.com",
        "scraped_at": time.strftime("%Y-%m-%d %H:%M:%S"),
    }
 
 
def save_jsonl(items: list[dict], filepath: str):
    with open(filepath, "a", encoding="utf-8") as f:
        for item in items:
            f.write(json.dumps(item, ensure_ascii=False) + "\n")
 
 
def load_page(page, url: str) -> str | None:
    logger.info(f"Đang mở: {url}")
    page.goto(url, timeout=30000, wait_until="domcontentloaded")
    page.wait_for_timeout(1500)
    html = page.content()
 
    if check_blocked(html):
        Path("debug_page.html").write_text(html, encoding="utf-8")
        logger.error(
            f"Nghi ngờ bị chặn tại {url}. Đã lưu 'debug_page.html' để kiểm tra. DỪNG."
        )
        sys.exit(1)
 
    return html
 
 
def inspect_mode(context):
    page = context.new_page()
    url = f"{BASE}/thue-phong-tro-quan-hai-chau-da-nang"
    html = load_page(page, url)
    data = extract_next_data(html)
 
    if data is None:
        logger.warning("Không tìm thấy __NEXT_DATA__.")
        page.close()
        return
 
    ads = extract_ads_from_next_data(data)
    logger.info(f"Tìm thấy {len(ads)} tin trong trang mẫu.")
 
    if ads:
        sample_records = [ad_to_raw_record(ad) for ad in ads[:3]]
        Path("sample_extracted.json").write_text(
            json.dumps(sample_records, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        logger.info("Đã lưu 3 tin mẫu đã trích xuất vào 'sample_extracted.json' - mở xem thử.")
 
    page.close()
 
 
def main(districts=None, max_pages=None, output_file=None):
    districts = districts if districts is not None else DISTRICTS
    max_pages = max_pages if max_pages is not None else MAX_LIST_PAGES_PER_DISTRICT
    out_path = output_file or OUTPUT_FILE
 
    Path(out_path).write_text("", encoding="utf-8")  # bắt đầu file mới mỗi lần chạy qua web demo
    seen_list_ids = set()
    total_saved = 0
 
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
            ),
            locale="vi-VN",
            viewport={"width": 1366, "height": 768},
        )
        page = context.new_page()
 
        for district in districts:
            logger.info(f"=== Quận: {district} ===")
            district_items = []
 
            for pnum in range(1, max_pages + 1):
                url = f"{BASE}/thue-phong-tro-{district}-da-nang"
                if pnum > 1:
                    url += f"?offset={(pnum - 1) * 20}"
 
                html = load_page(page, url)
                data = extract_next_data(html)
                if data is None:
                    logger.warning(f"Không tìm thấy __NEXT_DATA__ tại {url}, bỏ qua trang này.")
                    continue
 
                ads = extract_ads_from_next_data(data)
                logger.info(f"  Trang {pnum}: {len(ads)} tin")
 
                new_count = 0
                for ad in ads:
                    lid = ad.get("list_id")
                    if lid in seen_list_ids:
                        continue
                    seen_list_ids.add(lid)
                    record = ad_to_raw_record(ad)
                    if record:
                        district_items.append(record)
                        new_count += 1
 
                if pnum > 1 and new_count == 0:
                    logger.warning(
                        "  -> Trang này không có tin mới nào (toàn bộ trùng trang trước). "
                        "Tham số phân trang '?offset=' có thể chưa đúng cho trang này - "
                        "bỏ qua các trang sau của quận này."
                    )
                    break
 
                time.sleep(random.uniform(*DELAY_RANGE))
 
            save_jsonl(district_items, out_path)
            total_saved += len(district_items)
            logger.info(f"Đã lưu {len(district_items)} tin cho quận {district}")
 
        page.close()
        browser.close()
 
    logger.info(f"HOÀN TẤT. Tổng số tin đã cào: {total_saved}. File: {out_path}")
    return total_saved
 
 
def parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument("--inspect", action="store_true")
    parser.add_argument(
        "--districts",
        type=str,
        default=None,
        help="Danh sách quận cách nhau bởi dấu phẩy, vd: quan-hai-chau,quan-son-tra. "
             "Mặc định: cào tất cả 7 quận/huyện.",
    )
    parser.add_argument(
        "--max-pages",
        type=int,
        default=None,
        help="Số trang danh sách tối đa mỗi quận (mỗi trang ~20 tin). Mặc định: 2.",
    )
    return parser.parse_args()
 
 
if __name__ == "__main__":
    args = parse_args()
 
    if args.inspect:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            context = browser.new_context(
                user_agent=(
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                    "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
                ),
                locale="vi-VN",
                viewport={"width": 1366, "height": 768},
            )
            inspect_mode(context)
            browser.close()
    else:
        districts = args.districts.split(",") if args.districts else None
        main(districts=districts, max_pages=args.max_pages)