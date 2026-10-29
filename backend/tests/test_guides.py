import hashlib
import pytest
from app import guides
from app.agent import GuideArgs

@pytest.mark.parametrize('key', ['prd', 'initiation', 'competitor'])
def test_snapshot_pages(key):
    guide = guides.read_guide(key)
    assert guide['source_skill'] and guide['supported_mode']
    assert guide['reference_preview']['content']
    assert len(guide['reference_preview']['content']) <= 1800
    for reference in guide['references']:
        offset, parts = 0, []
        while True:
            page = guides.read_guide(key, reference, offset, 107)
            parts.append(page['content'])
            if page['next_offset'] is None:
                break
            offset = page['next_offset']
        assert hashlib.sha256(''.join(parts).encode()).hexdigest() == page['sha256']

@pytest.mark.parametrize('reference', ['../../.env', '/etc/passwd', 'SKILL.md'])
def test_unknown_reference_rejected(reference):
    with pytest.raises(ValueError):
        guides.read_guide('prd', reference)

def test_modified_snapshot_rejected(tmp_path, monkeypatch):
    reference = guides.GUIDES['prd']['references'][0]
    path = tmp_path / guides.MANIFEST['prd']['references'][reference]['path']
    path.parent.mkdir(); path.write_text('tampered')
    monkeypatch.setattr(guides, 'ROOT', tmp_path)
    with pytest.raises(ValueError, match='完整性'):
        guides.read_guide('prd', reference)

def test_legacy_and_bounds():
    assert len(guides.GUIDES) == 7
    assert guides.read_guide('requirements')['version'] == '2'
    assert guides.read_guide('review')['version'] == '1'
    assert GuideArgs(guide_id='prd').reference is None
    with pytest.raises(ValueError):
        GuideArgs(guide_id='prd', limit=6001)
    with pytest.raises(ValueError):
        guides.read_guide('unknown')
