# KÊ KHAI VINH — Full Source V0.4.1-LINK-R1.3 for Ubuntu VPS

**Bản phát hành:** V0.4.1-LINK-R1.3, xây dựng từ source LINK-R1.3 đã bàn giao. Đây là **full application source** gồm FastAPI/backend, templates, CSS, JS, banner, logo, QR frontend và ADMIN. Không phải một PATCH.

## Quan trọng trước khi triển khai

- Gói KHÔNG chứa `runtime/`, database `intake.sqlite3`, `.secrets.json`, ảnh QR ADMIN đã upload, dữ liệu người dùng, `.venv`, cache, hoặc file backup Windows. **Giữ nguyên và sao lưu dữ liệu runtime đang chạy trên VPS.**
- Chức năng đọc QR dự phòng phụ thuộc thư viện **jsQR 1.4.0**. File `portal/static/vendor/jsQR.js` không có sẵn trong ZIP do môi trường đóng gói không thể tải npm. Trước khi đưa vào vận hành, hãy chạy `prepare_qr_vendor.py` theo hướng dẫn; script xác minh SHA-512 cố định từ npm chính thức. Nếu chưa chạy, một số trình duyệt sẽ không giải mã được QR.
- Không đưa website lên public trước khi cấu hình HTTPS, account ADMIN, phân quyền truy cập và sao lưu dữ liệu. Website phải giữ dấu hiệu nhận diện là nền tảng hỗ trợ độc lập, không được trình bày là website chính thức của cơ quan nhà nước khi chưa có thẩm quyền.
- Đối với VPS **đã có website hoạt động**, đừng ghi đè `current`, `runtime` hay systemd service trước khi kiểm kê và có kế hoạch rollback.

## 1. Upload từ Windows PowerShell

Lưu ZIP và tệp `.sha256` cùng thư mục `D:\WebThue` trên Windows rồi chạy (thay `USER`, `IP_VPS`, cổng SSH nếu khác 22):

```powershell
scp -P 22 "D:\WebThue\KEKHAI_VINH_V0.4.1_LINK_R1_3_FULL_VPS.zip" USER@IP_VPS:/tmp/
scp -P 22 "D:\WebThue\KEKHAI_VINH_V0.4.1_LINK_R1_3_FULL_VPS.zip.sha256" USER@IP_VPS:/tmp/
```

## 2. Kiểm tra và giải nén trên Ubuntu (thư mục phiên bản mới)

```bash
cd /tmp
sha256sum -c KEKHAI_VINH_V0.4.1_LINK_R1_3_FULL_VPS.zip.sha256
unzip -t KEKHAI_VINH_V0.4.1_LINK_R1_3_FULL_VPS.zip
sudo mkdir -p /opt/webthue/releases
sudo unzip -q KEKHAI_VINH_V0.4.1_LINK_R1_3_FULL_VPS.zip -d /opt/webthue/releases/
```

Release directory: `/opt/webthue/releases/KEKHAI_VINH_V0.4.1_LINK_R1_3`.

**Nếu hệ thống đã có thư mục cùng tên:** kiểm tra trước; lệnh `unzip` có thể hỏi ghi đè. Không tự ghi đè release đang chạy.

## 3. Cài dependencies trong release riêng

```bash
cd /opt/webthue/releases/KEKHAI_VINH_V0.4.1_LINK_R1_3
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python prepare_qr_vendor.py --project "$PWD" --cache /tmp
```

Script jsQR cần có kết nối `registry.npmjs.org` ở bước này; nếu gặp lỗi mạng hoặc integrity thì **dừng triển khai** thay vì bỏ qua.

Nếu thư mục `/opt/webthue/releases` cần `sudo` khi thao tác, hãy cấu hình quyền cho user dịch vụ/triển khai riêng thay vì chạy Uvicorn bằng root.

## 4. Runtime dữ liệu tách riêng và kiểm thử trước cutover

Ứng dụng đọc đường dẫn runtime từ `KEKHAI_DATA_DIR`. Giữ lại **cùng một thư mục runtime cũ** khi nâng cấp, bao gồm cả file khóa `.secrets.json`, file SQLite, WAL liên quan và ảnh ADMIN. Không sao chép, thay thế hoặc xóa runtime cũ.

Ví dụ chạy thử tại `127.0.0.1:8001` (không chiếm cổng 8000 của production):

```bash
cd /opt/webthue/releases/KEKHAI_VINH_V0.4.1_LINK_R1_3
export KEKHAI_DATA_DIR=/opt/webthue/shared/runtime
.venv/bin/python -m uvicorn portal.app:app --host 127.0.0.1 --port 8001
```

**CẢNH BÁO:** Trên VPS production, chỉ dùng `KEKHAI_DATA_DIR` thật khi đã xác minh quyền truy cập và backup. Khi cần chạy thử không đụng dữ liệu thật, dùng runtime thử nghiệm tạm khác đường dẫn (sẽ tạo database/keys *mới*) và không mang runtime thử vào production.

Trong phiên SSH khác:

```bash
curl -sS -o /dev/null -w 'home: %{http_code}\n' http://127.0.0.1:8001/
curl -sS -o /dev/null -w 'linked: %{http_code}\n' http://127.0.0.1:8001/dich-vu-cong-lien-ket
curl -sS -o /dev/null -w 'form: %{http_code}\n' http://127.0.0.1:8001/nop-ho-so
curl -sS -o /dev/null -w 'jsQR: %{http_code}\n' http://127.0.0.1:8001/static/vendor/jsQR.js
```

Cả bốn mã nên là `200`. Dừng server thử nghiệm bằng `Ctrl+C`.

## 5. Triển khai production, backup và rollback

- Có mẫu `webthue.service.example`. Đừng sao chép ghi đè service đang chạy mà chưa kiểm tra đường dẫn, user, secret, Nginx, TLS và port.
- Trước khi chuyển release: backup nhất quán SQLite + `.secrets.json` và nội dung `/opt/webthue/shared/runtime/linked-service-media` (file bí mật chỉ ở bản sao riêng, quyền hạn chế; không đưa vào chat).
- Tạo bản sao đường dẫn `current` hoặc ghi nhận đích symlink cũ, rồi triển khai bằng symlink release và restart service **theo maintenance plan**. Có thể cần gián đoạn ngắn trong lúc khởi động. Không thực hiện khi chưa nghiệm thu route, auth ADMIN và upload QR.
- Nếu lỗi, trỏ lại symlink `current` về release cũ và restart service; giữ nguyên thư mục runtime. Không xóa release cũ.
- HTTPS-only cookies: thiết lập `KEKHAI_HTTPS_ONLY=1` khi có HTTPS reverse proxy đúng. Không đưa app trực tiếp ra Internet qua cổng Uvicorn.
- Theo dõi `journalctl -u webthue.service -n 100 --no-pager` và trạng thái Nginx / systemd.

## 6. Cài ADMIN trên VPS mới

Với runtime mới, sau khi tạo thư mục riêng được bảo vệ, dùng:

```bash
export KEKHAI_DATA_DIR=/opt/webthue/shared/runtime
.venv/bin/python manage.py init
.venv/bin/python manage.py create-admin --username <TEN_ADMIN>
```

Không tạo admin mới vào runtime production nếu không cần. Không bao giờ đính kèm mật khẩu, `.secrets.json` hoặc cơ sở dữ liệu vào yêu cầu hỗ trợ.
