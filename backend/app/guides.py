"""Approved business-method snapshots; never execute local skills."""
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).parent / 'skill_references'
GUIDES = json.loads((Path(__file__).parent / 'prompts' / 'business_guides.json').read_text())
MANIFEST = json.loads((ROOT / 'manifest.json').read_text())
for key, source in MANIFEST.items():
    GUIDES[key].update(source_skill=source['source_skill'], references=list(source['references']))


def read_guide(guide_id, reference=None, offset=0, limit=3000):
    if guide_id not in GUIDES:
        raise ValueError('业务指引不存在')
    if not reference:
        guide = dict(GUIDES[guide_id])
        references = guide.get('references', [])
        if references:
            guide['reference_preview'] = read_guide(guide_id, references[0], 0, 1800)
            guide['reading_hint'] = '已附首个模板的开头，可据任务选择使用；有必要再读后续页或其他模板。已获得足够方法时直接处理用户资料，不重复读取。'
        return guide
    item = MANIFEST.get(guide_id, {}).get('references', {}).get(reference)
    if item is None:
        raise ValueError('参考资料不存在，请使用指引列出的名称')
    if offset < 0 or not 1 <= limit <= 6000:
        raise ValueError('读取范围无效')
    path = (ROOT / item['path']).resolve()
    if not path.is_relative_to(ROOT.resolve()):
        raise ValueError('参考资料路径无效')
    try:
        raw = path.read_bytes()
    except OSError:
        raise ValueError('参考资料不可用') from None
    if hashlib.sha256(raw).hexdigest() != item['sha256']:
        raise ValueError('参考资料完整性校验失败')
    content = raw.decode('utf-8')
    end = min(offset + limit, len(content))
    return {'guide_id': guide_id, 'reference': reference, 'sha256': item['sha256'],
            'supported_mode': GUIDES[guide_id]['supported_mode'],
            'offset': offset, 'total_chars': len(content), 'content': content[offset:end],
            'next_offset': end if end < len(content) else None}
