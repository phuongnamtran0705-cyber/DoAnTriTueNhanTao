from flask import Flask, render_template, request, redirect, url_for, session, flash
import database
import price_analysis
import pwa
import socket
import subprocess
import threading
import time
import hashlib
import secrets
import json
import sys
import os

app = Flask(__name__)
app.config["TEMPLATES_AUTO_RELOAD"] = True
pwa.init_pwa(app)        # PWA: cài lên màn hình chính điện thoại (xem pwa.py)
app.secret_key = "tro_ai_danang_secret_key" # Đặt secret key cho session

database.init_db()


def _to_int(value, default=0):
    try:
        return int(float(str(value).replace(",", ".").strip()))
    except (TypeError, ValueError):
        return default


def _to_float(value, default=0.0):
    try:
        return float(str(value).replace(",", ".").strip())
    except (TypeError, ValueError):
        return default


@app.route("/", methods=["GET"])
def index():
    districts = database.distinct_districts()
    amenities = database.distinct_amenities()
    
    # Đã bỏ chức năng gợi ý khu vực (hàm get_top_recommended_districts chưa từng tồn tại trong database.py)
    recommended_districts = []
    
    return render_template(
        "index.html", 
        districts=districts, 
        amenities=amenities,
        recommended_districts=recommended_districts
    )

# --- ĐĂNG KÝ / ĐĂNG NHẬP / ĐĂNG XUẤT ---

@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username_or_email = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        user = database.verify_user(username_or_email, password)
        
        if user:
            session['user_id'] = user['id']
            session['username'] = user['username']
            session['full_name'] = user['full_name']
            session['role'] = user['role']
            return redirect(url_for("admin_dashboard" if user['role'] == 'admin' else "index"))
        else:
            flash("Mật khẩu hoặc tài khoản/email không chính xác!", "danger")

    return render_template("auth.html", mode="login")
@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("index"))

# --- LIÊN HỆ HỎI PHÒNG - KHÔNG CẦN ĐĂNG NHẬP ---
 
@app.route("/lien-he/<int:room_id>", methods=["POST"])
def lien_he(room_id):
    from flask import jsonify
 
    customer_name = request.form.get("customer_name", "").strip()
    customer_phone = request.form.get("customer_phone", "").strip()
    note = request.form.get("note", "").strip()
 
    if not customer_name or not customer_phone:
        return jsonify(success=False, message="Vui lòng nhập đầy đủ họ tên và số điện thoại!"), 400
 
    room = database.get_room_by_id(room_id)
    if not room:
        return jsonify(success=False, message="Phòng trọ không tồn tại!"), 404
 
    success = database.add_inquiry(room_id, customer_name, customer_phone, note)
    if success:
        owner_phone = (room.get('so_dien_thoai') or '').strip()
        other = (room.get('lien_he_khac') or '').strip()
        src = room.get('url') or ''
        if owner_phone:
            msg = f"Đã gửi yêu cầu liên hệ! Số điện thoại chủ trọ: {owner_phone}"
        elif other:
            msg = f"Đã gửi yêu cầu liên hệ! Chủ trọ chưa công khai SĐT, bạn có thể nhắn qua: {other}"
        else:
            msg = "Đã gửi yêu cầu liên hệ! Chủ trọ chưa công khai SĐT" + (f" - liên hệ qua tin gốc: {src}" if src.startswith('http') else ".")
        return jsonify(success=True, message=msg, phone=owner_phone, contact_link=other, url=src)
    else:
        return jsonify(success=False, message="Có lỗi xảy ra, vui lòng thử lại!"), 500
 
 
@app.route("/admin/inquiries")
def admin_inquiries():
    """Admin xem danh sách khách đã để lại SĐT hỏi phòng nào."""
    if session.get('role') != 'admin':
        flash("Bạn không có quyền truy cập trang này!", "danger")
        return redirect(url_for("login"))
    inquiries = database.get_all_inquiries()
    return render_template("admin_inquiries.html", inquiries=inquiries)

# --- QUẢN TRỊ ADMIN ---

@app.route("/admin/dashboard")
def admin_dashboard():
    if session.get('role') != 'admin':
        flash("Bạn không có quyền truy cập trang quản trị!", "danger")
        return redirect(url_for("login"))
    rooms = database.get_all_rooms()
    return render_template("admin_dashboard.html", rooms=rooms)

@app.route("/admin/edit/<int:room_id>", methods=["GET", "POST"])
def admin_edit_room(room_id):
    if session.get('role') != 'admin':
        return redirect(url_for("login"))
    
    room = database.get_room_by_id(room_id)
    if not room:
        flash("Phòng trọ không tồn tại!", "danger")
        return redirect(url_for("admin_dashboard"))

    if request.method == "POST":
        room_data = {
            'title': request.form.get('title'),
            'gia_thue': _to_int(request.form.get('gia_thue')),
            'quan': request.form.get('quan'),
            'dien_tich': _to_float(request.form.get('dien_tich')),
            'tien_ich': request.form.get('tien_ich'),
            'mo_ta': request.form.get('mo_ta'),
            'so_dien_thoai': request.form.get('so_dien_thoai')
        }
        if database.update_room(room_id, room_data):
            flash("Cập nhật thông tin phòng trọ thành công!", "success")
            return redirect(url_for("admin_dashboard"))
        else:
            flash("Có lỗi xảy ra khi cập nhật!", "danger")

    return render_template("admin_edit.html", room=room)

@app.route("/admin/delete/<int:room_id>")
def admin_delete_room(room_id):
    if session.get('role') != 'admin':
        return redirect(url_for("login"))
    database.delete_room(room_id)
    flash("Xóa phòng trọ thành công!", "success")
    return redirect(url_for("admin_dashboard"))

@app.route("/admin/add", methods=["GET", "POST"])
def add_room():
    if session.get('role') != 'admin':
        flash("Vui lòng đăng nhập với quyền quản trị để thực hiện chức năng này!", "danger")
        return redirect(url_for("login"))

    if request.method == "POST":
        room_data = {
            'title': request.form.get('title'),
            'gia_thue': _to_int(request.form.get('gia_thue')),
            'quan': request.form.get('quan'),
            'dien_tich': _to_float(request.form.get('dien_tich')),
            'tien_ich': request.form.get('tien_ich'),
            'mo_ta': request.form.get('mo_ta'),
            'so_dien_thoai': request.form.get('so_dien_thoai') or '',
            'nguon': 'Đăng tay qua Admin',
            'url': '#',
            'nguoi_dang': session.get('full_name', 'Chủ trọ'),
            'user_id': session.get('user_id'),
        }
        if database.add_room(room_data):
            flash("Đăng tin phòng trọ thành công!", "success")
            return redirect(url_for("admin_dashboard"))
        else:
            flash("Có lỗi xảy ra khi lưu tin đăng!", "danger")

    return render_template("add_room.html")

# --- ROUTE SEARCH GIỮ NGUYÊN ---
@app.route("/search", methods=["POST"])
def search():
    raw_budget = request.form.get("budget", "").strip()
    raw_area = request.form.get("area_min", "").strip()
    district = request.form.get("district", "").strip()
    keyword = request.form.get("keyword", "").strip()
    selected_amenities = request.form.getlist("amenities")

    budget = int(raw_budget) if raw_budget.isdigit() else 0
    if 0 < budget < 10000:
        budget = budget * 1000

    area_min = float(raw_area) if raw_area.replace('.', '', 1).isdigit() else 0
    all_rooms = database.get_all_rooms()
    scored_rooms = []

    for room in all_rooms:
        score = 0
        price = room.get('gia_thue') or 0
        real_price = price * 1000 if price < 100000 else price

        if budget > 0 and real_price <= budget: score += 30
        if district and district.lower() in (room.get('quan') or '').lower(): score += 25
        if keyword and keyword.lower() in f"{room.get('title','')} {room.get('mo_ta','')}".lower(): score += 20
        
        room['match_score'] = score
        scored_rooms.append(room)

    # Phòng đã báo hết trọ: mặc định xếp CUỐI danh sách (form có thể gửi hide_taken=1 để ẩn hẳn)
    if request.form.get("hide_taken"):
        scored_rooms = [r for r in scored_rooms if not r.get('het_tro')]
    scored_rooms.sort(key=lambda x: (1 if x.get('het_tro') else 0, -x['match_score']))
    return render_template("results.html", results=scored_rooms)

# tránh lỗi UnicodeEncodeError khi các script print() tiếng Việt có dấu.
_SUBPROCESS_ENV = os.environ.copy()
_SUBPROCESS_ENV["PYTHONIOENCODING"] = "utf-8"
_SUBPROCESS_ENV["PYTHONUTF8"] = "1"
 
# ---------------------------------------------------------------------------
# CÀO DỮ LIỆU CHẠY NỀN: bấm "Bắt đầu cào" -> chuyển ngay sang trang tiến trình,
# trình duyệt không bị "đứng" chờ. Trang tiến trình tự cập nhật log mỗi 2 giây.
# (Lưu trạng thái trong bộ nhớ của tiến trình Flask: phù hợp chạy 1 server như khi demo.)
# ---------------------------------------------------------------------------
_job_lock = threading.Lock()
_job = {"status": "idle", "step": "", "log": [], "results": [], "error": "",
        "started": 0.0, "finished": 0.0, "params": {}, "proc": None, "cancelled": False}
_MAX_LOG_LINES = 400
_SCRAPE_TIMEOUT = 900   # giây - quá thì tự dừng


def _job_log(line):
    with _job_lock:
        _job["log"].append(line.rstrip())
        if len(_job["log"]) > _MAX_LOG_LINES:
            del _job["log"][: len(_job["log"]) - _MAX_LOG_LINES]


def _job_set(**kw):
    with _job_lock:
        _job.update(kw)


def _run_step(cmd, timeout):
    """Chạy 1 lệnh, đẩy từng dòng output vào log theo thời gian thực. Trả về returncode."""
    _job_log("$ " + " ".join(cmd))
    proc = subprocess.Popen(
        cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
        encoding="utf-8", errors="replace", env=_SUBPROCESS_ENV, bufsize=1,
    )
    _job_set(proc=proc)
    timer = threading.Timer(timeout, proc.kill)
    timer.start()
    try:
        for line in proc.stdout:
            _job_log(line)
        proc.wait()
    finally:
        timer.cancel()
        _job_set(proc=None)
    return proc.returncode


def _scrape_worker(district, max_pages, sites):
    try:
        _job_set(step="1/2 Đang cào dữ liệu từ các trang nguồn…")
        cmd = [sys.executable, "-u", "scraper_multi.py", "--districts", district, "--max-pages", max_pages]
        if sites:
            cmd += ["--sites", sites]
        rc = _run_step(cmd, _SCRAPE_TIMEOUT)
        if _job["cancelled"]:
            _job_set(status="cancelled", step="Đã hủy.", finished=time.time())
            return
        if rc != 0:
            _job_set(status="error", step="Cào dữ liệu thất bại", finished=time.time(),
                     error="Cào dữ liệu thất bại - xem nhật ký bên dưới để biết chi tiết.")
            return

        _job_set(step="2/2 Đang chuẩn hóa dữ liệu…")
        rc = _run_step([sys.executable, "-u", "2_normalize.py"], 120)
        if rc != 0:
            _job_set(status="error", step="Chuẩn hóa thất bại", finished=time.time(),
                     error="Chuẩn hóa dữ liệu thất bại - xem nhật ký bên dưới.")
            return

        results = []
        try:
            with open("normalized_listings.jsonl", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line:
                        results.append(json.loads(line))
        except FileNotFoundError:
            _job_set(status="error", step="Không thấy file kết quả", finished=time.time(),
                     error="Không tìm thấy file kết quả sau khi chuẩn hóa.")
            return
        _job_set(status="done", step="Hoàn tất", results=results, finished=time.time())
    except Exception as e:  # noqa
        _job_set(status="error", step="Lỗi không mong đợi", finished=time.time(), error=str(e))


@app.route("/admin/scrape", methods=["GET"])
def admin_scrape():
    if session.get('role') != 'admin':
        flash("Bạn không có quyền truy cập trang này!", "danger")
        return redirect(url_for("login"))
    return render_template("admin_scrape.html", results=None, log_output=None,
                           job_status=_job["status"])


@app.route("/admin/scrape/run", methods=["POST"])
def admin_scrape_run():
    if session.get('role') != 'admin':
        return redirect(url_for("login"))

    with _job_lock:
        if _job["status"] == "running":
            flash("Đang có một tiến trình cào chạy - xem tiến độ bên dưới.", "warning")
            return redirect(url_for("admin_scrape_progress"))

    district = request.form.get("district", "quan-hai-chau")
    max_pages = request.form.get("max_pages", "1")
    if not max_pages.isdigit():
        max_pages = "1"
    sites = ",".join(request.form.getlist("sites"))   # không chọn = tất cả nguồn đang bật

    with _job_lock:
        _job.update(status="running", step="Đang khởi động…", log=[], results=[], error="",
                    started=time.time(), finished=0.0, cancelled=False, proc=None,
                    params={"district": district, "max_pages": max_pages, "sites": sites or "tất cả"})
    threading.Thread(target=_scrape_worker, args=(district, max_pages, sites), daemon=True).start()
    return redirect(url_for("admin_scrape_progress"))


@app.route("/admin/scrape/progress", methods=["GET"])
def admin_scrape_progress():
    if session.get('role') != 'admin':
        return redirect(url_for("login"))
    with _job_lock:
        job = dict(_job)
        job["log"] = list(_job["log"])
    if job["status"] == "idle":
        return redirect(url_for("admin_scrape"))
    return render_template("admin_scrape_progress.html", job=job, results=job["results"])


@app.route("/admin/scrape/status.json", methods=["GET"])
def admin_scrape_status():
    from flask import jsonify
    if session.get('role') != 'admin':
        return jsonify(status="forbidden"), 403
    with _job_lock:
        end = _job["finished"] or time.time()
        return jsonify(status=_job["status"], step=_job["step"], error=_job["error"],
                       elapsed=int(end - _job["started"]) if _job["started"] else 0,
                       log="\n".join(_job["log"][-120:]), count=len(_job["results"]))


@app.route("/admin/scrape/cancel", methods=["POST"])
def admin_scrape_cancel():
    if session.get('role') != 'admin':
        return redirect(url_for("login"))
    with _job_lock:
        _job["cancelled"] = True
        proc = _job["proc"]
    if proc:
        try:
            proc.terminate()
        except Exception:  # noqa
            pass
    flash("Đã gửi yêu cầu hủy tiến trình cào.", "warning")
    return redirect(url_for("admin_scrape_progress"))


@app.route("/admin/scrape/import", methods=["POST"])
def admin_scrape_import():
    if session.get('role') != 'admin':
        return redirect(url_for("login"))
 
    result = subprocess.run(
        [sys.executable, "3_import_to_db.py"],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
        timeout=60, env=_SUBPROCESS_ENV,
    )
 
    if result.returncode == 0:
        flash("Đã nhập dữ liệu vào Database thành công! Xem trong Quản lý phòng trọ.", "success")
    else:
        flash(f"Có lỗi khi nhập vào Database: {result.stderr}", "danger")
 
    return redirect(url_for("admin_dashboard"))
 

 # --- ĐÁNH GIÁ PHÒNG TRỌ - KHÔNG CẦN ĐĂNG NHẬP ---

@app.route("/danh-gia/<int:room_id>", methods=["POST"])
def danh_gia(room_id):
    from flask import jsonify

    customer_name = request.form.get("customer_name", "").strip()
    customer_phone = request.form.get("customer_phone", "").strip()
    rating = request.form.get("rating", "").strip()
    comment = request.form.get("comment", "").strip()

    if not customer_name or not customer_phone or not rating:
        return jsonify(success=False, message="Vui lòng nhập đầy đủ họ tên, SĐT và chọn số sao!"), 400

    if not rating.isdigit() or not (1 <= int(rating) <= 5):
        return jsonify(success=False, message="Số sao không hợp lệ!"), 400

    room = database.get_room_by_id(room_id)
    if not room:
        return jsonify(success=False, message="Phòng trọ không tồn tại!"), 404

    success, msg = database.add_review(room_id, customer_name, customer_phone, rating, comment)
    if success:
        return jsonify(success=True, message=msg)
    else:
        return jsonify(success=False, message=msg), 500


@app.route("/phong/<int:room_id>/danh-gia", methods=["GET"])
def xem_danh_gia(room_id):
    """Trả về JSON danh sách đánh giá công khai của 1 phòng - dùng cho modal xem đánh giá."""
    from flask import jsonify
    reviews = database.get_reviews_for_room(room_id)
    # Chuyển datetime thành string để jsonify được
    for r in reviews:
        r["created_at"] = str(r["created_at"])
    return jsonify(reviews=reviews)


@app.route("/admin/reviews")
def admin_reviews():
    """Admin xem và duyệt (xóa) đánh giá - phòng khi có review spam/không đúng sự thật."""
    if session.get('role') != 'admin':
        flash("Bạn không có quyền truy cập trang này!", "danger")
        return redirect(url_for("login"))
    reviews = database.get_all_reviews_admin()
    return render_template("admin_reviews.html", reviews=reviews)


@app.route("/admin/reviews/delete/<int:review_id>", methods=["POST"])
def admin_delete_review(review_id):
    if session.get('role') != 'admin':
        return redirect(url_for("login"))
    database.delete_review(review_id)
    flash("Đã xóa đánh giá.", "success")
    return redirect(url_for("admin_reviews"))


# ---------------------------------------------------------------------------
# BÁO "ĐÃ HẾT TRỌ" / "VẪN CÒN" - sinh viên báo cho nhau, KHÔNG cần đăng nhập
# ---------------------------------------------------------------------------
_report_hits = {}                 # ip -> [thời điểm các lần báo gần đây] (chống spam đơn giản)
_REPORT_LIMIT, _REPORT_WINDOW_SEC = 15, 3600


def _reporter_key():
    """Mỗi trình duyệt 1 mã ẩn danh (lưu trong session) -> mỗi người chỉ có 1 phiếu cho mỗi phòng."""
    token = session.get("rk")
    if not token:
        token = secrets.token_hex(16)
        session["rk"] = token
    return hashlib.sha256(token.encode()).hexdigest()


def _report_rate_limited(ip):
    now = time.time()
    hits = [t for t in _report_hits.get(ip, []) if now - t < _REPORT_WINDOW_SEC]
    if len(hits) >= _REPORT_LIMIT:
        _report_hits[ip] = hits
        return True
    hits.append(now)
    _report_hits[ip] = hits
    return False


def _clean_phone_input(raw):
    """Chuẩn hóa SĐT người dùng nhập: '0336 213 987' / '+84336213987' -> '0336213987'. Sai định dạng -> ''."""
    d = "".join(ch for ch in str(raw or "") if ch.isdigit())
    if d.startswith("84") and len(d) == 11:
        d = "0" + d[2:]
    return d if (len(d) == 10 and d.startswith("0")) else ""


def _first_field(*names, default=""):
    for n in names:
        v = request.form.get(n)
        if v is not None:
            return v.strip()
    return default


def _process_report(room_id, kind, name="", phone="", note=""):
    """Xử lý chung cho mọi form báo hết/còn. Trả về (dict JSON, mã HTTP)."""
    room = database.get_room_by_id(room_id)
    if not room:
        return {"success": False, "message": "Phòng trọ không tồn tại!"}, 404
    if _report_rate_limited(request.remote_addr or "?"):
        return {"success": False, "message": "Bạn gửi quá nhiều báo cáo, vui lòng thử lại sau."}, 429

    session_key = _reporter_key()
    verified, key = False, session_key
    if phone:
        key = hashlib.sha256(("tel:" + phone).encode()).hexdigest()      # 1 SĐT = 1 phiếu cho mỗi phòng
        verified = kind == "het" and database.phone_has_inquiry(room_id, phone)
    full_note = (f"{name}: " if name else "") + note

    if not database.add_room_report(room_id, key, kind, full_note, phone or None, verified, drop_key=session_key):
        return {"success": False, "message": "Có lỗi xảy ra, vui lòng thử lại!"}, 500

    room = database.get_room_by_id(room_id) or room
    st = room.get("trang_thai", "con")
    if kind == "con":
        msg = "Cảm ơn bạn! Đã ghi nhận phòng này VẪN CÒN TRỐNG."
    elif st == "het":
        msg = ("Đã xác minh: số điện thoại của bạn từng để lại hỏi phòng này. " if verified else "") + \
              "Phòng đã được đánh dấu ĐÃ HẾT TRỌ, các bạn sau sẽ không mất công liên hệ nữa. Cảm ơn bạn!"
    else:
        msg = "Cảm ơn bạn! Đã ghi nhận báo cáo. Cần thêm người xác nhận (hoặc quản trị viên) thì phòng mới bị ẩn."
    if room.get("trang_thai_admin") is not None:
        msg += " (Quản trị viên đã xác nhận trạng thái phòng nên báo cáo của bạn chỉ để tham khảo.)"
    return {"success": True, "message": msg, "trang_thai": st, "verified": verified,
            "het_count": room.get("het_count", 0), "con_count": room.get("con_count", 0)}, 200


@app.route("/bao-het-tro/<int:room_id>", methods=["POST"])
def bao_het_tro(room_id):
    """Báo nhanh từ bản đồ (không cần SĐT)."""
    from flask import jsonify
    kind = request.form.get("kind", "het")
    if kind not in ("het", "con"):
        return jsonify(success=False, message="Yêu cầu không hợp lệ!"), 400
    data, code = _process_report(room_id, kind, note=request.form.get("note", "").strip()[:200])
    return jsonify(data), code


@app.route("/bao-het-phong/<int:room_id>", methods=["POST"])
def bao_het_phong(room_id):
    """Form 'Báo đã hết trọ' ở trang kết quả: họ tên (tùy chọn), SĐT (bắt buộc), ghi chú, ô tick xác nhận.
    Nếu SĐT trùng số đã để lại bằng nút 'Để lại SĐT hỏi phòng' -> báo cáo được xác minh, phòng bị đánh dấu hết ngay."""
    from flask import jsonify
    name = _first_field("customer_name", "name", "ho_ten", "fullname")[:100]
    raw_phone = _first_field("customer_phone", "phone", "sdt", "so_dien_thoai", "reporter_phone")
    note = _first_field("note", "ghi_chu", "comment", "reason")[:200]

    # Ô tick "Tôi đã liên hệ chủ trọ và được báo phòng này đã hết" (tên trường tùy form; chỉ kiểm tra khi có gửi lên)
    confirm_names = ("confirm", "confirmed", "xac_nhan", "da_lien_he", "agree", "checked", "contacted")
    sent = [n for n in confirm_names if n in request.form]
    if sent and not any(request.form.get(n, "").lower() in ("on", "1", "true", "yes") for n in sent):
        return jsonify(success=False, message="Vui lòng tick xác nhận bạn đã liên hệ chủ trọ."), 400

    if not raw_phone:
        return jsonify(success=False, message="Vui lòng nhập số điện thoại của bạn."), 400
    phone = _clean_phone_input(raw_phone)
    if not phone:
        return jsonify(success=False, message="Số điện thoại không hợp lệ (cần 10 chữ số, bắt đầu bằng 0)."), 400

    data, code = _process_report(room_id, "het", name, phone, note)
    return jsonify(data), code


@app.route("/admin/availability", methods=["GET"])
def admin_availability():
    """Admin xem các phòng bị báo hết trọ, xác nhận HẾT / CÒN TRỐNG hoặc để hệ thống tự quyết."""
    if session.get('role') != 'admin':
        flash("Bạn không có quyền truy cập trang này!", "danger")
        return redirect(url_for("login"))
    show = request.args.get("show", "reported")           # reported = chỉ phòng có báo cáo/đã xác nhận; all = tất cả
    rooms = database.get_all_rooms()
    if show != "all":
        rooms = [r for r in rooms if r.get("het_count") or r.get("con_count") or r.get("trang_thai_admin") is not None]
    rooms.sort(key=lambda r: ({"het": 0, "nghi_het": 1, "con": 2}.get(r.get("trang_thai"), 2), -(r.get("het_count") or 0)))
    return render_template("admin_availability.html", rooms=rooms, show=show,
                           reports=database.get_recent_reports(60),
                           threshold=database.HET_TRO_THRESHOLD, window=database.REPORT_WINDOW_DAYS)


@app.route("/admin/availability/<int:room_id>", methods=["POST"])
def admin_set_availability(room_id):
    if session.get('role') != 'admin':
        return redirect(url_for("login"))
    status = request.form.get("status", "auto")
    if status not in ("het", "con", "auto"):
        status = "auto"
    if database.set_room_status_admin(room_id, status):
        flash({"het": "Đã đánh dấu phòng ĐÃ HẾT TRỌ.",
               "con": "Đã đánh dấu phòng CÒN TRỐNG (đã xóa các báo cáo cũ).",
               "auto": "Đã chuyển sang chế độ tự động theo báo cáo của sinh viên."}[status], "success")
    else:
        flash("Có lỗi xảy ra khi cập nhật trạng thái phòng!", "danger")
    return redirect(request.referrer or url_for("admin_availability"))


@app.route("/api/gia-re-khu-vuc", methods=["GET"])
def api_gia_re_khu_vuc():
    """JSON cho panel "Giá rẻ theo khu vực" trên bản đồ nhiệt.
    Tham số: size=S|M|L, tier=basic|comfort|premium, limit, max_price (VNĐ)."""
    from flask import jsonify
    size = request.args.get("size", "").upper()
    tier = request.args.get("tier", "").lower()
    size = size if size in price_analysis.SIZE_LABELS else ""
    tier = tier if tier in price_analysis.TIER_LABELS else ""
    limit = request.args.get("limit", "30")
    limit = min(int(limit), 100) if limit.isdigit() else 30
    max_price = request.args.get("max_price", "")
    max_price = int(max_price) if max_price.isdigit() else None
    return jsonify(price_analysis.build_report(database.get_all_rooms(), size, tier, limit, max_price))


UNIVERSITIES = [
    {"name": "ĐH Bách Khoa - ĐH Đà Nẵng", "lat": 16.0725, "lng": 108.1500},
    {"name": "ĐH Sư Phạm - ĐH Đà Nẵng", "lat": 16.0682, "lng": 108.1522},
    {"name": "ĐH Kinh Tế - ĐH Đà Nẵng", "lat": 16.0336, "lng": 108.2406},
    {"name": "ĐH Ngoại Ngữ - ĐH Đà Nẵng", "lat": 16.0279, "lng": 108.2086},
    {"name": "ĐH Duy Tân (cơ sở Nguyễn Văn Linh)", "lat": 16.0619, "lng": 108.2171},
    {"name": "ĐH Đông Á", "lat": 16.0553, "lng": 108.2205},
]
 
 
@app.route("/ban-do-nhiet", methods=["GET"])
def ban_do_nhiet():
    """Bản đồ nhiệt mật độ phòng trọ + tính khoảng cách tới trường - không cần đăng nhập."""
    rooms = database.get_rooms_with_coords()
    return render_template("ban_do_nhiet.html", rooms=rooms, universities=UNIVERSITIES)

import socket

def _lan_ip():
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "127.0.0.1"


if __name__ == "__main__":
    port = 5000
    # Đặt PUBLIC_MODE=1 khi chạy qua Cloudflare Tunnel (chỉ nghe localhost)
    public = os.environ.get("PUBLIC_MODE") == "1"
    host = "127.0.0.1" if public else "0.0.0.0"
    print(f"\n  Máy tính:   http://127.0.0.1:{port}")
    if not public:
        print(f"  Điện thoại (cùng Wi-Fi): http://{_lan_ip()}:{port}\n")
    app.run(host=host, port=port, debug=os.environ.get("FLASK_DEBUG") == "1")