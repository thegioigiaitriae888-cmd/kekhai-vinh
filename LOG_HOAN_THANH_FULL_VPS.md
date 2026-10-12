# LOG HOÀN THÀNH — KÊ KHAI VINH Full VPS

- Dự án: KÊ KHAI VINH
- Version đóng gói: V0.4.1-LINK-R1.3 — FULL VPS
- Source nền: thư mục `KEKHAI_VINH_V0.4.1_LINK_R1_3_SOURCE` đã bàn giao
- Ngày kiểm tra/đóng gói: 2026-10-12
- Đầu ra: `KEKHAI_VINH_V0.4.1_LINK_R1_3_FULL_VPS.zip`
- Hệ điều hành đích: Linux Ubuntu (Python 3.11+ khuyến nghị)

## Phạm vi nguồn

Toàn bộ mã nguồn FastAPI, templates Jinja2, CSS/JS, assets banner/icon/logo, frontend QR, chức năng ADMIN, requirements, mẫu systemd service và script tải vendor QR. Không thay đổi logic API, database hay tính năng đã có ở LINK-R1.3. Bỏ các LOG cũ, README cũ và file không dùng để chạy.

## Kiểm thử

- ZIP `testzip`: PASS.
- FastAPI TestClient trên bản source staging với runtime mới ở thư mục tạm: PASS.
- 13 đường dẫn HTTP: PASS (gồm home, linked service, submit, lookup, guide, login, assets CSS/JS/banner/logo).
- `/quan-tri` khi chưa đăng nhập: chuyển hướng HTTP 303 — PASS.
- Có 2 mục QR và link dịch vụ công liên kết trên trang chủ — PASS.
- Kiểm tra không đóng gói `.venv`, `runtime`, `intake.sqlite3`, `.secrets.json`, `.env`, cache, backup hoặc ảnh QR do ADMIN tải lên — PASS.
- Đã tạo `MANIFEST_SHA256.txt` và checksum ZIP riêng — PASS.
- Chưa chạy trên VPS của người dùng; chưa kiểm thử camera thật/đọc QR thực tế trên trình duyệt thiết bị.

## Phụ thuộc chưa đóng gói

`jsQR 1.4.0` **chưa nằm trong ZIP**. Trước khi đưa vào vận hành, chạy `python prepare_qr_vendor.py --project "$PWD" --cache /tmp` trong release mới để tải và kiểm tra SHA-512 từ npm. Các thiết bị không có native `BarcodeDetector` cần jsQR để giải mã.

## Dữ liệu production

Không chứa dữ liệu hoặc khóa giải mã. Khi triển khai, phải giữ nguyên runtime thật (`KEKHAI_DATA_DIR`), sao lưu SQLite nhất quán cùng `.secrets.json` và ảnh upload, không thay file runtime bằng dữ liệu thử nghiệm. Nghiệm thu runtime, quyền truy cập ADMIN và HTTPS trước khi đổi release.
