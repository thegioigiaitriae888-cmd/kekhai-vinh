#!/usr/bin/env python3
"""Prepare verified, self-hosted jsQR 1.4.0. No image/QR data is transferred.
Fetch once at install/deployment. Requires internet access to registry.npmjs.org.
"""
from __future__ import annotations
import base64
import hashlib
import io
from pathlib import Path
import tarfile
import urllib.request

REGISTRY = 'https://registry.npmjs.org/jsqr/-/jsqr-1.4.0.tgz'
NPM_SHA512 = 'dxLob7q65Xg2DvstYkRpkYtmKm2sPJ9oFhrhmudT1dZvNFFTlroai3AWSpLey/w5vMcLBXRgOJsbXpdN9HzU/A=='
CACHE_FILE = 'jsqr-1.4.0.tgz'
JS_PATH = 'package/dist/jsQR.js'
LICENSE_PATH = 'package/LICENSE'
MAX_TARBALL = 4_000_000

def verified_vendor(root: Path) -> tuple[bytes, bytes]:
    cache = root / CACHE_FILE
    if cache.exists():
        raw = cache.read_bytes()
    else:
        print('Fetching jsQR 1.4.0 from the official npm registry (once)…')
        req = urllib.request.Request(REGISTRY, headers={'User-Agent':'WebThue-QR-Vendor/1.0'})
        try:
            with urllib.request.urlopen(req, timeout=25) as response:
                raw = response.read(MAX_TARBALL+1)
        except Exception as exc:
            raise RuntimeError('Không tải được bộ giải mã jsQR từ npm. Kiểm tra Internet/proxy và thử lại. Source hiện tại chưa thay đổi.') from exc
    if not raw or len(raw) > MAX_TARBALL:
        raise RuntimeError('jsQR archive size is invalid')
    expected = base64.b64decode(NPM_SHA512)
    if hashlib.sha512(raw).digest() != expected:
        raise RuntimeError('jsQR archive failed pinned npm SHA-512 verification; refusing install')
    try:
        with tarfile.open(fileobj=io.BytesIO(raw), mode='r:gz') as archive:
            js = archive.extractfile(JS_PATH).read()
            license_text = archive.extractfile(LICENSE_PATH).read()
    except Exception as exc:
        raise RuntimeError('Verified jsQR tarball cannot be extracted') from exc
    if not (100_000 < len(js) < 2_000_000 and b'jsQR' in js[:3000] and b'Apache License' in license_text):
        raise RuntimeError('jsQR source or license invalid')
    if not cache.exists():
        cache.write_bytes(raw)
    return js, license_text

def install_local_vendor(project: Path, root: Path) -> dict[str, str]:
    js, license_bytes = verified_vendor(root)
    vendor = project / 'portal/static/vendor'
    vendor.mkdir(parents=True, exist_ok=True)
    outputs = {'portal/static/vendor/jsQR.js': js,
               'portal/static/vendor/LICENSE.jsQR.txt': license_bytes}
    for rel, contents in outputs.items():
        target = project / rel
        if target.exists() and target.read_bytes() != contents:
            raise RuntimeError('Existing jsQR vendor file differs; refusing overwrite: ' + rel)
    for rel, contents in outputs.items():
        target = project / rel
        if not target.exists():
            target.write_bytes(contents)
    return {rel:hashlib.sha256(contents).hexdigest() for rel, contents in outputs.items()}

if __name__ == '__main__':
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument('--project',required=True)
    ap.add_argument('--cache',default=str(Path(__file__).resolve().parent))
    args = ap.parse_args()
    outputs = install_local_vendor(Path(args.project), Path(args.cache))
    print('jsQR installed locally and verified:',outputs['portal/static/vendor/jsQR.js'])
