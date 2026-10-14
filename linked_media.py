"""Validated, isolated admin-uploaded images for the independent linked-service page."""
from __future__ import annotations
import io
import os
import secrets
from pathlib import Path
from PIL import Image, ImageOps, UnidentifiedImageError

MAX_UPLOAD = 3 * 1024 * 1024
MAX_PIXELS = 10_000_000
MAX_EDGE = 2400
KINDS = {'logo', 'qr'}

class MediaValidationError(ValueError):
    pass

class LinkedMedia:
    def __init__(self, data_dir: Path):
        self.directory = Path(data_dir) / 'linked-service-media'

    def path(self, kind: str) -> Path | None:
        if kind not in KINDS: return None
        path = self.directory / (kind + '.png')
        return path if path.is_file() else None

    def exists(self, kind: str) -> bool:
        return self.path(kind) is not None

    def version(self, kind: str) -> str:
        p = self.path(kind)
        return str(p.stat().st_mtime_ns) if p else 'default'

    def replace(self, kind: str, data: bytes) -> None:
        if kind not in KINDS:
            raise MediaValidationError('Loại ảnh không hợp lệ.')
        if not data or len(data) > MAX_UPLOAD:
            raise MediaValidationError('Ảnh cần nhỏ hơn hoặc bằng 3 MB.')
        try:
            with Image.open(io.BytesIO(data)) as im:
                if im.format not in {'PNG', 'JPEG', 'WEBP'}:
                    raise MediaValidationError('Chỉ chấp nhận PNG, JPEG hoặc WebP.')
                if im.width < 100 or im.height < 100 or im.width * im.height > MAX_PIXELS:
                    raise MediaValidationError('Ảnh phải từ 100×100 đến tối đa 10 triệu điểm ảnh.')
                im = ImageOps.exif_transpose(im)
                im.thumbnail((MAX_EDGE, MAX_EDGE), Image.Resampling.LANCZOS)
                clean = im.convert('RGBA')
                buffer = io.BytesIO()
                clean.save(buffer, format='PNG', optimize=True)
                result = buffer.getvalue()
                if len(result) > 8 * 1024 * 1024:
                    raise MediaValidationError('Ảnh sau chuẩn hóa có dung lượng quá lớn.')
        except (UnidentifiedImageError, OSError, ValueError, Image.DecompressionBombError) as exc:
            if isinstance(exc, MediaValidationError): raise
            raise MediaValidationError('Không thể đọc ảnh hoặc ảnh không hợp lệ.') from None
        self.directory.mkdir(parents=True, exist_ok=True)
        try: os.chmod(self.directory, 0o700)
        except OSError: pass
        destination = self.directory / (kind + '.png')
        temp = self.directory / ('.' + kind + '-' + secrets.token_hex(8) + '.tmp')
        try:
            with temp.open('xb') as f:
                f.write(result)
                f.flush()
                os.fsync(f.fileno())
            try: os.chmod(temp, 0o600)
            except OSError: pass
            os.replace(temp, destination)
        finally:
            temp.unlink(missing_ok=True)

    def delete(self, kind: str) -> None:
        if kind not in KINDS: raise MediaValidationError('Loại ảnh không hợp lệ.')
        p = self.path(kind)
        if p is not None: p.unlink()
