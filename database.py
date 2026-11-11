import mysql.connector
from werkzeug.security import generate_password_hash, check_password_hash
 
DB_CONFIG = {
    "host": "localhost",
    "user": "root",
    "password": "",  # Mặc định của Laragon/XAMPP - đổi lại nếu bạn có set password khác
    "database": "phongtro_db",
    "charset": "utf8mb4",
}
 
 
def get_db_connection():
    return mysql.connector.connect(**DB_CONFIG)
 
 
def _existing_columns(cursor, table_name: str) -> set:
    cursor.execute("""
        SELECT COLUMN_NAME FROM INFORMATION_SCHEMA.COLUMNS
        WHERE TABLE_SCHEMA = %s AND TABLE_NAME = %s
    """, (DB_CONFIG["database"], table_name))
    return {row[0] for row in cursor.fetchall()}
 
 
def init_db():
    """
    Tạo bảng nếu chưa có, tự động thêm cột còn thiếu (migrate an toàn).
    KHÔNG bao giờ DROP TABLE / xoá dữ liệu cũ trong rooms hoặc users.
    """
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
 
        # ---- 1. Bảng rooms ----
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS rooms (
                id INT AUTO_INCREMENT PRIMARY KEY,
                title VARCHAR(255) NOT NULL,
                gia_thue INT NOT NULL,
                quan VARCHAR(100) NOT NULL,
                dien_tich FLOAT NOT NULL,
                tien_ich TEXT,
                mo_ta TEXT,
                vi_do FLOAT DEFAULT NULL,
                kinh_do FLOAT DEFAULT NULL,
                nguon VARCHAR(100) DEFAULT 'Chưa rõ nguồn',
                url VARCHAR(255) DEFAULT '#',
                so_dien_thoai VARCHAR(20) DEFAULT '0905123456',
                nguoi_dang VARCHAR(100) DEFAULT 'Chủ trọ',
                user_id INT DEFAULT NULL,
                ngay_dang TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
        """)
 
        # Thêm cột còn thiếu nếu bảng rooms đã tồn tại từ trước với cấu trúc cũ hơn
        rooms_cols = _existing_columns(cursor, "rooms")
        extra_columns = {
            "so_dien_thoai": "VARCHAR(20) DEFAULT '0905123456'",
            "nguoi_dang": "VARCHAR(100) DEFAULT 'Chủ trọ'",
            "user_id": "INT DEFAULT NULL",
            "url": "VARCHAR(255) DEFAULT '#'",
            "nguon": "VARCHAR(100) DEFAULT 'Chưa rõ nguồn'",
            "lien_he_khac": "VARCHAR(255) DEFAULT ''",   # Zalo/Facebook người đăng công khai trong tin
            "trang_thai_admin": "TINYINT DEFAULT NULL",  # NULL = tự động theo báo cáo; 1 = admin xác nhận HẾT; 0 = admin xác nhận CÒN
        }
        for col_name, col_def in extra_columns.items():
            if col_name not in rooms_cols:
                cursor.execute(f"ALTER TABLE rooms ADD COLUMN {col_name} {col_def}")
                print(f"-> Đã thêm cột '{col_name}' vào bảng rooms")
 
        # ---- 2. Bảng users (KHÔNG drop nếu đã tồn tại) ----
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id INT AUTO_INCREMENT PRIMARY KEY,
                username VARCHAR(50) UNIQUE NOT NULL,
                email VARCHAR(100) UNIQUE NOT NULL,
                phone VARCHAR(20) NOT NULL,
                full_name VARCHAR(100) NOT NULL,
                password VARCHAR(255) NOT NULL,
                role VARCHAR(20) DEFAULT 'user',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
        """)
 
        # ---- 3. Tạo admin mặc định CHỈ KHI chưa có admin nào ----
        cursor.execute("SELECT COUNT(*) FROM users WHERE role = 'admin'")
        admin_count = cursor.fetchone()[0]
        if admin_count == 0:
            hashed_pw = generate_password_hash("admin123")
            cursor.execute("""
                INSERT INTO users (username, email, phone, full_name, password, role)
                VALUES (%s, %s, %s, %s, %s, %s)
            """, ("admin", "admin@phongtro.vn", "0905123456", "Quản Trị Viên", hashed_pw, "admin"))
            print("-> Đã tạo tài khoản admin mặc định (admin / admin123)")
 
        # ---- 4. Bảng inquiries: khách để lại SĐT hỏi phòng, KHÔNG cần đăng nhập ----
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS inquiries (
                id INT AUTO_INCREMENT PRIMARY KEY,
                room_id INT NOT NULL,
                customer_name VARCHAR(100) NOT NULL,
                customer_phone VARCHAR(20) NOT NULL,
                note TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (room_id) REFERENCES rooms(id) ON DELETE CASCADE
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
        """)
 
        # ---- 5. Bảng reviews: khách đánh giá sao + bình luận, KHÔNG cần đăng nhập ----
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS reviews (
                id INT AUTO_INCREMENT PRIMARY KEY,
                room_id INT NOT NULL,
                customer_name VARCHAR(100) NOT NULL,
                customer_phone VARCHAR(20) DEFAULT NULL,
                rating INT NOT NULL,
                comment TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (room_id) REFERENCES rooms(id) ON DELETE CASCADE,
                CONSTRAINT chk_rating CHECK (rating BETWEEN 1 AND 5)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
        """)
 
        # ---- 6. Bảng room_reports: sinh viên báo "đã hết trọ" / "vẫn còn", KHÔNG cần đăng nhập ----
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS room_reports (
                id INT AUTO_INCREMENT PRIMARY KEY,
                room_id INT NOT NULL,
                reporter_key VARCHAR(64) NOT NULL,
                kind VARCHAR(10) NOT NULL,
                note VARCHAR(255) DEFAULT '',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE KEY uq_room_reporter (room_id, reporter_key),
                FOREIGN KEY (room_id) REFERENCES rooms(id) ON DELETE CASCADE
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
        """)
        rr_cols = _existing_columns(cursor, "room_reports")
        for col_name, col_def in {
            "reporter_phone": "VARCHAR(20) DEFAULT NULL",   # SĐT người báo (chỉ admin thấy, dùng để xác minh)
            "verified": "TINYINT DEFAULT 0",                # 1 = SĐT trùng số đã để lại hỏi phòng này
        }.items():
            if col_name not in rr_cols:
                cursor.execute(f"ALTER TABLE room_reports ADD COLUMN {col_name} {col_def}")
                print(f"-> Đã thêm cột '{col_name}' vào bảng room_reports")

        conn.commit()
        cursor.close()
        conn.close()
        print("-> Khởi tạo/migrate CSDL MySQL thành công!")
    except Exception as e:
        print("Lỗi khởi tạo Database:", e)
 
 
# --- XỬ LÝ TÀI KHOẢN ---
 
def create_user(username, email, phone, full_name, password, role="user"):
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        hashed_password = generate_password_hash(password)
        sql = """
            INSERT INTO users (username, email, phone, full_name, password, role)
            VALUES (%s, %s, %s, %s, %s, %s)
        """
        cursor.execute(sql, (username, email, phone, full_name, hashed_password, role))
        conn.commit()
        cursor.close()
        conn.close()
        return True, "Đăng ký tài khoản thành công!"
    except mysql.connector.Error as err:
        if err.errno == 1062:
            return False, "Tên đăng nhập hoặc Email đã tồn tại trên hệ thống!"
        return False, f"Lỗi CSDL: {err}"
 
 
def verify_user(username_or_email, password):
    try:
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)
        sql = "SELECT * FROM users WHERE username = %s OR email = %s"
        cursor.execute(sql, (username_or_email, username_or_email))
        user = cursor.fetchone()
        cursor.close()
        conn.close()
 
        if user and check_password_hash(user["password"], password):
            return user
        return None
    except Exception as e:
        print("Lỗi xác thực người dùng:", e)
        return None
 
 
# --- XỬ LÝ PHÒNG TRỌ ---
 
# --- TRẠNG THÁI CÒN / HẾT TRỌ (sinh viên báo cho nhau đỡ mất thời gian) ---
# Quy tắc tự động (đếm các báo cáo trong REPORT_WINDOW_DAYS ngày gần nhất, mỗi người 1 phiếu/phòng):
#   - admin đã xác nhận (trang_thai_admin) -> theo admin, bỏ qua báo cáo
#   - số người báo "hết" >= HET_TRO_THRESHOLD và nhiều hơn số người báo "còn" -> 'het'  (ẩn khỏi gợi ý)
#   - có người báo "hết" (chưa đủ ngưỡng) và nhiều hơn số báo "còn"           -> 'nghi_het' (cảnh báo)
#   - còn lại                                                                   -> 'con'
REPORT_WINDOW_DAYS = 30
HET_TRO_THRESHOLD = 2

_AVAIL_COLS = (
    "(SELECT COUNT(*) FROM room_reports rr WHERE rr.room_id = rooms.id AND rr.kind = 'het' "
    f"AND rr.created_at >= NOW() - INTERVAL {REPORT_WINDOW_DAYS} DAY) AS het_count, "
    "(SELECT COUNT(*) FROM room_reports rr WHERE rr.room_id = rooms.id AND rr.kind = 'con' "
    f"AND rr.created_at >= NOW() - INTERVAL {REPORT_WINDOW_DAYS} DAY) AS con_count, "
    "(SELECT MAX(rr.created_at) FROM room_reports rr WHERE rr.room_id = rooms.id AND rr.kind = 'het' "
    f"AND rr.created_at >= NOW() - INTERVAL {REPORT_WINDOW_DAYS} DAY) AS last_het_at, "
    "(SELECT COUNT(*) FROM room_reports rr WHERE rr.room_id = rooms.id AND rr.kind = 'het' AND rr.verified = 1 "
    f"AND rr.created_at >= NOW() - INTERVAL {REPORT_WINDOW_DAYS} DAY) AS verified_het"
)


def _apply_availability(r):
    het, con = int(r.get("het_count") or 0), int(r.get("con_count") or 0)
    vhet = int(r.get("verified_het") or 0)      # báo hết đã xác minh qua SĐT từng hỏi phòng này
    admin = r.get("trang_thai_admin")
    if admin == 1:
        st = "het"
    elif admin == 0:
        st = "con"
    elif (het >= HET_TRO_THRESHOLD or vhet >= 1) and het > con:
        st = "het"
    elif het >= 1 and het > con:
        st = "nghi_het"
    else:
        st = "con"
    last = r.get("last_het_at")
    r["het_count"], r["con_count"], r["verified_het"] = het, con, vhet
    r["trang_thai"], r["het_tro"] = st, st == "het"
    r["trang_thai_admin"] = None if admin is None else int(admin)
    r["last_het_at"] = last.strftime("%d/%m/%Y") if hasattr(last, "strftime") else (str(last) if last else "")
    return r


def add_room_report(room_id, reporter_key, kind, note="", reporter_phone=None, verified=False, drop_key=None):
    """Ghi 1 báo cáo ('het' hoặc 'con'). Mỗi người (reporter_key) chỉ có 1 phiếu/phòng, báo lại sẽ ghi đè.
    drop_key: phiếu cũ của cùng người (khóa theo trình duyệt) sẽ bị xóa khi họ báo lại bằng SĐT, tránh tính 2 lần."""
    if kind not in ("het", "con"):
        return False
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        if drop_key and drop_key != reporter_key:
            cursor.execute("DELETE FROM room_reports WHERE room_id = %s AND reporter_key = %s", (room_id, drop_key))
        cursor.execute("""
            INSERT INTO room_reports (room_id, reporter_key, kind, note, reporter_phone, verified)
            VALUES (%s, %s, %s, %s, %s, %s)
            ON DUPLICATE KEY UPDATE kind = VALUES(kind), note = VALUES(note),
                reporter_phone = VALUES(reporter_phone), verified = VALUES(verified), created_at = CURRENT_TIMESTAMP
        """, (room_id, reporter_key, kind, (note or "")[:255], reporter_phone, 1 if verified else 0))
        conn.commit()
        cursor.close()
        conn.close()
        return True
    except Exception as e:
        print("Lỗi lưu báo cáo trạng thái phòng:", e)
        return False


def _norm_phone(raw):
    d = "".join(ch for ch in str(raw or "") if ch.isdigit())
    if d.startswith("84") and len(d) == 11:
        d = "0" + d[2:]
    return d


def phone_has_inquiry(room_id, phone):
    """True nếu SĐT này từng để lại yêu cầu hỏi chính phòng này (nút 'Để lại SĐT hỏi phòng') -> báo cáo được xác minh."""
    target = _norm_phone(phone)
    if not target:
        return False
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT customer_phone FROM inquiries WHERE room_id = %s", (room_id,))
        rows = cursor.fetchall()
        cursor.close()
        conn.close()
        return any(_norm_phone(r[0]) == target for r in rows)
    except Exception as e:
        print("Lỗi đối chiếu SĐT:", e)
        return False


def set_room_status_admin(room_id, status):
    """status: 'het' (admin xác nhận hết), 'con' (xác nhận còn + xóa các báo cáo cũ), 'auto' (theo báo cáo)."""
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        if status == "het":
            cursor.execute("UPDATE rooms SET trang_thai_admin = 1 WHERE id = %s", (room_id,))
        elif status == "con":
            cursor.execute("UPDATE rooms SET trang_thai_admin = 0 WHERE id = %s", (room_id,))
            cursor.execute("DELETE FROM room_reports WHERE room_id = %s", (room_id,))
        else:
            cursor.execute("UPDATE rooms SET trang_thai_admin = NULL WHERE id = %s", (room_id,))
        conn.commit()
        cursor.close()
        conn.close()
        return True
    except Exception as e:
        print("Lỗi cập nhật trạng thái phòng:", e)
        return False


def get_recent_reports(limit=60):
    """Các báo cáo gần đây (cho trang admin)."""
    try:
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)
        cursor.execute("""
            SELECT rr.id, rr.room_id, rr.kind, rr.note, rr.created_at, rr.reporter_phone, rr.verified, rooms.title, rooms.quan
            FROM room_reports rr JOIN rooms ON rooms.id = rr.room_id
            ORDER BY rr.created_at DESC LIMIT %s
        """, (int(limit),))
        rows = cursor.fetchall()
        cursor.close()
        conn.close()
        for r in rows:
            r["created_at"] = r["created_at"].strftime("%d/%m/%Y %H:%M") if hasattr(r["created_at"], "strftime") else str(r["created_at"])
            ph = r.get("reporter_phone") or ""
            r["reporter_phone"] = (ph[:4] + "***" + ph[-3:]) if len(ph) >= 8 else ph      # che bớt khi hiển thị
            r["verified"] = bool(r.get("verified"))
        return rows
    except Exception as e:
        print("Lỗi lấy báo cáo:", e)
        return []


def get_all_rooms():
    try:
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)
        cursor.execute("""
            SELECT rooms.*, """ + _AVAIL_COLS + """,
                   COALESCE(AVG(reviews.rating), 0) AS avg_rating,
                   COUNT(reviews.id) AS review_count
            FROM rooms
            LEFT JOIN reviews ON reviews.room_id = rooms.id
            GROUP BY rooms.id
            ORDER BY rooms.id DESC
        """)
        rooms = cursor.fetchall()
        cursor.close()
        conn.close()
 
        for r in rooms:
            if r["gia_thue"] and r["gia_thue"] < 100000:
                r["gia_thue_vnd"] = r["gia_thue"] * 1000
            else:
                r["gia_thue_vnd"] = r["gia_thue"]
            r["avg_rating"] = round(float(r["avg_rating"]), 1)
            _apply_availability(r)
        return rooms
    except Exception as e:
        print("Lỗi truy vấn phòng trọ:", e)
        return []
 
 
def list_rooms():
    return get_all_rooms()
 
 
def get_rooms_with_coords():
    """Lấy các phòng có tọa độ hợp lệ (vi_do, kinh_do khác NULL) - dùng cho bản đồ nhiệt."""
    try:
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)
        cursor.execute("""
            SELECT id, title, quan, gia_thue, dien_tich, vi_do, kinh_do, url,
                   so_dien_thoai, nguoi_dang, trang_thai_admin, """ + _AVAIL_COLS + """
            FROM rooms
            WHERE vi_do IS NOT NULL AND kinh_do IS NOT NULL
              AND vi_do != 0 AND kinh_do != 0
        """)
        rooms = cursor.fetchall()
        cursor.close()
        conn.close()
        for r in rooms:
            if r["gia_thue"] and r["gia_thue"] < 100000:
                r["gia_thue_vnd"] = r["gia_thue"] * 1000
            else:
                r["gia_thue_vnd"] = r["gia_thue"]
            _apply_availability(r)
        return rooms
    except Exception as e:
        print("Lỗi lấy tọa độ phòng trọ:", e)
        return []
 
 
def get_room_by_url(url: str):
    """Dùng để chống trùng khi import dữ liệu cào được."""
    if not url or url == "#":
        return None
    try:
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)
        cursor.execute("SELECT id FROM rooms WHERE url = %s", (url,))
        row = cursor.fetchone()
        cursor.close()
        conn.close()
        return row
    except Exception as e:
        print("Lỗi kiểm tra trùng url:", e)
        return None
 
 
def add_room(room: dict) -> bool:
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        sql = """
            INSERT INTO rooms (title, gia_thue, quan, dien_tich, tien_ich, mo_ta, vi_do, kinh_do, nguon, url, so_dien_thoai, nguoi_dang, user_id, lien_he_khac)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        """
        val = (
            room.get("title"),
            room.get("gia_thue"),
            room.get("quan"),
            room.get("dien_tich"),
            room.get("tien_ich"),
            room.get("mo_ta"),
            room.get("vi_do"),
            room.get("kinh_do"),
            room.get("nguon", "Chưa rõ nguồn"),
            room.get("url", "#"),
            room.get("so_dien_thoai", "0905123456"),
            room.get("nguoi_dang", "Chủ trọ"),
            room.get("user_id"),
            room.get("lien_he_khac", ""),
        )
        cursor.execute(sql, val)
        conn.commit()
        cursor.close()
        conn.close()
        return True
    except Exception as e:
        print("Lỗi thêm phòng trọ:", e)
        return False
 
 
def delete_room(room_id):
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("DELETE FROM rooms WHERE id = %s", (room_id,))
        conn.commit()
        cursor.close()
        conn.close()
        return True
    except Exception as e:
        print("Lỗi xóa phòng trọ:", e)
        return False
 
 
def get_room_by_id(room_id):
    try:
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)
        cursor.execute("""
            SELECT rooms.*, """ + _AVAIL_COLS + """,
                   COALESCE(AVG(reviews.rating), 0) AS avg_rating,
                   COUNT(reviews.id) AS review_count
            FROM rooms
            LEFT JOIN reviews ON reviews.room_id = rooms.id
            WHERE rooms.id = %s
            GROUP BY rooms.id
        """, (room_id,))
        room = cursor.fetchone()
        cursor.close()
        conn.close()
        if room:
            room["avg_rating"] = round(float(room["avg_rating"]), 1)
            _apply_availability(room)
        return room
    except Exception as e:
        print("Lỗi lấy phòng:", e)
        return None
 
 
def update_room(room_id, room_data):
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        sql = """
            UPDATE rooms
            SET title = %s, gia_thue = %s, quan = %s, dien_tich = %s, tien_ich = %s, mo_ta = %s, so_dien_thoai = %s
            WHERE id = %s
        """
        val = (
            room_data.get("title"),
            room_data.get("gia_thue"),
            room_data.get("quan"),
            room_data.get("dien_tich"),
            room_data.get("tien_ich"),
            room_data.get("mo_ta"),
            room_data.get("so_dien_thoai"),
            room_id,
        )
        cursor.execute(sql, val)
        conn.commit()
        cursor.close()
        conn.close()
        return True
    except Exception as e:
        print("Lỗi cập nhật phòng:", e)
        return False
 
 
# --- ĐÁNH GIÁ PHÒNG TRỌ (không cần đăng nhập) ---
 
def add_review(room_id, customer_name, customer_phone, rating, comment=""):
    try:
        rating = int(rating)
        if rating < 1 or rating > 5:
            return False, "Số sao phải từ 1 đến 5!"
 
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO reviews (room_id, customer_name, customer_phone, rating, comment)
            VALUES (%s, %s, %s, %s, %s)
        """, (room_id, customer_name, customer_phone, rating, comment))
        conn.commit()
        cursor.close()
        conn.close()
        return True, "Đã gửi đánh giá thành công!"
    except Exception as e:
        print("Lỗi lưu đánh giá:", e)
        return False, "Có lỗi xảy ra, vui lòng thử lại!"
 
 
def get_reviews_for_room(room_id):
    """Danh sách đánh giá công khai cho 1 phòng (không kèm SĐT khách)."""
    try:
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)
        cursor.execute("""
            SELECT id, customer_name, rating, comment, created_at
            FROM reviews
            WHERE room_id = %s
            ORDER BY created_at DESC
        """, (room_id,))
        rows = cursor.fetchall()
        cursor.close()
        conn.close()
        return rows
    except Exception as e:
        print("Lỗi lấy đánh giá:", e)
        return []
 
 
def get_all_reviews_admin():
    """Cho admin xem/duyệt toàn bộ đánh giá kèm SĐT khách (để xác minh nếu cần)."""
    try:
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)
        cursor.execute("""
            SELECT reviews.*, rooms.title AS room_title
            FROM reviews
            JOIN rooms ON reviews.room_id = rooms.id
            ORDER BY reviews.created_at DESC
        """)
        rows = cursor.fetchall()
        cursor.close()
        conn.close()
        return rows
    except Exception as e:
        print("Lỗi lấy danh sách đánh giá:", e)
        return []
 
 
def delete_review(review_id):
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("DELETE FROM reviews WHERE id = %s", (review_id,))
        conn.commit()
        cursor.close()
        conn.close()
        return True
    except Exception as e:
        print("Lỗi xóa đánh giá:", e)
        return False
 
 
# --- YÊU CẦU LIÊN HỆ CỦA KHÁCH (không cần đăng nhập) ---
 
def add_inquiry(room_id, customer_name, customer_phone, note=""):
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO inquiries (room_id, customer_name, customer_phone, note)
            VALUES (%s, %s, %s, %s)
        """, (room_id, customer_name, customer_phone, note))
        conn.commit()
        cursor.close()
        conn.close()
        return True
    except Exception as e:
        print("Lỗi lưu yêu cầu liên hệ:", e)
        return False
 
 
def get_all_inquiries():
    """Cho admin xem danh sách khách đã để lại SĐT hỏi phòng nào."""
    try:
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)
        cursor.execute("""
            SELECT inquiries.*, rooms.title AS room_title, rooms.quan AS room_quan
            FROM inquiries
            JOIN rooms ON inquiries.room_id = rooms.id
            ORDER BY inquiries.created_at DESC
        """)
        rows = cursor.fetchall()
        cursor.close()
        conn.close()
        return rows
    except Exception as e:
        print("Lỗi lấy danh sách liên hệ:", e)
        return []
 
 
# --- BỘ LỌC FORM ---
 
def distinct_districts():
    rooms = get_all_rooms()
    districts = set()
    for r in rooms:
        if r.get("quan"):
            districts.add(r["quan"].strip())
    return sorted(districts)
 
 
def distinct_amenities():
    rooms = get_all_rooms()
    amenities_set = set()
    for r in rooms:
        if r.get("tien_ich"):
            items = [item.strip() for item in r["tien_ich"].split(",") if item.strip()]
            amenities_set.update(items)
    return sorted(amenities_set)
 

 
if __name__ == "__main__":
    init_db()