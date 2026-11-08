"""Bounded evidence that H actually used a visual browser on the museum site.

Configuration and proposed policy actions alone are not execution evidence. Only
provider observation images and completed browser tool events qualify. Provider
reasoning, page text, image payloads and signed image URLs are never retained.
"""
from __future__ import annotations

import base64
import re
import unicodedata
from urllib.parse import urlsplit, urlunsplit


BROWSER_ACTIONS = frozenset({
    'click_web', 'double_click_web', 'right_click_web', 'scroll_web',
    'drag_web', 'hover_web', 'press_key_web', 'type_text_web',
    'navigate_web', 'goto_web', 'go_to_url', 'navigate', 'goto',
    'open_url', 'open_tab', 'new_tab', 'switch_tab', 'select_tab',
    'click', 'scroll', 'hover', 'press_key', 'type_text',
})
MAX_PAGES = 8
PAGE_SIZE = 100
MAX_SUMMARIES = 24
BLOCKED_TITLE_MARKERS = (
    'acces refuse', 'acces interdit', 'acces non autorise', 'access denied',
    'access forbidden', 'forbidden', 'captcha', 'request blocked',
    'verifying you are human', 'verify you are human', 'just a moment',
    'attention required', 'verification de securite', 'security check',
    'page introuvable', 'page non trouvee', 'page not found',
    'internal server error', 'service unavailable',
)


def _plain(value):
    return value.model_dump(mode='json') if hasattr(value, 'model_dump') else value


def _domain(value):
    if not isinstance(value, str):
        raise ValueError('Domaine officiel invalide.')
    name = value.lower().rstrip('.')
    if not re.fullmatch(r'[a-z0-9](?:[a-z0-9.-]*[a-z0-9])?', name) or '..' in name:
        raise ValueError('Domaine officiel invalide.')
    return name


def _official_url(value, domain):
    if not isinstance(value, str):
        return None
    try:
        parsed = urlsplit(value)
        host = (parsed.hostname or '').lower().rstrip('.')
        if (parsed.scheme != 'https' or parsed.username or parsed.password or
                parsed.port not in (None, 443) or
                not (host == domain or host.endswith('.' + domain))):
            return None
        # A replay needs the public page path, never query tokens or fragments.
        return urlunsplit(('https', host, parsed.path[:1600] or '/', '', ''))
    except ValueError:
        return None


def _has_image(value):
    if not isinstance(value, dict) or not isinstance(value.get('source'), str):
        return False
    source = value['source']
    if not source.strip():
        return False
    if value.get('type') == 'url':
        parsed = urlsplit(source)
        return (parsed.scheme == 'https' and bool(parsed.hostname)) or (
            not parsed.netloc and parsed.path.startswith('/sessions/') and '/resources/' in parsed.path)
    if value.get('type') == 'base64' and len(source) <= 20_000_000:
        try:
            image = base64.b64decode(source.split(',', 1)[-1], validate=True)
        except (ValueError, TypeError):
            return False
        return (image.startswith(b'\x89PNG\r\n\x1a\n') or image.startswith(b'\xff\xd8\xff') or
                (image.startswith(b'RIFF') and image[8:12] == b'WEBP'))
    return False


def _result_failed(data):
    result = data.get('result')
    return bool(data.get('error') or (isinstance(result, dict) and (
        result.get('error') or result.get('isError') or result.get('success') is False or
        result.get('status') in ('error', 'failed', 'blocked'))))


def _blocked_page(metadata):
    title = unicodedata.normalize('NFKD', str(metadata.get('title') or '')).encode('ascii', 'ignore').decode().lower()
    title = re.sub(r'\s+', ' ', title)
    return (any(marker in title for marker in BLOCKED_TITLE_MARKERS) or
            bool(re.search(r'\b(?:401|403|404|429|500|502|503)\b', title)) or
            any(str(metadata.get(key)) in ('401', '403', '404', '429', '500', '502', '503')
                for key in ('status_code', 'http_status')))


def extract_browser_evidence(events, allowed_domain):
    """Prove browser execution, without claiming verification of page facts."""
    domain = _domain(allowed_domain)
    urls, observations, actions, access_warnings = [], [], [], []
    visual_count = captured_visual_count = action_count = observation_count = blocked_count = 0
    current_url = None
    current_blocked = False
    for raw in events:
        event = _plain(raw)
        if not isinstance(event, dict):
            continue
        data = _plain(event.get('data'))
        if not isinstance(data, dict):
            continue
        kind = data.get('kind')
        at = str(event.get('timestamp') or '')[:64]
        if kind == 'observation_event':
            metadata = data.get('metadata')
            metadata = metadata if isinstance(metadata, dict) else {}
            # A foreign observation clears the action's scope immediately.
            current_url = _official_url(metadata.get('url'), domain)
            if data.get('type') not in ('web', 'browser') or not current_url:
                current_url = None
                current_blocked = False
                continue
            observation_count += 1
            if current_url not in urls and len(urls) < MAX_SUMMARIES:
                urls.append(current_url)
            visual = _has_image(data.get('image'))
            current_blocked = _blocked_page(metadata)
            captured_visual_count += int(visual)
            visual_count += int(visual and not current_blocked)
            blocked_count += int(current_blocked)
            title = str(metadata.get('title') or '')[:180]
            if current_blocked and len(access_warnings) < MAX_SUMMARIES:
                access_warnings.append(f"{title or 'Page inaccessible'} — {current_url} : contenu non vérifié.")
            if len(observations) < MAX_SUMMARIES:
                observations.append({'at': at, 'url': current_url,
                                     'title': title, 'visual': visual, 'blocked': current_blocked})
        elif kind == 'tool_result' and not _result_failed(data):
            tool = _plain(data.get('tool_req'))
            if not isinstance(tool, dict) or tool.get('tool_name') not in BROWSER_ACTIONS:
                continue
            args = tool.get('args')
            args = args if isinstance(args, dict) else {}
            explicit_target = next((args[key] for key in ('url', 'target_url', 'href') if key in args), None)
            scope = _official_url(explicit_target, domain) if explicit_target is not None else current_url
            if not scope or (current_blocked and explicit_target is None):
                continue
            action_count += 1
            if len(actions) < MAX_SUMMARIES:
                actions.append({'at': at, 'tool': tool['tool_name'], 'url': scope})
    verified = visual_count > 0 and action_count > 0
    return {'verified': verified, 'allowed_domain': domain, 'urls': urls,
            'observations': observations, 'actions': actions,
            'observation_count': observation_count, 'visual_observation_count': visual_count,
            'captured_visual_observation_count': captured_visual_count,
            'blocked_observation_count': blocked_count, 'access_warnings': access_warnings,
            'executed_action_count': action_count,
            'evidence_source': 'H session changes · observation images and completed browser tools',
            'scope': 'Preuve de navigation uniquement ; les informations publiées sur les pages ne sont pas validées par ce contrôle.',
            'reason': ('Navigation visuelle et action navigateur observées sur une page accessible du site officiel.' if verified else
                       'Une observation visuelle d’une page accessible et une action navigateur sur le site officiel restent à vérifier.')}


def browser_evidence(client, session_id, allowed_domain):
    """Read a bounded provider history, including changes during a custom tool."""
    events = []
    cursor = 0
    pages = 0
    for _ in range(MAX_PAGES):
        changes = client.sessions.get_session_changes(
            session_id, from_index=cursor, limit=PAGE_SIZE,
            include_events=True, wait_for_seconds=0)
        if changes is None:
            break
        payload = _plain(changes)
        if not isinstance(payload, dict):
            break
        entries = payload.get('new_events') or []
        if not entries:
            break
        pages += 1
        events.extend(entries)
        start = payload.get('first_index')
        start = start if isinstance(start, int) else cursor
        next_cursor = start + len(entries)
        if next_cursor <= cursor:
            break
        cursor = next_cursor
        if len(entries) < PAGE_SIZE:
            break
    evidence = extract_browser_evidence(events, allowed_domain)
    evidence.update(events_checked=len(events), pages_checked=pages,
                    history_truncated=pages >= MAX_PAGES)
    return evidence
