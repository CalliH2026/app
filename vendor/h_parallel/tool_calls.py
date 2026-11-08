"""Record real custom-tool invocations, independently from activity messages.

A cache hit is still an invocation of an H tool; ``cached`` explicitly shows
that it did not repeat the underlying provider work. Offline application work
is never inferred from a job's activity log.
"""
from contextvars import ContextVar
from datetime import datetime, timezone
from functools import wraps
import inspect
import json
import os
import re
import time
import uuid


_SENSITIVE = re.compile(r'password|passwd|secret|token|authorization|credential|cookie|api[_-]?key', re.I)
_CREDENTIAL_TEXT = re.compile(
    r'(?i)(\bbearer\s+)[^\s,;]+|'
    r'((?:api[_ -]?key|password|secret|token)\s*[=:]\s*)[^\s,;]+')


def _now():
    return datetime.now(timezone.utc).isoformat()


def _safe_value(value, secrets=(), depth=0):
    """Keep bounded, JSON-safe previews and redact credential-shaped fields."""
    if depth > 3:
        return '[résumé]'
    if hasattr(value, 'model_dump'):
        value = value.model_dump(mode='json')
    if isinstance(value, dict):
        items = list(value.items())
        result = {str(key): '[masqué]' if _SENSITIVE.search(str(key)) else
                  _safe_value(item, secrets, depth + 1) for key, item in items[:10]}
        if len(items) > 10:
            result['…'] = f'{len(items) - 10} autres champs'
        return result
    if isinstance(value, (tuple, list)):
        result = [_safe_value(item, secrets, depth + 1) for item in value[:4]]
        if len(value) > 4:
            result.append(f'… {len(value) - 4} autres éléments')
        return result
    if isinstance(value, str):
        text = value
        for secret in secrets:
            text = text.replace(secret, '[masqué]')
        text = _CREDENTIAL_TEXT.sub(lambda match: (match.group(1) or match.group(2)) + '[masqué]', text)
        return text if len(text) <= 240 else text[:237] + '…'
    if value is None or isinstance(value, (bool, int, float)):
        return value
    return f'[{type(value).__name__}]'


def _result_summary(value, secrets):
    if isinstance(value, str):
        # Tools commonly return JSON strings to the H SDK.
        try:
            value = json.loads(value) if len(value) <= 100_000 else value
        except (ValueError, TypeError):
            pass
    safe = _safe_value(value, secrets)
    text = safe if isinstance(safe, str) else json.dumps(safe, ensure_ascii=False)
    return text if len(text) <= 600 else text[:597] + '…'


class ToolCallTracker:
    """Persist one record per actual invocation without changing SDK schemas."""

    def __init__(self, job, persist, lock):
        self.job = job
        self.persist = persist
        self.lock = lock
        self._session_id = None
        self._record_ids = set()
        self._active_call = ContextVar('active_tool_call_' + uuid.uuid4().hex, default=None)
        self._secrets = tuple(value for name, value in os.environ.items()
                              if _SENSITIVE.search(name) and len(value) >= 8)

    def _save(self):
        # Observability must not convert a completed business action into an
        # apparent tool failure (which could cause the agent to repeat it).
        try:
            self.persist()
        except Exception:
            self.job['tool_call_tracking_error'] = 'Le journal des appels n’a pas pu être enregistré sur disque.'

    def set_session_id(self, session_id):
        """Attach the provider ID even when callbacks ran during start_session."""
        with self.lock:
            self._session_id = session_id
            for record in self.job.get('tool_calls', []):
                if record.get('id') in self._record_ids:
                    record['session_id'] = session_id
            self._save()

    def mark_cached(self):
        """Mark the current invocation as reusing an existing provider result."""
        record = self._active_call.get()
        if record is not None:
            with self.lock:
                record['cached'] = True

    def current_call_id(self):
        """Link a background execution to the model call which requested it."""
        record = self._active_call.get()
        return record.get('id') if record is not None else None

    def tool(self, function):
        signature = inspect.signature(function)

        @wraps(function)
        def tracked(*args, **kwargs):
            # Binding failures are also actual invocations and remain visible.
            try:
                bound = signature.bind(*args, **kwargs)
                bound.apply_defaults()
                arguments = dict(bound.arguments)
            except TypeError:
                arguments = {'arguments': args, 'keyword_arguments': kwargs}
            started = time.perf_counter()
            record = {
                'id': uuid.uuid4().hex,
                'name': function.__name__,
                'kind': 'custom',
                'status': 'running',
                'started_at': _now(),
                'ended_at': None,
                'duration_ms': None,
                'arguments': _safe_value(arguments, self._secrets),
                'result_summary': '',
                'cached': False,
                'session_id': self._session_id,
            }
            with self.lock:
                record['session_id'] = self._session_id
                self.job.setdefault('tool_calls', []).append(record)
                self._record_ids.add(record['id'])
                self._save()
            token = self._active_call.set(record)
            try:
                result = function(*args, **kwargs)
            except BaseException as error:
                with self.lock:
                    record.update(status='failed', ended_at=_now(),
                                  duration_ms=round((time.perf_counter() - started) * 1000, 2),
                                  result_summary=f'Échec de l’outil ({type(error).__name__}).')
                    self._save()
                raise
            else:
                try:
                    summary = _result_summary(result, self._secrets)
                except Exception:
                    summary = 'Résultat reçu ; aperçu indisponible.'
                with self.lock:
                    record.update(status='succeeded', ended_at=_now(),
                                  duration_ms=round((time.perf_counter() - started) * 1000, 2),
                                  result_summary=summary)
                    self._save()
                return result
            finally:
                self._active_call.reset(token)

        return tracked


def summarize_tool_calls(job):
    """Metrics from recorded calls only; activity events never affect counts."""
    records = [record for record in job.get('tool_calls', []) if isinstance(record, dict)]
    names = sorted({record['name'] for record in records if isinstance(record.get('name'), str)})
    navigation = sum(record.get('kind') == 'navigation' for record in records)
    return {
        'total': len(records),
        'succeeded': sum(record.get('status') == 'succeeded' for record in records),
        'failed': sum(record.get('status') == 'failed' for record in records),
        'running': sum(record.get('status') == 'running' for record in records),
        'cached': sum(bool(record.get('cached')) for record in records),
        'distinct_tools': len(names),
        'tool_names': names,
        'custom_total': sum(record.get('kind', 'custom') == 'custom' for record in records),
        'navigation_total': navigation,
        'coverage': 'custom_and_navigation' if navigation else 'custom',
    }
