"""Detect selected high-risk Office feature losses; not a proof of full fidelity."""
from collections import Counter
from hashlib import sha256
from io import BytesIO
from zipfile import ZipFile
from xml.etree import ElementTree as ET
import re


def _inventory(raw,kind):
    found={'media':Counter(),'embedded':Counter(),'charts':0,'headers':0,'footers':0,'slides':0,'timing':0,'notes':Counter(),'formulas':Counter(),'merges':0}
    with ZipFile(BytesIO(raw)) as archive:
        for name in archive.namelist():
            if re.match(r'^(word|xl|ppt)/media/[^/]+$',name):found['media'][sha256(archive.read(name)).hexdigest()]+=1
            elif re.match(r'^(word|xl|ppt)/embeddings/[^/]+$',name):found['embedded'][sha256(archive.read(name)).hexdigest()]+=1
            elif re.match(r'^(xl|ppt)/charts/chart\d+\.xml$',name):found['charts']+=1
            elif kind=='docx' and re.match(r'^word/header\d+\.xml$',name):found['headers']+=1
            elif kind=='docx' and re.match(r'^word/footer\d+\.xml$',name):found['footers']+=1
            elif kind=='pptx' and re.match(r'^ppt/slides/slide\d+\.xml$',name):
                found['slides']+=1;root=ET.fromstring(archive.read(name))
                found['timing']+=sum(1 for element in root.iter() if element.tag.endswith('}timing'))
            elif kind=='pptx' and re.match(r'^ppt/notesSlides/notesSlide\d+\.xml$',name):
                root=ET.fromstring(archive.read(name));text=''.join(e.text or '' for e in root.iter() if e.tag.endswith('}t')).strip()
                if text:found['notes'][text]+=1
            elif kind=='xlsx' and re.match(r'^xl/worksheets/sheet\d+\.xml$',name):
                root=ET.fromstring(archive.read(name))
                for element in root.iter():
                    if element.tag.endswith('}f'):found['formulas'][element.text or '']+=1
                    elif element.tag.endswith('}mergeCell'):found['merges']+=1
    return found


def potential_losses(before,after,kind):
    """Return only selected loss warnings; no claim that absent warnings mean lossless."""
    old,new=_inventory(before,kind),_inventory(after,kind);warnings=[]
    for key,label in [('media','图片或媒体'),('embedded','嵌入对象'),('notes','幻灯片备注'),('formulas','工作表公式')]:
        if old[key]-new[key]:warnings.append(f'{label}可能被删除或改变')
    for key,label in [('charts','图表'),('headers','页眉'),('footers','页脚'),('slides','幻灯片'),('timing','动画'),('merges','合并单元格')]:
        if new[key]<old[key]:warnings.append(f'{label}数量减少或无法保留')
    return warnings
