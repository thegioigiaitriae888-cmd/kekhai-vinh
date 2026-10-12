"""Operator CLI. No default admin password."""
import argparse
import getpass
import os
from pathlib import Path
from portal.core import Store

def main():
    parser = argparse.ArgumentParser(description='Quản lý nền tảng kê khai độc lập')
    sub = parser.add_subparsers(dest='cmd', required=True)
    sub.add_parser('init', help='Tạo kho dữ liệu và khóa mã hóa (chỉ chạy lần đầu)')
    create = sub.add_parser('create-admin', help='Tạo người dùng quản trị nội bộ')
    create.add_argument('--username', required=True)
    args = parser.parse_args()
    path = Path(os.getenv('KEKHAI_DATA_DIR', Path(__file__).parent / 'runtime'))
    db = Store(path)
    if args.cmd == 'init':
        print('Đã khởi tạo tại:', path.resolve())
        print('QUAN TRỌNG: Sao lưu cả intake.sqlite3 và .secrets.json, không chia sẻ khóa bí mật.')
    elif args.cmd == 'create-admin':
        pw = getpass.getpass('Mật khẩu mới (12+ ký tự): ')
        verify = getpass.getpass('Nhập lại mật khẩu: ')
        if pw != verify:
            raise SystemExit('Hai mật khẩu không trùng khớp.')
        try:
            db.create_admin(args.username, pw)
        except ValueError as ex:
            raise SystemExit(str(ex))
        except Exception as ex:
            if 'UNIQUE' in str(ex):
                raise SystemExit('Tên quản trị đã tồn tại.')
            raise
        print('Đã tạo tài khoản quản trị:', args.username)

if __name__ == '__main__':
    main()
