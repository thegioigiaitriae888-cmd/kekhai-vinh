"""Independent civic intake support portal. No government impersonation."""
from __future__ import annotations
import os
import json
import secrets
import time
from collections import defaultdict, deque
from pathlib import Path
from threading import Lock
from typing import Any
from fastapi import FastAPI, Request, Form, HTTPException, UploadFile, File
from fastapi.responses import HTMLResponse, RedirectResponse, Response, FileResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware
from .core import Store, STATUSES, SERVICES, BUSINESS_TYPES, INTAKE_UNITS, SUPPORT_UNITS, PROCEDURES, validate_submission
from .linked_media import LinkedMedia, MediaValidationError

BASE = Path(__file__).resolve().parent
TEMPLATES = Jinja2Templates(directory=str(BASE / 'templates'))

class Limits:
    def __init__(self):
        self.entries = defaultdict(deque)
        self.lock = Lock()

    def allowed(self, key: str, maximum: int, seconds: int) -> bool:
        ts = time.monotonic()
        with self.lock:
            queue = self.entries[key]
            while queue and ts - queue[0] >= seconds:
                queue.popleft()
            if len(queue) >= maximum:
                return False
            queue.append(ts)
            if len(self.entries) > 10_000:
                for k, v in list(self.entries.items()):
                    if not v or ts - v[-1] > seconds:
                        self.entries.pop(k, None)
            return True


def create_app(data_dir: Path | None = None) -> FastAPI:
    data_dir = Path(data_dir or os.getenv('KEKHAI_DATA_DIR', str(BASE.parent / 'runtime')))
    store = Store(data_dir)
    linked_media = LinkedMedia(data_dir)
    limits = Limits()
    # Fail closed: enabling real intake requires a reviewed, identified operator.
    mode = os.getenv('KEKHAI_INTAKE_MODE', 'preview').strip().lower()
    operator_path = Path(os.getenv('KEKHAI_OPERATOR_CONFIG', str(data_dir / 'operator-config.json')))
    operator = {}
    if operator_path.is_file():
        operator = json.loads(operator_path.read_text(encoding='utf-8'))
    intake_enabled = mode == 'live'
    if intake_enabled:
        required = ('legal_name', 'contact', 'authorization_ref', 'retention_days')
        if (os.getenv('KEKHAI_HTTPS_ONLY') != '1' or
                any(not str(operator.get(k, '')).strip() for k in required) or
                not str(operator['retention_days']).isdigit() or
                not 1 <= int(operator['retention_days']) <= 3650):
            raise RuntimeError('LIVE intake refused: HTTPS, operator identity, authorization reference and retention policy are required')
    elif mode != 'preview':
        raise RuntimeError('Unknown KEKHAI_INTAKE_MODE; use preview or live')
    app = FastAPI(title='Hỗ trợ kê khai Vinh (độc lập)', docs_url=None, redoc_url=None, openapi_url=None)
    app.add_middleware(SessionMiddleware, secret_key=store.secrets['session_secret'], same_site='lax', https_only=os.getenv('KEKHAI_HTTPS_ONLY') == '1', max_age=60*60*4)
    app.mount('/static', StaticFiles(directory=str(BASE / 'static')), name='static')
    app.state.store = store
    app.state.linked_media = linked_media
    app.state.intake_enabled = intake_enabled
    app.state.operator = operator

    @app.middleware('http')
    async def security_headers(request: Request, call_next):
        response = await call_next(request)
        response.headers['X-Content-Type-Options'] = 'nosniff'
        response.headers['Referrer-Policy'] = 'no-referrer'
        response.headers['X-Frame-Options'] = 'DENY'
        response.headers['Content-Security-Policy'] = "default-src 'self'; script-src 'self'; style-src 'self' https://fonts.googleapis.com; font-src 'self' https://fonts.gstatic.com; img-src 'self' data:; object-src 'none'; frame-ancestors 'none'; base-uri 'self'; form-action 'self'"
        response.headers['X-Robots-Tag'] = 'noindex, nofollow'
        if request.url.path.startswith(('/nop-ho-so','/tra-cuu','/quan-tri','/ket-qua','/dich-vu-cong-lien-ket')):
            response.headers['Cache-Control'] = 'no-store'
        return response

    def csrf_token(request: Request) -> str:
        if 'csrf' not in request.session:
            request.session['csrf'] = secrets.token_urlsafe(32)
        return request.session['csrf']

    def csrf_ok(request: Request, supplied: str) -> bool:
        token = request.session.get('csrf', '')
        return bool(token) and secrets.compare_digest(token, supplied)

    def view(request: Request, template: str, status_code: int = 200, **kwargs):
        return TEMPLATES.TemplateResponse(request=request, name=template, status_code=status_code, context={
            'csrf': csrf_token(request), 'statuses': STATUSES, 'services': SERVICES,
            'business_types': BUSINESS_TYPES, 'intake_units': INTAKE_UNITS,
            'support_units': SUPPORT_UNITS, 'procedures': PROCEDURES,
            'operator': operator, 'intake_enabled': intake_enabled, **kwargs,
        })

    def admin_user(request: Request) -> str | None:
        return request.session.get('admin')

    def require_admin(request: Request) -> str:
        username = admin_user(request)
        if not username:
            raise HTTPException(303, headers={'Location': '/quan-tri/dang-nhap'})
        return username

    @app.get('/', response_class=HTMLResponse)
    async def home(request: Request):
        return view(request, 'home.html', page='home')

    @app.get('/dich-vu-cong-lien-ket', response_class=HTMLResponse)
    async def linked_service(request: Request):
        return view(request, 'linked_service.html', page='linked', qr_available=linked_media.exists('qr'),
                    logo_custom=linked_media.exists('logo'), qr_version=linked_media.version('qr'), logo_version=linked_media.version('logo'))

    @app.get('/lien-ket-media/{kind}')
    async def linked_media_file(kind: str):
        if kind not in ('logo', 'qr'):
            raise HTTPException(404)
        path = linked_media.path(kind)
        if path is None:
            if kind == 'logo':
                path = BASE / 'static' / 'logo-tai-nguyen-moi-truong.png'
            else:
                raise HTTPException(404)
        response = FileResponse(path, media_type='image/png', headers={'Cache-Control':'no-store','X-Content-Type-Options':'nosniff'})
        return response

    @app.get('/chinh-sach-du-lieu', response_class=HTMLResponse)
    async def privacy(request: Request):
        return view(request, 'privacy.html', page='privacy')

    @app.get('/huong-dan', response_class=HTMLResponse)
    async def guide(request: Request):
        return view(request, 'guide.html', page='guide')

    @app.get('/nop-ho-so', response_class=HTMLResponse)
    async def new_submission(request: Request):
        return view(request, 'form.html', page='form', data={}, errors={},
                    read_only_preview=not intake_enabled)

    @app.post('/nop-ho-so', response_class=HTMLResponse)
    async def submit(request: Request):
        if not intake_enabled:
            raise HTTPException(503, detail='Hệ thống chưa được kích hoạt tiếp nhận hồ sơ thực tế.')
        form = await request.form()
        raw = {str(k): str(v) for k, v in form.items()}
        if not csrf_ok(request, raw.get('csrf', '')):
            raise HTTPException(403, detail='Phiên biểu mẫu không hợp lệ, vui lòng tải lại trang.')
        if not limits.allowed('submit:' + (request.client.host if request.client else 'unknown'), 5, 3600):
            return view(request, 'form.html', page='form', data=raw, errors={'global': 'Bạn đã gửi nhiều lần trong một giờ. Vui lòng thử lại sau.'}, status_code=429)
        data, errors = validate_submission(raw)
        if errors:
            return view(request, 'form.html', page='form', data=data, errors=errors)
        public_id, lookup_code = store.submit(data)
        request.session['csrf'] = secrets.token_urlsafe(32)
        return view(request, 'result.html', page='form', public_id=public_id, lookup_code=lookup_code)

    @app.get('/tra-cuu', response_class=HTMLResponse)
    async def lookup_page(request: Request):
        return view(request, 'lookup.html', page='lookup', record=None, error='')

    @app.post('/tra-cuu', response_class=HTMLResponse)
    async def lookup_submit(request: Request, public_id: str = Form(''), lookup_code: str = Form(''), csrf: str = Form('')):
        if not csrf_ok(request, csrf):
            raise HTTPException(403, detail='Phiên biểu mẫu không hợp lệ.')
        ip = request.client.host if request.client else 'unknown'
        if not limits.allowed('lookup:' + ip, 30, 3600):
            raise HTTPException(429, detail='Quá nhiều lượt tra cứu, vui lòng thử lại sau.')
        record = store.lookup(public_id.strip(), lookup_code.strip())
        if not record:
            return view(request, 'lookup.html', page='lookup', record=None, error='Mã hồ sơ hoặc mã tra cứu không chính xác.')
        return view(request, 'lookup.html', page='lookup', record=record, error='')

    @app.get('/quan-tri', response_class=HTMLResponse)
    async def dashboard(request: Request, status: str = ''):
        user = require_admin(request)
        return view(request, 'dashboard.html', page='admin', username=user, rows=store.list_submissions(status), current_status=status,
                    qr_available=linked_media.exists('qr'), logo_custom=linked_media.exists('logo'),
                    qr_version=linked_media.version('qr'), logo_version=linked_media.version('logo'),
                    upload_notice=request.query_params.get('media', ''))

    @app.post('/quan-tri/lien-ket-media')
    async def admin_media_upload(request: Request, kind: str = Form(''), csrf: str = Form(''), image: UploadFile = File(...)):
        require_admin(request)
        if not csrf_ok(request, csrf):
            raise HTTPException(403, detail='Phiên quản trị không hợp lệ.')
        if kind not in ('qr','logo'):
            raise HTTPException(400, detail='Loại ảnh không hợp lệ.')
        if not limits.allowed('media:' + (request.client.host if request.client else 'unknown'), 25, 3600):
            raise HTTPException(429, detail='Quá nhiều lượt tải ảnh.')
        try:
            blob = await image.read(3 * 1024 * 1024 + 1)
            linked_media.replace(kind, blob)
        except MediaValidationError as exc:
            raise HTTPException(400, detail=str(exc)) from None
        finally:
            await image.close()
        return RedirectResponse('/quan-tri?media=updated#linked-media-admin', 303)

    @app.post('/quan-tri/lien-ket-media/xoa')
    async def admin_media_delete(request: Request, kind: str = Form(''), csrf: str = Form('')):
        require_admin(request)
        if not csrf_ok(request, csrf):
            raise HTTPException(403, detail='Phiên quản trị không hợp lệ.')
        if kind not in ('qr','logo'):
            raise HTTPException(400, detail='Loại ảnh không hợp lệ.')
        linked_media.delete(kind)
        return RedirectResponse('/quan-tri?media=deleted#linked-media-admin', 303)

    @app.get('/quan-tri/dang-nhap', response_class=HTMLResponse)
    async def login_page(request: Request):
        if admin_user(request):
            return RedirectResponse('/quan-tri', 303)
        return view(request, 'login.html', page='admin', error='')

    @app.post('/quan-tri/dang-nhap', response_class=HTMLResponse)
    async def login(request: Request, username: str = Form(''), password: str = Form(''), csrf: str = Form('')):
        if not csrf_ok(request, csrf):
            raise HTTPException(403, detail='Phiên đăng nhập không hợp lệ.')
        ip = request.client.host if request.client else 'unknown'
        if not limits.allowed('login:' + ip, 8, 600):
            raise HTTPException(429, detail='Quá nhiều lần đăng nhập, vui lòng thử lại sau.')
        if not store.verify_admin(username.strip(), password):
            return view(request, 'login.html', page='admin', error='Thông tin đăng nhập không đúng.')
        request.session.clear()
        request.session['admin'] = username.strip()
        request.session['csrf'] = secrets.token_urlsafe(32)
        return RedirectResponse('/quan-tri', 303)

    @app.post('/quan-tri/dang-xuat')
    async def logout(request: Request, csrf: str = Form('')):
        require_admin(request)
        if not csrf_ok(request, csrf):
            raise HTTPException(403, detail='Phiên không hợp lệ.')
        request.session.clear()
        return RedirectResponse('/', 303)

    @app.get('/quan-tri/ho-so/{id}', response_class=HTMLResponse)
    async def detail(request: Request, id: int):
        user = require_admin(request)
        record = store.get_submission(id)
        if record is None:
            raise HTTPException(404, detail='Không tìm thấy hồ sơ.')
        return view(request, 'detail.html', page='admin', username=user, record=record)

    @app.post('/quan-tri/ho-so/{id}/cap-nhat')
    async def update(request: Request, id: int, status: str = Form(''), message: str = Form(''), csrf: str = Form('')):
        user = require_admin(request)
        if not csrf_ok(request, csrf):
            raise HTTPException(403, detail='Phiên không hợp lệ.')
        if status not in STATUSES or len(message) > 350:
            raise HTTPException(400, detail='Trạng thái hoặc nội dung không hợp lệ.')
        try:
            store.change_status(id, status, user, message.strip())
        except LookupError:
            raise HTTPException(404, detail='Không tìm thấy hồ sơ.') from None
        return RedirectResponse(f'/quan-tri/ho-so/{id}?updated=1', 303)

    @app.get('/robots.txt')
    async def robots():
        return Response('User-agent: *\nDisallow: /\n', media_type='text/plain')

    @app.get('/healthz')
    async def health():
        return {'status':'ok', 'service':'independent-intake-portal', 'intake':'live' if intake_enabled else 'preview'}

    return app

app = create_app()
