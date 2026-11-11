import json
import re
import logging

from phone_utils import extract_phone, clean_phone
 
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)
 
INPUT_FILE = "raw_listings.jsonl"
OUTPUT_FILE = "normalized_listings.jsonl"
 
# Các quận/huyện của Đà Nẵng - dùng để nhận diện trong địa chỉ/tiêu đề
DA_NANG_DISTRICTS = [
    "Hải Châu", "Thanh Khê", "Sơn Trà", "Ngũ Hành Sơn",
    "Liên Chiểu", "Cẩm Lệ", "Hòa Vang",
]
 
# Từ khóa tiện ích thường gặp trong tin đăng - mở rộng thêm nếu cần
AMENITY_KEYWORDS = [
    "máy lạnh", "điều hòa", "gác lửng", "gác", "ban công", "thang máy",
    "camera an ninh", "an ninh", "wifi", "nóng lạnh", "chỗ để xe",
    "giờ giấc tự do", "khép kín", "nội thất", "tủ lạnh", "máy giặt",
]
 
 
def extract_price_thousand_vnd(text: str) -> int:
    """
    Chuyển các dạng giá thường gặp về đơn vị NGHÌN ĐỒNG (khớp quy ước DB):
        "2.500.000đ"  -> 2500
        "2,5 triệu"   -> 2500
        "2.5tr"       -> 2500
        "2500k"       -> 2500
        "3 triệu 5"   -> 3500
    Trả về 0 nếu không parse được (bạn nên lọc bỏ các dòng này thủ công).
    """
    if not text:
        return 0
    t = text.lower().replace(" ", "")
 
    # Dạng viết tắt kiểu VN "3tr5" = 3,5 triệu (số lẻ đứng SAU "tr")
    m = re.search(r"(\d+)\s*(?:tr|triệu)\s*(\d)(?!\d)", t)
    if m:
        return int(m.group(1)) * 1000 + int(m.group(2)) * 100
 
    # Dạng "2,5tr" / "2.5tr" / "2,5triệu"
    m = re.search(r"(\d+[.,]?\d*)\s*(tr|triệu)", t)
    if m:
        return int(float(m.group(1).replace(",", ".")) * 1000)
 
    # Dạng "2500k"
    m = re.search(r"(\d+)\s*k\b", t)
    if m:
        return int(m.group(1))
 
    # Dạng số đầy đủ có dấu chấm phân cách nghìn: "2.500.000"
    m = re.search(r"(\d{1,3}(?:\.\d{3})+)", t)
    if m:
        full_number = int(m.group(1).replace(".", ""))
        return round(full_number / 1000)
 
    # Dạng số trần không dấu chấm, vd "2200000" hoặc đã là "2200"
    digits = re.sub(r"[^\d]", "", t)
    if digits:
        num = int(digits)
        # Nếu số lớn (>= 100000) coi là VNĐ đầy đủ -> quy về nghìn
        return round(num / 1000) if num >= 100000 else num
 
    return 0
 
 
def extract_area(text: str) -> float:
    """'25m2' / '25 m²' / '25,5m2' -> 25.0 / 25.5
    Cũng xử lý trường hợp chuỗi là số thuần (vd '25') khi lấy trực tiếp
    từ field JSON không kèm đơn vị."""
    if not text:
        return 0.0
    m = re.search(r"(\d+[.,]?\d*)\s*m", text.lower())
    if m:
        return float(m.group(1).replace(",", "."))
    # Không có chữ 'm' đi kèm - thử coi cả chuỗi là số thuần
    stripped = text.strip().replace(",", ".")
    if re.fullmatch(r"\d+(\.\d+)?", stripped):
        return float(stripped)
    return 0.0
 
 
# Sau sáp nhập hành chính (2025) nhiều tin chỉ ghi tên PHƯỜNG/XÃ mới, không ghi quận cũ.
# Ánh xạ GẦN ĐÚNG phường/xã mới -> quận cũ để biểu đồ/giá theo khu vực vẫn dùng được.
# Hãy đối chiếu lại nếu cần độ chính xác cao; có thể bổ sung thêm dòng.
WARD_TO_DISTRICT = {
    "hải vân": "Liên Chiểu", "hòa khánh": "Liên Chiểu", "hòa minh": "Liên Chiểu",
    "an khê": "Thanh Khê", "hòa cường": "Hải Châu", "an hải": "Sơn Trà",
    "hòa xuân": "Cẩm Lệ", "khuê trung": "Cẩm Lệ", "hòa thọ": "Cẩm Lệ",
    "bà nà": "Hòa Vang", "hòa phước": "Hòa Vang", "hòa tiến": "Hòa Vang",
    "mỹ an": "Ngũ Hành Sơn", "hòa quý": "Ngũ Hành Sơn", "khuê mỹ": "Ngũ Hành Sơn",
    "mân thái": "Sơn Trà", "phước mỹ": "Sơn Trà", "thọ quang": "Sơn Trà",
}


def extract_district(*texts: str) -> str:
    """Dò tên quận trong nhiều đoạn text (address, title...); nếu không có thì dò phường/xã mới."""
    combined = " ".join(t for t in texts if t).lower()
    for district in DA_NANG_DISTRICTS:
        if district.lower() in combined:
            return district
    for ward, district in WARD_TO_DISTRICT.items():
        if ward in combined:
            return district
    return "Chưa xác định"
 
 
def extract_amenities(*texts: str) -> str:
    combined = " ".join(t for t in texts if t).lower()
    found = [kw for kw in AMENITY_KEYWORDS if kw in combined]
    # Loại "gác" nếu đã có "gác lửng" để tránh trùng lặp
    if "gác lửng" in found and "gác" in found:
        found.remove("gác")
    return ", ".join(dict.fromkeys(found))  # dict.fromkeys giữ thứ tự, loại trùng
 
 
def normalize_record(raw: dict) -> dict | None:
    title = (raw.get("title") or "").strip()
    if not title:
        return None
 
    price = extract_price_thousand_vnd(raw.get("price_raw", ""))
    area = extract_area(raw.get("area_raw", ""))
    address = raw.get("address_raw", "") or ""
    district = extract_district(address, title)
    amenities = extract_amenities(title, address, raw.get("body_raw", ""))
    phone = clean_phone(raw.get("phone_raw") or "") or extract_phone(f"{title}\n{raw.get('body_raw') or ''}")
 
    # mo_ta: ưu tiên dùng mô tả thật (body_raw) nếu có - vd từ nhatot.com -
    # nếu không có thì ghép tạm từ title + address (trang không cung cấp mô tả riêng)
    body_raw = (raw.get("body_raw") or "").strip()
    if body_raw:
        mo_ta = body_raw
    else:
        mo_ta_parts = [title]
        if address:
            mo_ta_parts.append(f"Địa chỉ: {address}")
        mo_ta = ". ".join(mo_ta_parts)
 
    return {
        "title": title,
        "gia_thue": price,
        "quan": district,
        "dien_tich": area,
        "tien_ich": amenities,
        "mo_ta": mo_ta,
        "vi_do": raw.get("vi_do_raw"),    # dùng tọa độ thật nếu trang nguồn có sẵn
        "kinh_do": raw.get("kinh_do_raw"),
        "nguon": raw.get("nguon", "Không rõ"),
        "url": raw.get("url", "#"),
        # SĐT thật (nếu có); KHÔNG còn điền số giả 0905123456
        "so_dien_thoai": phone,
        "lien_he_khac": (raw.get("contact_raw") or "")[:255],   # Zalo/Facebook công khai trong tin
        "nguoi_dang": "Chủ trọ",
        # cờ để bạn dễ lọc khi review bằng mắt:
        "_can_review": price == 0 or area == 0 or district == "Chưa xác định",
    }
 
 
def main():
    normalized = []
    skipped = 0
 
    with open(INPUT_FILE, "r", encoding="utf-8") as f:
        for line_num, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue
            try:
                raw = json.loads(line)
            except json.JSONDecodeError:
                logger.warning(f"Dòng {line_num} không phải JSON hợp lệ, bỏ qua.")
                skipped += 1
                continue
 
            record = normalize_record(raw)
            if record is None:
                skipped += 1
                continue
            normalized.append(record)
 
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        for r in normalized:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
 
    with_phone = sum(1 for r in normalized if r["so_dien_thoai"])
    with_other = sum(1 for r in normalized if not r["so_dien_thoai"] and r["lien_he_khac"])
    logger.info(f"-> {with_phone}/{len(normalized)} tin có số điện thoại thật; {with_other} tin chỉ có Zalo/Facebook.")
    need_review = sum(1 for r in normalized if r["_can_review"])
    logger.info(f"Đã chuẩn hóa {len(normalized)} tin (bỏ qua {skipped} dòng lỗi).")
    logger.info(f"-> {need_review} tin có trường thiếu/không chắc (giá=0, diện tích=0, hoặc không rõ quận).")
    logger.info(f"Mở file '{OUTPUT_FILE}' để xem lại trước khi chạy bước 3 (import vào DB).")
    logger.info("Tìm các dòng có \"_can_review\": true để sửa tay trước khi import.")
 
 
if __name__ == "__main__":
    main()