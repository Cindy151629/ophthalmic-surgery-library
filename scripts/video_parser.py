"""Pure, conservative parsing of official video-resource HTML.

DOM media evidence means an identified playback entry point, never successful
playback, permission to embed, or permission to copy the video.
"""
import re
import urllib.parse
from bs4 import BeautifulSoup
from page_parser import parse_page_content, _title_matches


def _excluded(node, *, description=False):
    for parent in [node, *node.parents]:
        if getattr(parent, 'name', '') in ('aside', 'nav', 'footer', 'noscript', 'template'):
            return True
        attrs = getattr(parent, 'attrs', {}) or {}
        marker = ' '.join([str(attrs.get('id', '')), ' '.join(attrs.get('class', [])),
                           str(attrs.get('role', ''))])
        # WordPress uses no-sidebar as a page-layout class on body; it is not
        # an actual sidebar ancestor and must not invalidate the entire page.
        marker = re.sub(r'\bno-sidebar\b', '', marker, flags=re.I)
        if re.search(r'sidebar|related|recommend|comment|cookie|advert|analytics|'
                     r'(^|[\s_-])ad(?:s|slot|container)?(?:$|[\s_-])', marker, re.I):
            return True
        if description and re.search(r'transcript|transcription', marker, re.I):
            return True
        if ('hidden' in attrs or attrs.get('aria-hidden') == 'true' or
                re.search(r'display\s*:\s*none|visibility\s*:\s*hidden', str(attrs.get('style', '')), re.I)):
            return True
    return False


def _unique(nodes):
    out = []
    for node in nodes:
        if not _excluded(node) and all(node is not old for old in out):
            out.append(node)
    return out


def _scope_and_heading(soup, source):
    platform = source.get('id', '').casefold()
    if platform == 'moran':
        scopes = _unique(soup.select('main #content')) or _unique(soup.select('main'))
        if len(scopes) != 1:
            return None, None, ''
        scope = scopes[0]
        heads = _unique(scope.select('h2'))
        return scope, heads[0] if len(heads) == 1 else None, 'Moran CORE main #content h2'
    if platform == 'cybersight':
        # The official hero h1 is outside main. Pair it only with the one
        # library article; never treat comment articles as resource bodies.
        scopes = _unique(soup.select('main article.type-library, main article.library'))
        if len(scopes) == 1:
            heads = _unique(soup.select('h1.page-hero-title'))
            if not heads:
                heads = _unique(scopes[0].select('h1'))
            return scopes[0], heads[0] if len(heads) == 1 else None, 'Cybersight single library article + hero h1'
        if scopes:
            return None, None, ''
    # Conservative fallback for source templates with a semantic main/article.
    # Do not fall back to the entire body when no reliable resource scope exists.
    scopes = _unique(soup.select('main'))
    if len(scopes) != 1:
        scopes = _unique(soup.select('article'))
    if len(scopes) != 1:
        for selector in ('#main-content', '#maincontent', '#content'):
            scopes = _unique(soup.select(selector))
            if len(scopes) == 1:
                break
    if len(scopes) != 1:
        return None, None, ''
    scope = scopes[0]
    heads = _unique(scope.select('h1'))
    if not heads:
        heads = _unique(scope.select(source.get('title_selector', 'h1,h2')))
    return scope, heads[0] if len(heads) == 1 else None, 'unique main-resource heading'


def _web_url(value, base):
    try:
        url = urllib.parse.urljoin(base, value or '')
        parsed = urllib.parse.urlsplit(url)
        if parsed.scheme not in ('https', 'http') or not parsed.hostname or parsed.username or parsed.password:
            return None, None
        return url, parsed
    except ValueError:
        return None, None


def _iframe_media(value, base):
    url, parsed = _web_url(value, base)
    if not parsed:
        return None
    host = parsed.hostname.lower()
    patterns = {
        'www.youtube.com': ('youtube', r'/embed/([A-Za-z0-9_-]{6,})/?'),
        'youtube.com': ('youtube', r'/embed/([A-Za-z0-9_-]{6,})/?'),
        'www.youtube-nocookie.com': ('youtube', r'/embed/([A-Za-z0-9_-]{6,})/?'),
        'player.vimeo.com': ('vimeo', r'/video/(\d+)/?'),
        'fast.wistia.com': ('wistia', r'/embed/(?:iframe|medias)/([a-z0-9]{10})/?'),
        'fast.wistia.net': ('wistia', r'/embed/(?:iframe|medias)/([a-z0-9]{10})/?'),
    }
    if host not in patterns:
        return None
    kind, pattern = patterns[host]
    match = re.fullmatch(pattern, parsed.path)
    return {'kind': kind, 'media_id': match[1], 'url': url} if match else None


def _media(scope, base, source):
    entries = []
    for frame in scope.select('iframe'):
        if _excluded(frame):
            continue
        for attr in ('src', 'data-src'):
            entry = _iframe_media(frame.get(attr), base) if frame.get(attr) else None
            if entry:
                entries.append({**entry, 'locator': 'resource iframe[' + attr + ']'})
                break
    # Official Wistia asynchronous containers and current web-component syntax.
    # A stray .jsonp preload without its media container is insufficient.
    for node in scope.select('[class], wistia-player'):
        if _excluded(node):
            continue
        classes = node.get('class', [])
        media_id = None
        if 'wistia_embed' in classes:
            matches = [re.fullmatch(r'wistia_async_([a-z0-9]{10})', c) for c in classes]
            ids = [m[1] for m in matches if m]
            if len(ids) == 1:
                media_id = ids[0]
        elif node.name == 'wistia-player' and re.fullmatch(r'[a-z0-9]{10}', node.get('media-id', '')):
            media_id = node['media-id']
        if media_id:
            entries.append({'kind': 'wistia', 'media_id': media_id,
                            'locator': 'resource Wistia container media identifier'})
    allowed_hosts = {source.get('host', '').lower(), *[h.lower() for h in source.get('media_hosts', [])]}
    for video in scope.select('video'):
        if _excluded(video):
            continue
        nodes = [video, *video.select('source')]
        for node in nodes:
            for attr in ('src', 'data-src'):
                if not node.get(attr):
                    continue
                url, parsed = _web_url(node[attr], base)
                if (parsed and parsed.hostname.lower() in allowed_hosts and
                        re.search(r'\.(?:mp4|webm|mov|m4v|m3u8)$', parsed.path, re.I)):
                    entries.append({'kind': 'html5', 'url': url,
                                    'locator': 'resource video/source[' + attr + ']'})
    seen = set()
    result = []
    for entry in entries:
        key = (entry['kind'], entry.get('media_id') or entry.get('url'))
        if key not in seen:
            seen.add(key)
            result.append(entry)
    return result


def _description(scope, source):
    # Work on a separate tree so filtering text cannot change media provenance.
    body = BeautifulSoup(str(scope), 'html.parser')
    for node in list(body.find_all(True)):
        if node.parent is not None and (node.name in ('script', 'style', 'iframe', 'video') or _excluded(node, description=True)):
            node.decompose()
    text = body.get_text('\n', strip=True)
    if source.get('id', '').casefold() == 'moran':
        match = re.search(
            r'(?:Brief\s+Description|Description(?:\s+of\s+Case)?|Summary\s+of\s+the\s+Case|Case\s+Summary|History)\s*:\s*'
            r'(.+?)(?=\n(?:Format|Copyright|Introduction|Identifier|Series|References|Surgical\s+Steps|Keywords|Diagnosis|Faculty\s+Approval)\b|\Z)',
            text, re.S | re.I)
        return match[1].strip() if match else ''
    for node in body.select('p'):
        value = node.get_text(' ', strip=True)
        if len(value) < 40 or re.match(r'(?:accept cookies|subscribe|sign up|leave a comment|copyright|all rights reserved)', value, re.I):
            continue
        return value
    return ''


def parse_video_candidate(content, title, source, log):
    """Return ``(check, description, reason)``; ``reason is None`` means eligible.

    Does no I/O and never marks playback or embedding permission. The returned
    check includes ``official_title`` and ``video_entrypoints`` as DOM evidence.
    Source must name a configured official host, with optional HTML5 media_hosts.
    """
    check, _ = parse_page_content(content, title, log)
    check['video_entrypoints'] = []
    check['video_evidence_scope'] = 'source-page DOM only; no playback or embedding-permission test'
    if check.get('status') != 200:
        return check, '', '具体视频页面访问失败'
    if check.get('parse_error') or check.get('content_format') != 'HTML':
        return check, '', '具体视频页面不是可解析的 HTML'
    if (check.get('page_state') == '访问验证或限制页面' or
            re.search(r'^(?:login|log in|sign in|404|not found)\b', check.get('page_title', ''), re.I)):
        return check, '', '登录或访问验证页面'
    base = log.get('final_url') or log.get('requested_url') or ''
    _, parsed = _web_url(base, base)
    if not parsed or parsed.hostname.lower() != source.get('host', '').lower():
        return check, '', '最终页面不在配置的官方来源主机'
    soup = BeautifulSoup(content, 'html.parser')
    scope, heading, locator = _scope_and_heading(soup, source)
    if scope is None or heading is None:
        return check, '', '无法唯一定位主资源容器和题名'
    actual = heading.get_text(' ', strip=True)
    if not _title_matches(title, actual, 'h1') or check.get('title_conflict'):
        return check, '', '主资源题名与候选题名不一致'
    media = _media(scope, base, source)
    if not media:
        return check, '', '未确认主资源内的正式播放器或有效媒体标识'
    description = _description(scope, source)
    if not description:
        return check, '', '缺少主资源内的视频内容说明'
    check.update(official_title=actual, browser_title=check.get('page_title'),
                 page_title=actual, title_present=True, title_conflict=False,
                 title_match_source=locator, page_state='具体视频页题名、正文说明与播放入口已对应；播放未测试',
                 video_entrypoints=media, description_locator='primary resource description; transcript excluded')
    return check, description, None
