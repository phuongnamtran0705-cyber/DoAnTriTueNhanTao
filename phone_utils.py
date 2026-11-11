"""
phone_utils.py
--------------
Tách số điện thoại di động Việt Nam từ một đoạn văn bản (tiêu đề / mô tả tin đăng).
Chỉ lấy số được người đăng CÔNG KHAI trong nội dung tin - không phá cơ chế "bấm để hiện số".
"""
import re

# 0905123456 / 0905.123.456 / 0905 123 456 / +84 905 123 456 / 84905123456
_CANDIDATE = re.compile(r"(?<![\d.])(?:\+?84|0)[\s.\-]?\d(?:[\s.\-]?\d){8}(?!\d)")
# Đầu số di động VN hợp lệ (03x, 05x, 07x, 08x, 09x)
_MOBILE = re.compile(r"^0(?:3[2-9]|5[25689]|7[06-9]|8[1-9]|9\d)\d{7}$")
_CONTACT_HINT = re.compile(r"(liên hệ|lien he|\blh\b|sđt|sdt|zalo|gọi|call|hotline|phone|đt)", re.I)

# Số mẫu/giữ chỗ - KHÔNG phải số thật (số demo cũ của dự án)
PLACEHOLDER_PHONES = {"0905123456"}


def clean_phone(raw: str) -> str:
    """'+84 905.123.456' -> '0905123456'. Trả '' nếu không hợp lệ."""
    digits = re.sub(r"\D", "", raw or "")
    if digits.startswith("84") and len(digits) == 11:
        digits = "0" + digits[2:]
    if not _MOBILE.match(digits):
        return ""
    if len(set(digits)) <= 2 or digits in PLACEHOLDER_PHONES:
        return ""
    return digits


def extract_phones(text: str) -> list:
    """Danh sách SĐT hợp lệ trong text, theo thứ tự xuất hiện, không trùng.
    Số đứng ngay sau từ khóa liên hệ (LH, Zalo, SĐT...) được đưa lên đầu."""
    if not text:
        return []
    hinted, plain = [], []
    for m in _CANDIDATE.finditer(text):
        phone = clean_phone(m.group(0))
        if not phone:
            continue
        before = text[max(0, m.start() - 25):m.start()]
        bucket = hinted if _CONTACT_HINT.search(before) else plain
        if phone not in hinted and phone not in plain:
            bucket.append(phone)
    return hinted + plain


def extract_phone(text: str) -> str:
    phones = extract_phones(text)
    return phones[0] if phones else ""


# ---------------------------------------------------------------------------
# Liên hệ khác (Zalo / Facebook) mà người đăng CÔNG KHAI trong nội dung tin
# ---------------------------------------------------------------------------
_ZALO = re.compile(r"(?:https?://)?(?:chat\.)?zalo\.me/(?:\+?\d{9,12}|[A-Za-z0-9_.\-]{3,40})", re.I)
_FB = re.compile(r"(?:https?://)?(?:www\.|m\.|web\.)?(?:facebook\.com|fb\.com|fb\.me|m\.me)/[A-Za-z0-9_.\-/]+(?:\?id=\d+)?", re.I)
_FB_GENERIC = ("sharer", "share", "dialog", "plugins", "tr", "login", "groups", "events", "watch", "policies", "help")


def _norm_link(raw: str) -> str:
    link = raw.strip().rstrip(".,;:)!?")
    if not link.lower().startswith("http"):
        link = "https://" + link
    return link


def extract_contact_links(text: str, ignore=()) -> str:
    """Trả 1 liên kết liên hệ (ưu tiên Zalo, rồi Facebook cá nhân/trang) hoặc ''.
    `ignore`: danh sách chuỗi con - liên kết chứa chuỗi này bị bỏ (vd tên của chính trang web nguồn)."""
    if not text:
        return ""
    ign = [x.lower() for x in ignore]
    for rx in (_ZALO, _FB):
        for m in rx.finditer(text):
            link = _norm_link(m.group(0))
            low = link.lower()
            if any(x in low for x in ign):
                continue
            if rx is _FB:
                first = low.split("/", 3)[3].split("/")[0].split("?")[0] if low.count("/") >= 3 else ""
                if not first or first in _FB_GENERIC:
                    continue
            return link[:255]
    return ""