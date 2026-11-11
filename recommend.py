import database

class RecommendationEngine:
    def __init__(self):
        self.reload()

    def reload(self):
        self.rooms = database.list_rooms()

    def recommend(self, budget=0, area_min=0, district="", amenities=None, keyword="", k=10):
        self.reload()
        filtered = []

        for room in self.rooms:
            # 1. Chuẩn hóa giá từ Database về đơn vị VNĐ đầy đủ
            raw_price = room['gia_thue']
            # Nếu giá lưu dạng < 100000 (ví dụ 2200, 1800, 4000) thì nhân 1000 để thành VNĐ chuẩn
            real_price = raw_price * 1000 if raw_price < 100000 else raw_price

            # Lọc theo Ngân sách tối đa
            if budget and budget > 0 and real_price > budget:
                continue

            # 2. Lọc theo Diện tích tối thiểu
            if area_min and area_min > 0 and room['dien_tich'] < area_min:
                continue

            # 3. Lọc theo Quận/Huyện
            if district and district.strip() and district.lower() not in room['quan'].lower():
                continue

            # 4. Lọc từ khóa linh hoạt (Search trong cả Tiêu đề, Mô tả, Tiện ích, Quận)
            if keyword and keyword.strip():
                kw = keyword.strip().lower()
                content_text = f"{room['title']} {room['mo_ta']} {room['tien_ich']} {room['quan']}".lower()
                if kw not in content_text:
                    continue

            filtered.append(room)

        return filtered[:k]