"""
price_analysis.py
-----------------
Phân tích giá thuê theo khu vực bằng PHƯƠNG PHÁP SO SÁNH THỊ TRƯỜNG (market comparison
approach - cách thẩm định giá bất động sản vẫn dùng), có kiểm soát đặc tính phân khúc phòng.

Ý tưởng:
 1. "Khảo sát" = các tin đăng đã cào được. Làm sạch: bỏ giá/diện tích bất thường, bỏ ngoại
    lai (quy tắc IQR trên giá/m2) khi đủ mẫu.
 2. Mỗi phòng được xếp vào PHÂN KHÚC = cỡ phòng (Nhỏ <=20m2 / Vừa 20-30m2 / Rộng >30m2)
    x mức tiện nghi (Cơ bản / Tiện nghi / Cao cấp, chấm điểm từ danh sách tiện ích).
 3. CHỈ SỐ GIÁ KHU VỰC (đã loại ảnh hưởng cơ cấu phân khúc): với mỗi phòng tính
        tỷ lệ = giá phòng / giá trung vị toàn thành phố của CÙNG phân khúc
    rồi lấy trung vị tỷ lệ theo quận x 100. 100 = ngang mặt bằng thành phố; 85 = rẻ hơn 15%.
    -> Khu nhiều phòng cao cấp không bị coi là "đắt" chỉ vì cơ cấu phòng.
 4. PHÒNG RẺ: so giá phòng với trung vị các phòng so sánh được (cùng quận + cùng phân
    khúc, tối thiểu 3 phòng). Thiếu mẫu thì hạ bậc: cùng quận + cùng cỡ phòng, rồi
    mặt bằng thành phố x chỉ số khu vực. Có ghi rõ "cơ sở so sánh" cho từng phòng.

Hạn chế (nên nêu trong báo cáo): đây là GIÁ CHÀO trên tin đăng, không phải giá giao dịch;
mẫu nhỏ ở một số quận nên có nhãn độ tin cậy; tiện ích suy ra từ chữ trong tin.
"""
import statistics

MIN_PRICE, MAX_PRICE = 500_000, 15_000_000      # VNĐ/tháng hợp lý (loại nhập sai như "100")
MIN_AREA, MAX_AREA = 8, 100                     # m2
MIN_COMPARABLES = 3                             # tối thiểu phòng so sánh cùng khu + cùng phân khúc
MIN_CELL_FOR_REF = 5                            # tối thiểu mẫu để dùng làm giá tham chiếu thành phố
MIN_DISTRICT_N = 3                              # dưới mức này: không xếp hạng khu
CHEAP_THRESHOLD = 0.10                          # rẻ hơn >= 10% so với mặt bằng so sánh

SIZE_LABELS = {"S": "Nhỏ (≤20m²)", "M": "Vừa (20-30m²)", "L": "Rộng (>30m²)"}
TIER_LABELS = {"basic": "Cơ bản", "comfort": "Tiện nghi", "premium": "Cao cấp"}

# Nhóm tiện ích -> mỗi nhóm khớp được 1 điểm
AMENITY_GROUPS = [
    ["máy lạnh", "điều hòa", "điều hoà"],
    ["nóng lạnh", "khép kín"],
    ["gác lửng", "gác"],
    ["nội thất", "tủ lạnh"],
    ["máy giặt"],
    ["thang máy", "ban công"],
]


def _median(v):
    return statistics.median(v) if v else 0


def size_band(area):
    return "S" if area <= 20 else ("M" if area <= 30 else "L")


def amenity_tier(tien_ich):
    text = (tien_ich or "").lower()
    points = sum(any(k in text for k in group) for group in AMENITY_GROUPS)
    return "basic" if points <= 1 else ("comfort" if points <= 3 else "premium")


def clean_rooms(rooms):
    """Chuẩn hóa + loại dữ liệu bất thường. Trả (danh sách hợp lệ, số bị loại)."""
    out = []
    for r in rooms:
        try:
            price = float(r.get("gia_thue_vnd") or 0)
            if not price:
                g = float(r.get("gia_thue") or 0)
                price = g * 1000 if g < 100000 else g
            area = float(r.get("dien_tich") or 0)
        except (TypeError, ValueError):
            continue
        quan = (r.get("quan") or "").strip()
        if not quan or quan == "Chưa xác định":
            continue
        if not (MIN_PRICE <= price <= MAX_PRICE) or not (MIN_AREA <= area <= MAX_AREA):
            continue
        out.append({
            "id": r.get("id"), "title": r.get("title") or "", "quan": quan, "price": price,
            "area": area, "ppm2": price / area, "size": size_band(area),
            "tier": amenity_tier(r.get("tien_ich")), "url": r.get("url"),
            "het_tro": bool(r.get("het_tro")), "trang_thai": r.get("trang_thai", "con"),
            "lat": r.get("vi_do"), "lng": r.get("kinh_do"),
        })

    removed = 0
    if len(out) >= 20:  # chỉ lọc ngoại lai khi đủ mẫu
        q = statistics.quantiles([x["ppm2"] for x in out], n=4)
        iqr = q[2] - q[0]
        lo, hi = q[0] - 1.5 * iqr, q[2] + 1.5 * iqr
        kept = [x for x in out if lo <= x["ppm2"] <= hi]
        removed = len(out) - len(kept)
        out = kept
    return out, removed


def _build_reference(rooms):
    cells, sizes = {}, {}
    for r in rooms:
        cells.setdefault((r["size"], r["tier"]), []).append(r["price"])
        sizes.setdefault(r["size"], []).append(r["price"])
    overall = _median([r["price"] for r in rooms])

    def ref(size, tier):
        c = cells.get((size, tier), [])
        if len(c) >= MIN_CELL_FOR_REF:
            return _median(c)
        s = sizes.get(size, [])
        return _median(s) if len(s) >= MIN_CELL_FOR_REF else overall
    return ref


def _confidence(n):
    return "cao" if n >= 10 else ("trung bình" if n >= 5 else "thấp")


def _center(rooms):
    pts = []
    for r in rooms:
        try:
            la, ln = float(r["lat"]), float(r["lng"])
        except (TypeError, ValueError):
            continue
        if 15.8 <= la <= 16.35 and 107.7 <= ln <= 108.45:
            pts.append((la, ln))
    if not pts:
        return None
    return [round(sum(p[0] for p in pts) / len(pts), 6), round(sum(p[1] for p in pts) / len(pts), 6)]


def district_stats(rooms, ref, subset):
    """Chỉ số giá từng quận trên tập `subset` (đã lọc phân khúc), tham chiếu theo toàn thị trường."""
    by = {}
    for r in subset:
        by.setdefault(r["quan"], []).append(r)
    stats = []
    for quan, rs in by.items():
        n = len(rs)
        index = _median([r["price"] / ref(r["size"], r["tier"]) for r in rs]) * 100
        stats.append({
            "quan": quan, "n": n,
            "median_price": int(_median([r["price"] for r in rs])),
            "median_ppm2": int(_median([r["ppm2"] for r in rs])),
            "index": round(index, 1), "vs_city_pct": round(index - 100, 1),
            "confidence": _confidence(n), "du_du_lieu": n >= MIN_DISTRICT_N,
            "center": _center(rs),
        })
    ranked = sorted([s for s in stats if s["du_du_lieu"]], key=lambda s: s["index"])
    cheapest = ranked[0]["index"] if ranked else None
    for i, s in enumerate(ranked, 1):
        s["rank"] = i
        s["pricier_than_cheapest_pct"] = round((s["index"] / cheapest - 1) * 100, 1)
    for s in stats:
        s.setdefault("rank", None)
        s.setdefault("pricier_than_cheapest_pct", None)
    return sorted(stats, key=lambda s: (s["rank"] is None, s["rank"] or 0, -s["n"]))


def cheap_rooms(all_rooms, ref, dist_index, subset, limit=30, max_price=None):
    out = []
    for r in subset:
        if r.get("het_tro"):          # phòng đã báo hết trọ: không gợi ý
            continue
        if max_price and r["price"] > max_price:
            continue
        same_district = [x for x in all_rooms if x["quan"] == r["quan"] and x["id"] != r["id"]]
        comp = [x["price"] for x in same_district if x["size"] == r["size"] and x["tier"] == r["tier"]]
        if len(comp) >= MIN_COMPARABLES:
            bench, basis = _median(comp), f"cùng khu & cùng phân khúc (n={len(comp)})"
        else:
            comp2 = [x["price"] for x in same_district if x["size"] == r["size"]]
            if len(comp2) >= MIN_COMPARABLES + 1:
                bench, basis = _median(comp2), f"cùng khu & cùng cỡ phòng (n={len(comp2)})"
            else:
                idx = dist_index.get(r["quan"], 100) / 100
                bench, basis = ref(r["size"], r["tier"]) * idx, "ước tính: mặt bằng thành phố × chỉ số khu"
        discount = 1 - r["price"] / bench
        if discount < CHEAP_THRESHOLD:
            continue
        city_bench = ref(r["size"], r["tier"])           # mặt bằng THÀNH PHỐ cùng phân khúc
        vs_city = 1 - r["price"] / city_bench
        try:
            lat, lng = float(r["lat"]), float(r["lng"])
        except (TypeError, ValueError):
            lat = lng = None
        out.append({
            "id": r["id"], "title": r["title"], "quan": r["quan"], "price": int(r["price"]),
            "area": r["area"], "segment": f"{SIZE_LABELS[r['size']]} · {TIER_LABELS[r['tier']]}",
            "benchmark": int(bench), "discount_pct": round(discount * 100),
            "vs_city_pct": round(vs_city * 100), "basis": basis,
            "_rank": 0.6 * discount + 0.4 * vs_city, "lat": lat, "lng": lng, "url": r["url"], "trang_thai": r.get("trang_thai", "con"),
            "weight": round(min(discount / 0.4, 1.0), 2),
        })
    # Xếp hạng: 60% rẻ so với khu mình + 40% rẻ so với cả thành phố (cùng phân khúc),
    # tránh gợi ý phòng "rẻ so với khu đắt" nhưng thực ra vẫn đắt tuyệt đối.
    out.sort(key=lambda x: (-x["_rank"], x["price"]))
    for x in out:
        x.pop("_rank")
    return out[:limit]


def build_report(raw_rooms, size="", tier="", limit=30, max_price=None):
    rooms, removed = clean_rooms(raw_rooms)
    if not rooms:
        return {"ok": False, "message": "Chưa đủ dữ liệu hợp lệ.", "districts": [], "rooms": []}
    ref = _build_reference(rooms)

    # chỉ số khu vực tổng (mọi phân khúc) dùng để ước tính khi thiếu phòng so sánh
    overall_stats = district_stats(rooms, ref, rooms)
    dist_index = {s["quan"]: s["index"] for s in overall_stats if s["du_du_lieu"]}

    subset = [r for r in rooms if (not size or r["size"] == size) and (not tier or r["tier"] == tier)]
    districts = district_stats(rooms, ref, subset)
    return {
        "ok": True,
        "filter": {"size": size, "tier": tier},
        "city": {"n": len(rooms), "median_price": int(_median([r["price"] for r in rooms])),
                 "median_ppm2": int(_median([r["ppm2"] for r in rooms])),
                 "n_subset": len(subset), "outliers_removed": removed},
        "districts": districts,
        "rooms": cheap_rooms(rooms, ref, dist_index, subset, limit, max_price),
        "size_labels": SIZE_LABELS, "tier_labels": TIER_LABELS,
        "method": ("So sánh thị trường: chỉ số khu = trung vị (giá phòng ÷ giá trung vị thành phố cùng phân khúc) × 100. "
                   "Phòng rẻ = rẻ hơn ≥10% so với trung vị phòng cùng khu & cùng phân khúc, xếp hạng 60% theo mức rẻ so với khu và 40% so với cả thành phố. "
                   "Dựa trên giá chào trong tin đăng, không phải giá giao dịch."),
    }