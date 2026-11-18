"""Project a fully captured Feishu block tree into local guide sections.

Source captures and media bytes are private local inputs, never package data.
No browser interaction or network access occurs in this projection.
"""
import re
from urllib.parse import unquote, quote, urlsplit


GUIDE_SLUGS = {'CS2Iw7iQhiajaQkslgLcI7LFnCe':'tiangong-guide',
    'YNAvwp28ei2PqXkfKpBcvhs1njd':'canvas-guide', 'LOvNw9xUoiA1JJknReucChusnfh':'canvas-agent',
    'EYtBw2bt5ikKIAkB1Z9cjiFOndh':'seedance25-storyboard', 'NioJwMujYiZctSkjul2czl6Cnjd':'dramawave-4x'}


def brand(text):
    return text.replace('天工工作台', 'vsc创作工作台')


def local_link(url):
    parsed = urlsplit(url)
    token = parsed.path.rstrip('/').rsplit('/', 1)[-1]
    slug = GUIDE_SLUGS.get(token)
    return '/guide/'+slug if slug and not parsed.fragment else url


def block_text(value):
    """Decode source attributed text once, including inline document mentions."""
    value = value or {}
    attributed = value.get('initialAttributedTexts') or {}
    texts = attributed.get('text') or {}
    attribs = attributed.get('attribs') or {}
    pool = (value.get('apool') or {}).get('numToAttrib') or {}
    result = []
    for key in sorted(texts, key=lambda k:int(k)):
        text = texts[key]
        encoded = text.encode('utf-16-le')
        offset = 0
        chunks = []
        for match in re.finditer(r'((?:\*[0-9a-z]+)*)(?:\|[0-9a-z]+)?\+([0-9a-z]+)', attribs.get(key, '')):
            length = int(match[2],36)*2
            chunk = encoded[offset:offset+length].decode('utf-16-le')
            offset += length
            attrs = dict(pool[str(int(a,36))] for a in re.findall(r'\*([0-9a-z]+)', match[1]) if str(int(a,36)) in pool)
            inline = attrs.get('inline-component')
            if inline:
                import json
                data = json.loads(inline).get('data', {})
                title = data.get('title', '')
                url = data.get('raw_url', '')
                if title:
                    chunk = '['+brand(title)+']('+local_link(url)+')' if url else brand(title)
            elif attrs.get('link'):
                chunk = '['+brand(chunk)+']('+local_link(unquote(attrs['link']))+')'
            elif attrs.get('bold') == 'true' and chunk.strip():
                chunk = '**'+brand(chunk)+'**'
            chunks.append(chunk)
        chunks.append(encoded[offset:].decode('utf-16-le'))
        result.append(''.join(chunks))
    return brand(''.join(result))


def project_capture(capture, media):
    """Fail closed for missing blocks/media; retain original order and links."""
    records = capture['records']
    if capture.get('missing') or capture['root'] not in records:
        raise ValueError('Incomplete source capture')
    sections, images, visited, unsupported = [], [], set(), set()
    current = None
    stack = []

    def append(line):
        nonlocal current
        if not line:
            return
        if current is None:
            current = dict(section_key='introduction', title='', level=0, lines=[], parent_key=None)
            sections.append(current)
        current['lines'].append(line)

    def walk(key, depth=0):
        nonlocal current
        if key in visited:
            raise ValueError('Duplicate/cyclic source block '+key)
        visited.add(key)
        if key not in records:
            raise ValueError('Missing source block '+key)
        row = records[key]; kind = row['type']
        text = block_text(row.get('text'))
        if kind.startswith('heading'):
            level = max(2, min(6, int(kind[7:])-2))
            while stack and stack[-1]['level'] >= level:
                stack.pop()
            current = dict(section_key=key, level=level, title=text.replace('**',''), lines=[],
                           parent_key=stack[-1]['section_key'] if stack else None)
            sections.append(current); stack.append(current)
        elif kind == 'image':
            image = row['image']; token = image['token']
            if token not in media:
                raise ValueError('Missing local image '+token)
            alt = block_text((image.get('caption') or {}).get('text'))
            append('!['+alt+']('+media[token]['local_url']+')')
            images.append(dict(section_key=current['section_key'], filename=token,
                               alt_text=alt, media_url=media[token]['local_url']))
        elif kind == 'file':
            file = row['file']
            if file.get('mimeType','').startswith('video/'):
                append('[video:'+file['name']+'](/creation-guide-media/'+quote(file['name'])+')')
            else:
                append(file.get('name',''))
        elif kind in ('text','bullet','ordered'):
            prefix = '- ' if kind=='bullet' else str(row.get('seq') or '1')+'. ' if kind=='ordered' else ''
            append(prefix+text if text else '')
        elif kind == 'isv' and isinstance(row.get('data',{}).get('items'), list):
            for item in row['data']['items']:
                append(brand('\n'.join(str(item.get(k,'')) for k in ('time','title','text') if item.get(k))))
        elif kind not in ('page','grid','grid_column','callout','divider','view'):
            unsupported.add(kind)
            # Preserve source references explicitly instead of inventing body.
            if kind=='synced_reference':
                append('[引用原文](https://rg975ojk5z.feishu.cn/docx/'+row['src_page_id']+'#'+row['src_block_id']+')')
            elif text:
                append(text)
        for child in row.get('children', []):
            walk(child, depth+1)
    walk(capture['root'])
    for index, section in enumerate(sections):
        section['sort_order'] = index
        section['body'] = '\n\n'.join(section.pop('lines'))
        section['callout'] = ''
    return dict(title=block_text(records[capture['root']].get('text')), sections=sections, images=images,
                source_blocks=len(visited), unsupported_types=sorted(unsupported))
