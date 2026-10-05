"""Serial, cached arXiv HTML/PDF text extraction with explicit coverage."""
import io
import json
import re
import time
from pathlib import Path
import requests
from lxml import html
from pypdf import PdfReader

_last_request = 0.0

def download(url):
    global _last_request
    time.sleep(max(0, 5 - (time.monotonic() - _last_request)))
    _last_request = time.monotonic()
    with requests.get(url, timeout=(15, 60), stream=True, headers={'User-Agent':'ResearchPaperReader/1.0 (arXiv research reading)'}) as response:
        response.raise_for_status()
        data = bytearray()
        for block in response.iter_content(65536):
            data.extend(block)
            if len(data) > 30 * 1024 * 1024:
                raise ValueError('Full text exceeds 30 MB download limit')
    return bytes(data)

def html_sections(data):
    tree=html.fromstring(data)
    articles=tree.xpath('//article[contains(concat(" ", normalize-space(@class), " "), " ltx_document ")]')
    if not articles: raise ValueError('No arXiv full-text article')
    for node in articles[0].xpath('.//script|.//style|.//nav'): node.drop_tree()
    sections=[]
    heading='正文'
    for node in articles[0].xpath('.//*[self::h1 or self::h2 or self::h3 or self::h4 or self::p or self::table]'):
        if node.xpath('ancestor::table') and node.tag != 'table': continue
        text=' '.join(node.text_content().split())
        if not text: continue
        if node.tag.startswith('h'): heading=text
        sections.append({'id':f's{len(sections)+1}', 'location':heading, 'text':text})
    if sum(len(s['text']) for s in sections)<2000: raise ValueError('Insufficient HTML body text')
    return sections, ['HTML 正文文字已提取；图像内容、公式及复杂表格未做视觉核验。']

def pdf_sections(data):
    reader=PdfReader(io.BytesIO(data))
    sections=[]; missing=[]
    for index,page in enumerate(reader.pages,1):
        text=(page.extract_text() or '').strip()
        if len(text)<40: missing.append(index)
        if text: sections.append({'id':f'p{index}','location':f'PDF 第 {index} 页','text':text})
    if sum(len(s['text']) for s in sections)<2000: raise ValueError('Insufficient PDF text; OCR may be required')
    notes=['PDF 文字层已提取；图像、公式与复杂表格未做视觉核验。']
    if missing: notes.append('文字缺失或极少的页：'+','.join(map(str,missing)))
    return sections,notes

def fetch_fulltext(paper, cache_dir):
    identifier=paper['id']
    if not re.fullmatch(r'(?:\d{4}\.\d{4,5}|[a-zA-Z.-]+/\d{7})(?:v\d+)?',identifier):
        raise ValueError('Invalid arXiv identifier')
    path=Path(cache_dir)/('text-v1-'+identifier.replace('/','_')+'.json')
    if path.exists(): return json.loads(path.read_text(encoding='utf-8'))
    errors=[]
    for mode,parser in [('html',html_sections),('pdf',pdf_sections)]:
        url=f'https://arxiv.org/{mode}/{identifier}'
        try:
            sections,notes=parser(download(url))
            result={'source':url,'format':mode,'sections':sections,'notes':notes,
                    'coverage':'partial_text' if any('文字缺失' in n for n in notes) else 'extracted_text'}
            path.parent.mkdir(parents=True,exist_ok=True)
            path.write_text(json.dumps(result,ensure_ascii=False),encoding='utf-8')
            return result
        except Exception as error:
            errors.append(mode+':'+type(error).__name__)
    raise RuntimeError('Full-text retrieval failed: '+', '.join(errors))

def chunks(sections,limit):
    """Every extracted character is assigned to a chunk, with stable source IDs."""
    result=[]; current=[]; size=0
    for section in sections:
        for start in range(0,len(section['text']),limit):
            part={**section,'text':section['text'][start:start+limit]}
            if current and size+len(part['text'])>limit:
                result.append(current);current=[];size=0
            current.append(part);size+=len(part['text'])
    if current: result.append(current)
    return result
