# Hệ thống hỗ trợ tìm phòng trọ Đà Nẵng

Đây là phiên bản chạy thật của đồ án — một trang web nhỏ có công cụ AI gợi ý
phòng trọ theo tiêu chí người dùng nhập vào.

## Cấu trúc thư mục

```
phong-tro-app/
├── app.py              Ứng dụng web Flask (điều hướng các trang)
├── database.py         Tạo và thao tác với cơ sở dữ liệu SQLite
├── recommend.py        "Bộ não" AI: chấm điểm và xếp hạng phòng trọ
├── requirements.txt    Danh sách thư viện cần cài
├── data/
│   └── seed_data.csv   30 phòng trọ mẫu để demo (Bạn thay bằng dữ liệu thật)
├── templates/
│   ├── index.html       Trang tìm kiếm
│   ├── results.html      Trang kết quả gợi ý + bản đồ
│   └── admin_add.html    Form thêm tin đăng thủ công
└── static/
    └── style.css         Giao diện
```

## Bước 1 — Cài đặt (làm một lần)

Mở Command Prompt tại thư mục này, chạy:

```
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
```

## Bước 2 — Nạp dữ liệu mẫu vào cơ sở dữ liệu

```
python database.py
```

Lệnh này tạo file `phongtro.db` và nạp 30 phòng trọ mẫu từ `data/seed_data.csv`
để bạn có dữ liệu demo ngay, không phải tự nhập tay từ đầu.

## Bước 3 — Chạy thử "bộ não" AI (tuỳ chọn, để kiểm tra)

```
python recommend.py
```

In ra 5 phòng trọ gợi ý theo một tiêu chí mẫu, dùng để kiểm tra công thức gợi
ý hoạt động đúng trước khi mở giao diện web.

## Bước 4 — Chạy trang web

```
python app.py
```

Mở trình duyệt vào `http://localhost:5000`.

## Cách thu thập dữ liệu thật (quan trọng)

Việc tự động đăng nhập vào Facebook/Zalo để "cào" bài đăng trong các nhóm
riêng tư **vi phạm điều khoản dịch vụ** của những nền tảng đó và có thể khiến
tài khoản bị khoá. Cách làm đúng và an toàn cho đồ án:

1. Vào các trang/nhóm cho thuê trọ, đọc từng tin đăng.
2. Vào `http://localhost:5000/admin/add`, chép thông tin của tin đăng đó vào
   form (giá, khu vực, diện tích, tiện ích, mô tả, nguồn).
3. Bấm "Lưu tin đăng". Phòng trọ này lập tức có thể được gợi ý ngay ở trang
   tìm kiếm.

Ghi lại tên nguồn (cột "Nguồn tin") mỗi khi nhập, để sau này còn biết dữ liệu
lấy từ đâu, phục vụ phần "nguồn dữ liệu" cần khai trong báo cáo.

Nếu muốn nhập nhanh nhiều tin cùng lúc: sửa file `data/seed_data.csv` theo
đúng các cột đã có, rồi chạy lại `python database.py` (lệnh này sẽ xoá dữ liệu
cũ và nạp lại toàn bộ CSV — chỉ dùng khi muốn làm lại từ đầu; dùng form admin
nếu muốn thêm dần mà không mất dữ liệu đã có).

## "Bộ não" AI hoạt động ra sao

Xem chi tiết trong `recommend.py`. Tóm tắt: mỗi phòng trọ được biến thành 4
nhóm vec-tơ (giá & diện tích, khu vực, tiện ích, mô tả), tiêu chí người dùng
cũng biến thành 4 vec-tơ tương ứng, sau đó tính độ tương đồng cô-sin từng
nhóm rồi cộng có trọng số lại thành một điểm duy nhất (hàm `recommend()`).
Trọng số mặc định nằm ở biến `DEFAULT_WEIGHTS` đầu file, có thể chỉnh lại nếu
muốn ưu tiên tiêu chí này hơn tiêu chí khác.

## Việc cần làm để hoàn thiện cho báo cáo

- Xoá 30 dòng dữ liệu mẫu trong `data/seed_data.csv`, thay bằng dữ liệu thật
  bạn tự thu thập (tối thiểu vài chục phòng trọ để demo có ý nghĩa).
- Chụp ảnh màn hình trang tìm kiếm và trang kết quả, chèn vào Chương 4 của
  báo cáo LaTeX thay cho ô placeholder.
- Chạy thử với vài bộ tiêu chí thật, ghi lại kết quả (Precision@5 thật) để
  thay số liệu minh hoạ trong Chương 5 của báo cáo.
- Cập nhật lại đường link kho `git` và các bước cài đặt ở Phụ lục A cho khớp
  với các bước ở README này (không dùng lệnh `train.py --epochs` như bản cũ,
  vì hệ thống này không huấn luyện theo epoch).
