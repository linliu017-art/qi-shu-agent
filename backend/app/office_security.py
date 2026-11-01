"""Helpers for a future local Office editor integration; no network endpoints.

The editor is deliberately not exposed until session persistence, save handling,
and real-file tests are complete. These checks are independent of UI state.
"""
from urllib.parse import unquote, urlsplit
import jwt


def verify_editor_token(header: str, secret: str, expected: dict) -> dict:
    if not secret or not header.startswith('Bearer '):
        raise ValueError('编辑服务认证失败')
    try:
        # The local editor and application may run in separate VMs whose clocks
        # differ slightly. Keep the tolerance bounded while still checking expiry.
        claims=jwt.decode(header[7:],secret,algorithms=['HS256'],options={'verify_aud':False},leeway=5)
    except jwt.InvalidTokenError:
        raise ValueError('编辑服务认证失败') from None
    payload=claims.get('payload')
    if not isinstance(payload,dict) or any(payload.get(key)!=value for key,value in expected.items()):
        raise ValueError('编辑服务请求与签名不一致')
    return payload


def validate_editor_download(url: str, configured_origin: str) -> str:
    """Allow only the configured local editor's own cache paths, never redirects."""
    try:
        requested=urlsplit(url);configured=urlsplit(configured_origin)
        requested_port=requested.port or (80 if requested.scheme=='http' else 443)
        configured_port=configured.port or (80 if configured.scheme=='http' else 443)
        path=unquote(unquote(requested.path))
    except ValueError:
        raise ValueError('编辑结果地址无效') from None
    if (configured.scheme not in ('http','https') or configured.hostname not in ('127.0.0.1','localhost','::1')
        or requested.scheme!=configured.scheme or requested.hostname!=configured.hostname or requested_port!=configured_port
        or requested.username is not None or requested.password is not None or requested.fragment
        or not path.startswith('/cache/files/') or '\\' in path or any(part in ('.','..') for part in path.split('/'))):
        raise ValueError('编辑结果地址不属于本地编辑服务')
    return url
