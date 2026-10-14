"""Persistence, encryption, validation and security primitives."""
from __future__ import annotations
import base64
import hashlib
import hmac
import json
import os
import re
import secrets
import sqlite3
from datetime import date, datetime, timezone
from pathlib import Path
from threading import Lock
from typing import Any
from cryptography.fernet import Fernet

STATUSES = {'received': 'Đã tiếp nhận', 'reviewing': 'Đang kiểm tra', 'needs_info': 'Cần bổ sung', 'completed': 'Đã xử lý', 'rejected': 'Không tiếp nhận'}
# Danh mục hỗ trợ do đơn vị vận hành cấu hình; không phải danh mục tiếp nhận chính thức.
SUPPORT_UNITS = [
    'Bộ phận một cửa',
    'Tổ tư vấn hỗ trợ nộp hồ sơ dịch vụ công',
    'Tổng đài hỗ trợ thủ tục hành chính công',
]
BUSINESS_TYPES = [
    'Kê khai đất đai',
    'Đất đai (cấp sổ, chuyển nhượng)',
    'Tư pháp (hộ tịch, khai sinh, kết hôn)',
    'Đăng ký doanh nghiệp/hộ kinh doanh',
]
PROCEDURES = [
    'Chuyển đổi sang sổ hồng',
    'Làm việc trực tiếp với Sở Tài nguyên và Môi trường',
    'Đăng ký biến động quyền sử dụng đất',
    'Cấp bản sao trích lục hộ tịch',
    'Đăng ký thành lập hộ kinh doanh cá thể',
]
SERVICES = [
    'Chuyển đổi sổ giấy sang sổ điện tử trên VNeID',
    'Sang tên chuyển nhượng thửa đất',
    'Kê khai đo đạc/cấp sổ',
    'Tách thửa/hợp thửa đất',
    'Sửa đổi địa chỉ thửa đất và tích hợp thông tin đất vào VNeID',
    'Dịch vụ công trực tuyến mức độ 3',
    'Dịch vụ công trực tuyến mức độ 4',
]
INTAKE_UNITS = ['Chi cục Thuế', 'Văn phòng Đăng ký đất đai', 'Sở Tài nguyên và Môi trường']

LOCK = Lock()

def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec='seconds')


def ensure_secrets(data_dir: Path) -> dict[str, str]:
    data_dir.mkdir(parents=True, exist_ok=True)
    path = data_dir / '.secrets.json'
    if path.exists():
        obj = json.loads(path.read_text(encoding='utf-8'))
        if not obj.get('session_secret') or not obj.get('data_key'):
            raise RuntimeError('Security material invalid. Restore original secrets, DO NOT regenerate.')
        Fernet(obj['data_key'].encode())
        return obj
    obj = {'session_secret': secrets.token_hex(32), 'data_key': Fernet.generate_key().decode()}
    try:
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        return ensure_secrets(data_dir)
    with os.fdopen(fd, 'w', encoding='utf-8') as file:
        json.dump(obj, file)
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass
    return obj


def hash_password(password: str, salt: str | None = None) -> tuple[str, str]:
    salt = salt or secrets.token_hex(16)
    digest = hashlib.scrypt(password.encode(), salt=bytes.fromhex(salt), n=2**14, r=8, p=1, dklen=32).hex()
    return salt, digest


def check_password(password: str, salt: str, digest: str) -> bool:
    _, actual = hash_password(password, salt)
    return hmac.compare_digest(actual, digest)


def lookup_hash(secret: str, salt: str) -> str:
    return hashlib.pbkdf2_hmac('sha256', secret.encode(), bytes.fromhex(salt), 175_000).hex()


def validate_submission(raw: dict[str, str]) -> tuple[dict[str, str], dict[str, str]]:
    fields = {
        'intake_unit': 120, 'support_unit': 120, 'business_type': 60, 'procedure': 120,
        'service': 150, 'applicant_name': 100, 'dob': 10, 'id_number': 12,
        'id_date': 10, 'id_place': 120, 'phone': 20, 'address': 255,
        'authorized': 5, 'agent_name': 100, 'agent_phone': 20,
        'land_user': 100, 'land_address': 255, 'land_phone': 20,
        'bank_name': 100, 'bank_account': 34, 'bank_holder': 100,
        'notes': 1000, 'consent': 5,
    }
    data = {key: str(raw.get(key, '')).strip() for key in fields}
    errors: dict[str, str] = {}
    for key, max_len in fields.items():
        if len(data[key]) > max_len:
            errors[key] = f'Tối đa {max_len} ký tự.'
    required = ('intake_unit', 'support_unit', 'business_type', 'procedure', 'service', 'applicant_name', 'dob', 'id_number', 'id_date', 'id_place', 'phone', 'address')
    for key in required:
        if not data[key]:
            errors[key] = 'Trường này bắt buộc.'
    if data['intake_unit'] and data['intake_unit'] not in INTAKE_UNITS:
        errors['intake_unit'] = 'Đơn vị tiếp nhận không hợp lệ.'
    if data['support_unit'] and data['support_unit'] not in SUPPORT_UNITS:
        errors['support_unit'] = 'Đơn vị hỗ trợ không hợp lệ.'
    if data['business_type'] and data['business_type'] not in BUSINESS_TYPES:
        errors['business_type'] = 'Hình thức kinh doanh không hợp lệ.'
    if data['procedure'] and data['procedure'] not in PROCEDURES:
        errors['procedure'] = 'Thủ tục hành chính không hợp lệ.'
    if data['service'] and data['service'] not in SERVICES:
        errors['service'] = 'Dịch vụ công không hợp lệ.'
    for key in ('dob', 'id_date'):
        if data[key]:
            try:
                try:
                    d = date.fromisoformat(data[key])
                except ValueError:
                    d = datetime.strptime(data[key], '%d/%m/%Y').date()
                data[key] = d.isoformat()
                if d > date.today() or d.year < 1900:
                    raise ValueError('Outside supported range')
            except ValueError:
                errors[key] = 'Ngày không hợp lệ.'
    for key in ('phone', 'agent_phone', 'land_phone'):
        if data[key] and not re.fullmatch(r'[+0-9 .()\-]{9,20}', data[key]):
            errors[key] = 'Số điện thoại không hợp lệ.'
    if data['id_number'] and not re.fullmatch(r'[0-9]{9}|[0-9]{12}', data['id_number']):
        errors['id_number'] = 'Nhập 9 hoặc 12 chữ số.'
    # Land details are required only for a land-related submission.
    land_related = (
        data['business_type'] in ('Kê khai đất đai', 'Đất đai (Cấp sổ, chuyển nhượng)')
        or data['procedure'] in ('Chuyển đổi sang sổ hồng', 'Đăng ký biến động quyền sử dụng đất')
        or data['service'] in (
            'Sang tên chuyển nhượng thửa đất', 'Kê khai đo đạc/cấp sổ',
            'Tách thửa/hợp thửa đất',
            'Sửa đổi địa chỉ thửa đất và tích hợp thông tin đất vào VNeID',
        )
    )
    if land_related:
        for key in ('land_user', 'land_address', 'land_phone'):
            if not data[key]:
                errors[key] = 'Trường này bắt buộc đối với hồ sơ đất đai.'
    if data['authorized'] == 'on':
        if not data['agent_name']:
            errors['agent_name'] = 'Nhập người được ủy quyền.'
        if not data['agent_phone']:
            errors['agent_phone'] = 'Nhập số điện thoại người được ủy quyền.'
    else:
        data['agent_name'] = data['agent_phone'] = ''
    if data['bank_account'] and not re.fullmatch(r'[0-9]{6,34}', data['bank_account']):
        errors['bank_account'] = 'Chỉ nhập số tài khoản từ 6–34 chữ số.'
    if any(data[x] for x in ('bank_name','bank_account','bank_holder')):
        for key in ('bank_name','bank_account','bank_holder'):
            if not data[key]:
                errors[key] = 'Vui lòng điền đủ cả ba trường ngân hàng hoặc để trống.'
    if data['consent'] != 'on':
        errors['consent'] = 'Cần xác nhận thông tin và đồng ý chính sách dữ liệu.'
    return data, errors


class Store:
    def __init__(self, data_dir: Path):
        self.data_dir = Path(data_dir)
        self.secrets = ensure_secrets(self.data_dir)
        self.cipher = Fernet(self.secrets['data_key'].encode())
        self.dbpath = self.data_dir / 'intake.sqlite3'
        self._init_db()
        try:
            os.chmod(self.dbpath, 0o600)
        except OSError:
            pass

    def connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.dbpath, timeout=15)
        conn.row_factory = sqlite3.Row
        conn.execute('PRAGMA foreign_keys=ON')
        conn.execute('PRAGMA busy_timeout=15000')
        return conn

    def _init_db(self):
        with self.connect() as db:
            db.execute('PRAGMA journal_mode=WAL')
            db.executescript('''
                CREATE TABLE IF NOT EXISTS submissions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    public_id TEXT UNIQUE NOT NULL,
                    lookup_salt TEXT NOT NULL,
                    lookup_digest TEXT NOT NULL,
                    encrypted_payload BLOB NOT NULL,
                    service TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'received',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_submissions_created ON submissions(created_at);
                CREATE TABLE IF NOT EXISTS admins (
                    username TEXT PRIMARY KEY,
                    salt TEXT NOT NULL,
                    password_digest TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    submission_id INTEGER NOT NULL REFERENCES submissions(id),
                    event_type TEXT NOT NULL,
                    actor TEXT NOT NULL,
                    message TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
            ''')

    def create_admin(self, username: str, password: str):
        if not re.fullmatch(r'[a-zA-Z0-9_.-]{4,40}', username):
            raise ValueError('Tên quản trị chỉ gồm chữ, số, dấu . _ - (4–40 ký tự).')
        if len(password) < 12 or len(password) > 128:
            raise ValueError('Mật khẩu quản trị phải có 12–128 ký tự.')
        salt, digest = hash_password(password)
        with self.connect() as db:
            db.execute('INSERT INTO admins VALUES (?,?,?,?)', (username, salt, digest, now()))

    def verify_admin(self, username: str, password: str) -> bool:
        with self.connect() as db:
            rec = db.execute('SELECT salt,password_digest FROM admins WHERE username=?', (username,)).fetchone()
        if rec:
            return check_password(password, rec['salt'], rec['password_digest'])
        hash_password(password)  # keep failure timing less distinguishable
        return False

    def submit(self, data: dict[str, str]) -> tuple[str, str]:
        public_id = 'VH-' + secrets.token_hex(5).upper()
        code = '-'.join((secrets.token_hex(4).upper(), secrets.token_hex(4).upper()))
        salt = secrets.token_hex(16)
        encrypted = self.cipher.encrypt(json.dumps(data, ensure_ascii=False).encode())
        timestamp = now()
        with self.connect() as db:
            cursor = db.execute('''INSERT INTO submissions (public_id,lookup_salt,lookup_digest,encrypted_payload,service,status,created_at,updated_at)
              VALUES (?,?,?,?,?,?,?,?)''', (public_id,salt,lookup_hash(code,salt),encrypted,data['service'],'received',timestamp,timestamp))
            db.execute('INSERT INTO events (submission_id,event_type,actor,message,created_at) VALUES (?,?,?,?,?)',
                (cursor.lastrowid,'submitted','public','Đã gửi hồ sơ đến nền tảng hỗ trợ độc lập.', timestamp))
        return public_id, code

    def lookup(self, public_id: str, code: str) -> dict[str, Any] | None:
        with self.connect() as db:
            row = db.execute('SELECT public_id,lookup_salt,lookup_digest,service,status,created_at,updated_at FROM submissions WHERE public_id=?', (public_id.upper(),)).fetchone()
        if not row or not hmac.compare_digest(row['lookup_digest'], lookup_hash(code.upper(), row['lookup_salt'])):
            return None
        return dict(row)

    def list_submissions(self, status: str = ''):
        with self.connect() as db:
            if status in STATUSES:
                rows = db.execute('SELECT id,public_id,service,status,created_at,updated_at FROM submissions WHERE status=? ORDER BY id DESC LIMIT 200', (status,)).fetchall()
            else:
                rows = db.execute('SELECT id,public_id,service,status,created_at,updated_at FROM submissions ORDER BY id DESC LIMIT 200').fetchall()
        return [dict(row) for row in rows]

    def get_submission(self, id: int):
        with self.connect() as db:
            row = db.execute('SELECT * FROM submissions WHERE id=?', (id,)).fetchone()
            evts = db.execute('SELECT event_type,actor,message,created_at FROM events WHERE submission_id=? ORDER BY id DESC', (id,)).fetchall()
        if not row:
            return None
        result = dict(row)
        result['payload'] = json.loads(self.cipher.decrypt(row['encrypted_payload']).decode())
        result['events'] = [dict(e) for e in evts]
        return result

    def change_status(self, id: int, status: str, actor: str, message: str):
        if status not in STATUSES:
            raise ValueError('Trạng thái không hợp lệ')
        timestamp = now()
        with self.connect() as db:
            cursor = db.execute('UPDATE submissions SET status=?,updated_at=? WHERE id=?', (status,timestamp,id))
            if cursor.rowcount != 1:
                raise LookupError('Không tìm thấy hồ sơ')
            db.execute('INSERT INTO events (submission_id,event_type,actor,message,created_at) VALUES (?,?,?,?,?)',
                (id,'status_change',actor,message[:350] or STATUSES[status],timestamp))
