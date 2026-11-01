import jwt
import time
import pytest
from app.office_security import verify_editor_token,validate_editor_download


def test_callback_token_requires_correct_signature_and_matching_payload():
    payload={'key':'office-test','status':2,'url':'http://127.0.0.1:18080/cache/files/edited.docx'}
    token=jwt.encode({'payload':payload},'local-test-secret',algorithm='HS256')
    assert verify_editor_token('Bearer '+token,'local-test-secret',payload)==payload
    with pytest.raises(ValueError):verify_editor_token('Bearer '+token,'another-secret',payload)
    with pytest.raises(ValueError):verify_editor_token('Bearer '+token,'local-test-secret',{**payload,'status':6})
    with pytest.raises(ValueError):verify_editor_token(token,'local-test-secret',payload)
    with pytest.raises(ValueError):verify_editor_token('Bearer '+token,'',payload)


def test_local_editor_clock_skew_is_bounded():
    payload={'url':'http://127.0.0.1:28081/file'};now=int(time.time())
    def signed(iat,exp):return 'Bearer '+jwt.encode({'payload':payload,'iat':iat,'exp':exp},'local-test-secret',algorithm='HS256')
    assert verify_editor_token(signed(now+3,now+60),'local-test-secret',payload)==payload
    with pytest.raises(ValueError):verify_editor_token(signed(now+30,now+60),'local-test-secret',payload)
    with pytest.raises(ValueError):verify_editor_token(signed(now-60,now-20),'local-test-secret',payload)


@pytest.mark.parametrize('url',[
    'http://example.com/cache/files/a.docx',
    'http://127.0.0.1:18080@evil.example/cache/files/a.docx',
    'http://127.0.0.1:18081/cache/files/a.docx',
    'http://127.0.0.1:18080/cache/files/%2e%2e/private',
    'http://127.0.0.1:18080/cache/files/%252e%252e/private',
    'http://127.0.0.1:18080/api/admin',
    'file:///cache/files/a.docx',
    'http://127.0.0.1:18080/cache/files/a.docx#fragment',
])
def test_download_url_rejects_non_editor_targets(url):
    with pytest.raises(ValueError):validate_editor_download(url,'http://127.0.0.1:18080')


def test_download_url_accepts_local_editor_cache_and_rejects_remote_origin():
    url='http://127.0.0.1:18080/cache/files/result.docx?expires=123'
    assert validate_editor_download(url,'http://127.0.0.1:18080')==url
    with pytest.raises(ValueError):validate_editor_download('http://example.com/cache/files/a.docx','http://example.com')
