"""
geocode_universities.py
--------------------------
Tra tọa độ CHÍNH XÁC của các trường đại học bằng Nominatim (dịch vụ geocoding
miễn phí của OpenStreetMap - CÙNG NGUỒN DỮ LIỆU với bản đồ nền đang dùng
trong ban_do_nhiet.html, nên tọa độ trả về sẽ khớp chính xác với vị trí thật
hiển thị trên bản đồ).
 
Chạy 1 lần trên máy bạn (cần có internet):
    pip install requests
    python geocode_universities.py
 
Kết quả in ra sẽ là danh sách UNIVERSITIES với tọa độ CHÍNH XÁC - copy đè vào
biến UNIVERSITIES trong app.py và heatmap_route.py (nếu còn giữ file riêng).
"""
 
import requests
import time
 
# Địa chỉ đầy đủ, càng chi tiết càng tra chính xác
QUERIES = [
    ("ĐH Bách Khoa - ĐH Đà Nẵng", "Trường Đại học Bách Khoa, 54 Nguyễn Lương Bằng, Đà Nẵng, Việt Nam"),
    ("ĐH Sư Phạm - ĐH Đà Nẵng", "Trường Đại học Sư Phạm, 459 Tôn Đức Thắng, Đà Nẵng, Việt Nam"),
    ("ĐH Kinh Tế - ĐH Đà Nẵng", "Trường Đại học Kinh Tế Đà Nẵng, 71 Ngũ Hành Sơn, Đà Nẵng, Việt Nam"),
    ("ĐH Ngoại Ngữ - ĐH Đà Nẵng", "Trường Đại học Ngoại Ngữ, 131 Lương Nhữ Hộc, Đà Nẵng, Việt Nam"),
    ("ĐH Duy Tân (cơ sở Nguyễn Văn Linh)", "Đại học Duy Tân, 254 Nguyễn Văn Linh, Đà Nẵng, Việt Nam"),
    ("ĐH Đông Á", "Đại học Đông Á, 33 Xô Viết Nghệ Tĩnh, Đà Nẵng, Việt Nam"),
]
 
NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"
HEADERS = {
    # Nominatim yêu cầu User-Agent thật, không dùng mặc định của thư viện
    "User-Agent": "phongtro-ai-danang-app/1.0 (do-an-tot-nghiep)"
}
 
 
def geocode(query: str):
    params = {"q": query, "format": "json", "limit": 1, "countrycodes": "vn"}
    resp = requests.get(NOMINATIM_URL, params=params, headers=HEADERS, timeout=15)
    resp.raise_for_status()
    data = resp.json()
    if not data:
        return None
    return float(data[0]["lat"]), float(data[0]["lon"]), data[0].get("display_name", "")
 
 
def main():
    print("Đang tra tọa độ chính xác từng trường qua Nominatim/OpenStreetMap...\n")
    results = []
 
    for name, query in QUERIES:
        try:
            result = geocode(query)
            if result:
                lat, lon, display_name = result
                print(f"✅ {name}")
                print(f"   -> lat={lat}, lon={lon}")
                print(f"   -> Địa chỉ khớp: {display_name}\n")
                results.append((name, lat, lon))
            else:
                print(f"⚠️  {name}: không tìm thấy kết quả, giữ tọa độ cũ hoặc tra tay.\n")
        except Exception as e:
            print(f"❌ {name}: lỗi khi tra cứu - {e}\n")
 
        time.sleep(1.2)  # Nominatim giới hạn ~1 request/giây, phải tôn trọng
 
    print("\n=== COPY ĐOẠN DƯỚI ĐÂY ĐÈ VÀO BIẾN UNIVERSITIES TRONG app.py ===\n")
    print("UNIVERSITIES = [")
    for name, lat, lon in results:
        print(f'    {{"name": "{name}", "lat": {round(lat, 6)}, "lng": {round(lon, 6)}}},')
    print("]")
 
 
if __name__ == "__main__":
    main()