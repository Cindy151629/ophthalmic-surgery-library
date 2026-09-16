"""All-record bibliographic retrieval, with private raw evidence and resumable logs."""
from common import *
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor,as_completed
from bs4 import BeautifulSoup
from difflib import SequenceMatcher
from copy import deepcopy
from io import BytesIO

PAGE_PARSER_VERSION = 'main-title-v3'


def _title_matches(expected, actual, source):
    """Only punctuation/spacing differences and explicit browser-title suffixes."""
    wanted = norm(expected or '')
    if not wanted or not actual:
        return False
    if wanted == norm(actual):
        return True
    # A journal/site suffix is common in <title>, but an arbitrary substring (or
    # a high fuzzy score for a different edition/follow-up) is not identity.
    if source in ('title', 'og:title'):
        for suffix in (' from the SAGES Video Library', ' - A SAGES Publication'):
            if actual.rstrip().casefold().endswith(suffix.casefold()):
                return wanted == norm(actual.rstrip()[:-len(suffix)])
        parts = re.split(r'\s+[|–—-]\s+|\s*\|\s*', actual)
        # Remove a known site label from the END, never accept an arbitrary
        # suffix such as "five-year follow-up" as publisher branding.
        if len(parts) > 1 and re.fullmatch(
                r'PubMed|(?:Europe )?PMC|ScienceDirect(?:\.com)?|Wiley Online Library|'
                r'Springer(?:Link| Nature Link)?|Oxford Academic|OUP Academic|'
                r'Annals of Surgery|JAMA Network|AASLD|SAGES|IEG', parts[-1], re.I):
            return wanted == norm(' '.join(parts[:-1]))
    return False


def _excluded_heading(node):
    for ancestor in [node, *node.parents]:
        if getattr(ancestor, 'name', '') in ('nav', 'aside', 'footer'):
            return True
        attrs = getattr(ancestor, 'attrs', {}) or {}
        markers = ' '.join([str(attrs.get('id', '')),
                            ' '.join(attrs.get('class', [])),
                            str(attrs.get('role', ''))])
        if re.search(r'relat|recommend|reference|bibliograph|cited.by|citation.list|'
                     r'sidebar|navigation|search.result', markers, re.I):
            return True
        if attrs.get('hidden') is not None or attrs.get('aria-hidden') == 'true':
            return True
    return False


def _html_titles(soup, metas):
    """Select main-record titles; never pool every h2 into a candidate."""
    citations = list(dict.fromkeys(x.get('content', '').strip() for x in
                     soup.select('head meta[content]')
                     if (x.get('name') or x.get('property') or '').lower() == 'citation_title'
                     and x.get('content', '').strip()))
    headings = [x for x in soup.find_all('h1') if not _excluded_heading(x)]
    scoped = [x for x in headings if x.find_parent(['main', 'article'])]
    headings = scoped or headings
    primary = [x.get_text(' ', strip=True) for x in headings
               if x.get_text(' ', strip=True)]
    # citation_title and the visible primary title must not contradict one
    # another. Multiple different h1s usually indicate an article listing.
    if citations or primary:
        return ([('citation_title', x) for x in citations] +
                [('h1', x) for x in primary])
    if metas.get('og:title'):
        return [('og:title', metas['og:title'])]
    if soup.title and soup.title.get_text(' ', strip=True):
        return [('title', soup.title.get_text(' ', strip=True))]
    # h2 is a conservative fallback only when it is the first heading of the
    # single main/article container, not a link or a recommendation section.
    scopes = soup.find_all('main') or soup.find_all('article')
    if len(scopes) == 1:
        head = scopes[0].find(['h1', 'h2'])
        if (head is not None and head.name == 'h2' and
                not _excluded_heading(head) and not head.find('a') and
                not re.search(r'^(related|recommended|references|recommended articles|'
                              r'related articles|abstract|introduction)$',
                              head.get_text(' ', strip=True), re.I)):
            return [('h2', head.get_text(' ', strip=True))]
    return []


def _xml_main_record(root):
    """Return one primary record, its title and its own identifiers only."""
    for node in root.iter():
        if isinstance(node.tag, str):
            node.tag = node.tag.rsplit('}', 1)[-1]
    if root.tag in ('pmc-articleset', 'article-set'):
        articles = root.findall('article')
        if len(articles) != 1:
            return None, '', []
        root = articles[0]
    if root.tag == 'article':
        meta = root.find('front/article-meta')
        group = root.find('front/article-meta/title-group')
        title = txt(group.find('article-title')) if group is not None else ''
        if title:
            subtitles = [txt(node) for node in group.findall('subtitle') if txt(node)]
            if subtitles:
                title = ': '.join([title.rstrip(':： '), *subtitles])
        title = title or txt(root.find('front/article-title'))
        ids = [txt(x) for x in meta.findall('article-id')] if meta is not None else []
        return root, title, ids
    if root.tag == 'PubmedArticleSet':
        articles = root.findall('PubmedArticle')
        if len(articles) != 1:
            return None, '', []
        root = articles[0]
    if root.tag == 'PubmedArticle':
        title = txt(root.find('MedlineCitation/Article/ArticleTitle'))
        ids = [txt(x) for x in root.findall('PubmedData/ArticleIdList/ArticleId')]
        return root, title, ids
    return None, '', []


def _pdf_title(reader):
    """Read the largest-type title block in the upper part of page one."""
    page = reader.pages[0]
    bottom, top = float(page.cropbox.bottom), float(page.cropbox.top)
    height = top - bottom
    fragments = []
    if page.rotation:
        return '', {'reason': 'rotated first page requires manual title review'}

    def visit(text, cm, tm, font_dict, font_size):
        text = text.strip()
        y = tm[4] * cm[1] + tm[5] * cm[3] + cm[5]
        x = tm[4] * cm[0] + tm[5] * cm[2] + cm[4]
        size = abs(font_size) * (cm[0] ** 2 + cm[1] ** 2) ** .5
        if text and size > 0 and bottom + .55 * height <= y <= bottom + .95 * height:
            fragments.append((y, x, size, text))

    page.extract_text(visitor_text=visit)
    region = {'page': 1, 'bottom_fraction': .55, 'top_fraction': .95}
    if not fragments:
        return '', region
    largest = max(row[2] for row in fragments)
    lines = sorted((row for row in fragments if row[2] >= largest * .95),
                   key=lambda row: (-row[0], row[1]))
    block = [lines[0]]
    for row in lines[1:]:
        if block[-1][0] - row[0] > largest * 2.2:
            break
        block.append(row)
    region['font_size'] = largest
    return ' '.join(row[3] for row in block), region


def parse_page_content(content: bytes, title: str, log: dict, *,
                       extract_body: bool = True) -> tuple[dict, str]:
    """Reclassify cached response bytes without network or filesystem writes.

    Returns (fresh_log, extracted_text). Pass the original fetch log, including
    status/content_type/requested_url/final_url. Request provenance (including
    checked_at and sha256) is retained; old parsing conclusions are recomputed.
    With extract_body=False, text contains only the HTML challenge prefix or
    XML/PDF main title, and PDF text extraction touches only its first page.
    This confirms a page title only, not authors/DOI or a human reading depth.
    """
    result = deepcopy(log)
    for key in ('parse_error', 'pdf_pages', 'xml_title', 'body_present', 'body_chars',
                'ids', 'pdf_title_region'):
        result.pop(key, None)
    result.update(page_parser_version=PAGE_PARSER_VERSION, page_title='',
                  title_similarity=0, title_present=False, title_match_source='',
                  title_candidates=[], title_conflict=False, metadata={}, text_chars=0,
                  description='', video_tags=0, iframes=[], access_signals=[], content_format='',
                  text_extraction_scope='full' if extract_body else 'identity-only')
    if result.get('status') != 200:
        result['page_state'] = '受限或请求失败'
        return result, ''
    text = ''
    candidates = []
    challenge = False
    content_type = str(result.get('content_type') or '').lower()
    prefix = content.lstrip(b'\xef\xbb\xbf \r\n\t')
    is_pdf = prefix.startswith(b'%PDF') or 'pdf' in content_type
    is_xml = ('html' not in content_type and ('xml' in content_type or
              prefix.startswith(b'<?xml') or
              re.match(br'<(?:article|pmc-articleset|PubmedArticleSet)(?:\s|>)', prefix)))
    result['content_format'] = 'PDF' if is_pdf else 'XML' if is_xml else 'HTML'
    try:
        if is_pdf:
            from pypdf import PdfReader
            reader = PdfReader(BytesIO(content))
            primary, region = _pdf_title(reader)
            text = ('\n'.join(page.extract_text() or '' for page in reader.pages)
                    if extract_body else primary)
            candidates = [('pdf:first-page-title-region', primary)] if primary else []
            result.update(pdf_pages=len(reader.pages), pdf_title_region=region,
                          content_format='PDF', page_title=primary)
        elif is_xml:
            root = ET.fromstring(content)
            record, primary, ids = _xml_main_record(root)
            body = record.find('body') if record is not None else None
            text = ('\n'.join(txt(node) for node in root.iter()
                              if node.tag in ('article-title', 'title', 'p', 'caption', 'table'))
                    if extract_body else primary)
            candidates = [('xml:main-record-title', primary)] if primary else []
            result.update(content_format='XML', page_title=primary, xml_title=primary,
                          ids=ids, body_present=body is not None,
                          body_chars=len(txt(body)) if extract_body else None)
        else:
            soup = BeautifulSoup(content, 'html.parser')
            metas = {(x.get('name') or x.get('property') or '').lower(): x.get('content', '')
                     for x in soup.select('head meta[content]')}
            page_title = soup.title.get_text(' ', strip=True) if soup.title else ''
            candidates = _html_titles(soup, metas)
            for node in soup(['script', 'style', 'noscript', 'nav', 'footer', 'header']):
                node.decompose()
            if extract_body:
                text = soup.get_text('\n', strip=True)
            else:
                pieces, count = [], 0
                for piece in soup.stripped_strings:
                    pieces.append(piece[:600 - count])
                    count += len(piece) + 1
                    if count >= 600:
                        break
                text = '\n'.join(pieces)[:600]
            challenge = bool(re.search(
                r'just a moment|verify you are human|checking your browser|access denied|'
                r'enable javascript and cookies|captcha verification|robot check',
                page_title + ' ' + text[:600], re.I))
            challenge = challenge or bool(re.match(
                r'^(?:sign in|log in|login|authentication required)(?:\s*[|:–—-]|\s*$)',
                page_title.strip(), re.I))
            result.update(content_format='HTML', page_title=page_title, metadata=metas,
                          description=metas.get('description') or metas.get('og:description', ''),
                          video_tags=len(soup.find_all('video')),
                          iframes=[x.get('src') for x in soup.find_all('iframe')],
                          access_signals=sorted(set(re.findall(
                              'subscribe|subscription|log in|sign in|register|purchase|login',
                              text, re.I)))[:12])
        matches = [_title_matches(title, value, source) for source, value in candidates]
        citations = [i for i, (source, _) in enumerate(candidates) if source == 'citation_title']
        h1s = [i for i, (source, _) in enumerate(candidates) if source == 'h1']
        if citations and all(matches[i] for i in citations) and len(h1s) == 1:
            # Publishers sometimes put the subtitle outside h1. The COMPLETE
            # citation_title must already match, and the visible h1 must equal
            # the entire sufficiently specific main title at a colon boundary.
            parts = re.split(r'[:：]', title, maxsplit=1)
            if (len(parts) == 2 and norm(parts[1]) and len(norm(parts[0])) >= 40 and
                    len(norm(parts[0])) >= .4 * len(norm(title))):
                index = h1s[0]
                matches[index] = matches[index] or norm(candidates[index][1]) == norm(parts[0])
        ratio = max((SequenceMatcher(None, norm(title), norm(value)).ratio()
                     for _, value in candidates), default=0)
        match = bool(matches) and all(matches) and not challenge
        result.update(title_candidates=[{'source': source, 'title': value}
                                        for source, value in candidates],
                      title_similarity=round(ratio, 3), title_present=match,
                      title_match_source=', '.join(source for source, _ in candidates) if match else '',
                      title_conflict=bool(matches) and any(matches) and not all(matches),
                      text_chars=len(text),
                      page_state='访问验证或限制页面' if challenge else
                      ('目标题名在页面中确认' if match else
                       '取得PDF；身份待核对' if is_pdf else '页面取得；身份待核对'))
    except Exception as exc:
        result.update(parse_error=str(exc), page_state='页面解析失败；身份待核对')
    return result, text

def txt(x):return ''.join(x.itertext()).strip() if x is not None else ''
