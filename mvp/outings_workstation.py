"""Evidence from H's shell-first ephemeral workstation.

The installed browser-cli emits web receipts plus @@attach image markers. The
managed shell result carries the matching image bytes in ``attachments``. This
parser accepts that known contract only: an arbitrary shell command, URL string,
proposed action or unattached receipt cannot establish computer use. Other
provider result serializers remain unverified until observed and supported.

The cloud provider also serializes one completed shell result followed by its
image resource in a two-item list, stripping @@attach from the text. Accept it
only for one screenshot receipt and a H-hosted image bound to this session.
"""
from __future__ import annotations

import re
import shlex
import base64
from io import BytesIO
from urllib.parse import urlsplit

from PIL import Image

from .outings_holo import (_blocked_page, _domain, _has_image, _official_url,
                           _plain, MAX_PAGES, MAX_SUMMARIES, PAGE_SIZE)


WEB_ACTIONS = frozenset({'goto', 'click', 'scroll', 'hover', 'drag', 'key', 'type',
                         'back', 'forward', 'refresh', 'tab'})
WEB_READS = frozenset({'screenshot', 'zoom', 'snap', 'text', 'find', 'status', 'wait', 'help'})
RECEIPT = re.compile(r'^\[web\s+([a-z]+)(?:[^\]]*)\]\s*(.*)$')
RESOURCE_PATH = re.compile(
    r'^/api/v1/trajectories/([^/]+)/resources/([^/]+)/([^/]+)/screenshot-[A-Za-z0-9_-]+\.(png|jpe?g|webp)$')
SCREENSHOT_PATH = re.compile(r'^/tmp/screenshots/[0-9]+\.(?:png|jpe?g|webp)$')


def workstation_environment():
    """Explicit fresh cloud disk, without a persistent volume or local bridge."""
    return {'id': 'outing-workstation', 'kind': 'workstation', 'host': 'cloud',
            'storage': {'ephemeral': True}}


def _commands(args):
    if not isinstance(args, dict):
        return None
    command = args.get('command')
    if not isinstance(command, str) or len(command) > 12_000 or re.search(r'[\n\r`$()<>]', command):
        return None
    try:
        lexer = shlex.shlex(command, posix=True, punctuation_chars=';&|')
        lexer.whitespace_split, lexer.commenters = True, ''
        segments, current = [], []
        for token in lexer:
            if token in (';', '&&'):
                if not current:
                    return None
                segments.append(current)
                current = []
            elif token in ('|', '||', '&') or set(token) <= set(';&|'):
                return None
            else:
                current.append(token)
        if current:
            segments.append(current)
        if not segments or any(len(s) < 2 or s[0] != 'web' or s[1] not in WEB_ACTIONS | WEB_READS for s in segments):
            return None
        return segments
    except ValueError:
        return None


def _fields(text):
    try:
        return dict(token.split('=', 1) for token in shlex.split(text) if '=' in token)
    except ValueError:
        return {}


def _provider_image(value, session_id):
    value = _plain(value)
    if not isinstance(value, dict) or value.get('type') != 'url':
        return False
    source = value.get('source')
    if not isinstance(source, str) or len(source) > 4000:
        return False
    try:
        url = urlsplit(source)
        if (url.scheme != 'https' or url.hostname not in ('agp.eu.hcompany.ai', 'agp.hcompany.ai') or
                url.username or url.password or url.port not in (None, 443)):
            return False
        match = RESOURCE_PATH.fullmatch(url.path)
        if not match or match[1] != match[3] or (session_id is not None and match[1] != session_id):
            return False
        media = {'png':'image/png', 'jpg':'image/jpeg', 'jpeg':'image/jpeg', 'webp':'image/webp'}[match[4]]
        return value.get('media_type') == media
    except ValueError:
        return False


def _result(data, session_id):
    result = _plain(data.get('result'))
    provider_image = False
    if isinstance(result, list):
        if len(result) != 2 or not _provider_image(result[1], session_id):
            return None
        result, provider_image = _plain(result[0]), True
    if (data.get('error') or not isinstance(result, dict) or
            type(result.get('exit_code')) is not int or result['exit_code'] != 0):
        return None
    if (result.get('state', 'completed') != 'completed' or result.get('timed_out') or
            result.get('failure') or result.get('error') or result.get('isError') or
            result.get('success') is False or result.get('status') in ('failed', 'error', 'blocked')):
        return None
    output = result.get('output')
    if output is None:
        output = '\n'.join(str(result.get(k) or '') for k in ('stdout', 'stderr'))
    if not isinstance(output, str) or len(output) > 100_000:
        return None
    attachments = result.get('attachments') or {}
    return output, attachments if isinstance(attachments, dict) else {}, provider_image


def _valid_attachment(source):
    if not isinstance(source, str) or not _has_image({'type': 'base64', 'source': source}):
        return False
    try:
        raw = base64.b64decode(source.split(',', 1)[-1], validate=True)
        with Image.open(BytesIO(raw)) as image:
            if image.format not in ('PNG', 'JPEG', 'WEBP') or image.width * image.height > 20_000_000:
                return False
            image.verify()
        return True
    except Exception:
        return False


def extract_workstation_evidence(events, allowed_domain, session_id=None):
    domain = _domain(allowed_domain)
    observations, actions, urls, warnings = [], [], [], []
    visual_count = captured_count = blocked_count = action_count = shell_count = 0
    current_url, current_blocked = None, False
    for raw in events:
        event = _plain(raw)
        data = _plain(event.get('data')) if isinstance(event, dict) else None
        if not isinstance(data, dict) or data.get('kind') != 'tool_result':
            continue
        tool = _plain(data.get('tool_req'))
        if not isinstance(tool, dict) or tool.get('tool_name') != 'shell':
            continue
        commands, result = _commands(tool.get('args')), _result(data, session_id)
        if commands is None or result is None:
            continue
        shell_count += 1
        output, attachments, provider_image = result
        requested = {command[1] for command in commands}
        attached_paths = {line.removeprefix('@@attach ').strip() for line in output.splitlines()
                          if line.startswith('@@attach ')}
        screenshot_receipts = [line for line in output.splitlines()
                               if (match := RECEIPT.fullmatch(line)) and match[1] == 'screenshot']
        single_provider_screenshot = (provider_image and len(screenshot_receipts) == 1 and
                                      sum(command[1] == 'screenshot' for command in commands) == 1)
        at = str(event.get('timestamp') or '')[:64]
        for line in output.splitlines():
            match = RECEIPT.fullmatch(line)
            if not match or match[1] not in requested:
                continue
            verb, fields = match[1], _fields(match[2])
            if 'url' in fields:
                current_url = _official_url(fields['url'], domain)
                current_blocked = _blocked_page(fields)
            if not current_url:
                continue
            if current_url not in urls and len(urls) < MAX_SUMMARIES:
                urls.append(current_url)
            if verb in WEB_ACTIONS and not current_blocked:
                action_count += 1
                if len(actions) < MAX_SUMMARIES:
                    actions.append({'at': at, 'tool': 'shell:web.' + verb, 'url': current_url})
            if verb != 'screenshot':
                continue
            path = fields.get('saved', '')
            source = attachments.get(path)
            inline_visual = path.startswith('/') and path in attached_paths and _valid_attachment(source)
            resource_visual = single_provider_screenshot and bool(SCREENSHOT_PATH.fullmatch(path))
            visual = bool(inline_visual or resource_visual)
            captured_count += int(visual)
            visual_count += int(visual and not current_blocked)
            blocked_count += int(current_blocked)
            title = str(fields.get('title') or '')[:180]
            if current_blocked and len(warnings) < MAX_SUMMARIES:
                warnings.append(f"{title or 'Page inaccessible'} — {current_url} : contenu non vérifié.")
            if len(observations) < MAX_SUMMARIES:
                observations.append({'at': at, 'url': current_url, 'title': title,
                                     'visual': visual, 'blocked': current_blocked,
                                     'environment': 'workstation',
                                     'image_provenance': 'provider_session_resource' if resource_visual else
                                         'matching_inline_attachment' if inline_visual else 'unverified'})
    verified = visual_count > 0 and action_count > 0
    return {'verified': verified, 'allowed_domain': domain, 'environment': 'workstation',
            'storage': 'ephemeral', 'urls': urls, 'observations': observations, 'actions': actions,
            'observation_count': len(observations), 'visual_observation_count': visual_count,
            'captured_visual_observation_count': captured_count, 'blocked_observation_count': blocked_count,
            'access_warnings': warnings, 'executed_action_count': action_count,
            'executed_shell_count': shell_count,
            'evidence_source': 'H session changes · completed shell web receipts with matching image attachments',
            'scope': 'Preuve d’exécution de la workstation et de navigation uniquement ; les tarifs restent issus des sources conservées.',
            'reason': ('Navigation et capture du site officiel observées dans la workstation éphémère.' if verified else
                       'Une commande web réussie et sa capture attachée du site officiel restent à vérifier.')}


def workstation_evidence(client, session_id, allowed_domain):
    events, cursor, pages = [], 0, 0
    for _ in range(MAX_PAGES):
        changes = client.sessions.get_session_changes(session_id, from_index=cursor, limit=PAGE_SIZE,
                                                      include_events=True, wait_for_seconds=0)
        payload = _plain(changes)
        if not isinstance(payload, dict) or not payload.get('new_events'):
            break
        entries = payload['new_events']
        pages += 1
        events.extend(entries)
        start = payload.get('first_index')
        next_cursor = (start if isinstance(start, int) else cursor) + len(entries)
        if next_cursor <= cursor:
            break
        cursor = next_cursor
        if len(entries) < PAGE_SIZE:
            break
    evidence = extract_workstation_evidence(events, allowed_domain, session_id=session_id)
    evidence.update(events_checked=len(events), pages_checked=pages, history_truncated=pages >= MAX_PAGES)
    return evidence
