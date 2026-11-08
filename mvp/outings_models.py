"""Official H Models API tool loop; only model-requested local tools execute.

This transport never creates an Agents session or a workstation. Tool handlers
remain responsible for receipts, revision guards and local-only simulation.
"""
import inspect
import json
import time

import httpx


ENDPOINT = 'https://api.hcompany.ai/v1/chat/completions'


class ModelsError(RuntimeError):
    """Bounded local error text safe to display without provider response bodies."""


def tool_schema(function):
    """Expose the deliberately small no-argument/string-argument tool contract."""
    parameters = {}
    required = []
    for name, parameter in inspect.signature(function).parameters.items():
        if parameter.kind not in (parameter.POSITIONAL_OR_KEYWORD, parameter.KEYWORD_ONLY):
            raise ValueError('Unsupported demonstration tool signature.')
        if parameter.annotation not in (str, 'str'):
            raise ValueError('Demonstration tool arguments must be strings.')
        parameters[name] = {'type': 'string'}
        if parameter.default is inspect.Parameter.empty:
            required.append(name)
    return {'type': 'function', 'function': {
        'name': function.__name__, 'description': inspect.getdoc(function) or function.__name__,
        'parameters': {'type': 'object', 'properties': parameters, 'required': required,
                       'additionalProperties': False}}}


def _arguments(function, raw):
    arguments = json.loads(raw)
    if not isinstance(arguments, dict):
        raise ValueError('Les arguments doivent être un objet JSON.')
    signature = inspect.signature(function)
    signature.bind(**arguments)
    if any(not isinstance(value, str) for value in arguments.values()):
        raise ValueError('Les identifiants receipt_id doivent être des chaînes de caractères.')
    return arguments


def run_function_calls(*, api_key, model, functions, prompt, missing, guard,
                       on_response, max_rounds=12, timeout_seconds=180, client_factory=httpx.Client):
    """Run Holo4's chosen calls and return only after every required tool succeeds.

    No missing handler is called by this loop. Unknown tools and invalid
    arguments are returned to the model as errors without invoking a handler.
    """
    tools = {function.__name__: function for function in functions}
    schemas = [tool_schema(function) for function in functions]
    messages = [{'role': 'system', 'content': prompt},
                {'role': 'user', 'content': 'Prépare cette démonstration avec les outils fournis. Commence par lire le contexte.'}]
    deadline = time.monotonic() + timeout_seconds
    with client_factory(headers={'Authorization': 'Bearer ' + api_key}) as client:
        for round_index in range(1, max_rounds + 1):
            guard()
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError('Holo4 Models API n’a pas terminé les outils dans le délai prévu.')
            try:
                response = client.post(ENDPOINT, json={
                    'model': model, 'messages': messages, 'tools': schemas,
                    'tool_choice': 'required', 'max_tokens': 4096,
                }, timeout=min(60.0, remaining))
            except httpx.TimeoutException:
                raise TimeoutError('Holo4 Models API n’a pas répondu dans le délai prévu.') from None
            if response.status_code != 200:
                raise ModelsError(f'Holo4 Models API a refusé la requête (HTTP {response.status_code}).')
            payload = response.json()
            guard()
            on_response({'id': payload.get('id'), 'model': payload.get('model', model),
                         'round': round_index, 'usage': payload.get('usage') or {},
                         'request_id': response.headers.get('x-request-id')})
            try:
                message = payload['choices'][0]['message']
                calls = message.get('tool_calls') or []
                if not isinstance(calls, list):
                    raise ValueError()
            except (KeyError, IndexError, TypeError, ValueError):
                raise ModelsError('La réponse Holo4 Models API ne contient pas de message exploitable.') from None
            if not calls:
                messages.append({'role': 'assistant', 'content': message.get('content') or ''})
                messages.append({'role': 'user', 'content': 'Appelle réellement les outils restants : ' + ', '.join(sorted(missing()))})
                continue
            ids = [call.get('id') for call in calls if isinstance(call, dict)]
            if len(ids) != len(calls) or any(not isinstance(value, str) or not value for value in ids) or len(set(ids)) != len(ids):
                raise ModelsError('La réponse Holo4 contient des identifiants d’appels invalides.')
            messages.append({'role': 'assistant', 'content': message.get('content'), 'tool_calls': calls})
            for call in calls:
                guard()
                try:
                    definition = call['function']
                    name = definition['name']
                    function = tools.get(name)
                    if call.get('type') != 'function' or function is None:
                        raise ValueError('Fonction indisponible dans cette démonstration.')
                    arguments = _arguments(function, definition['arguments'])
                    result = function(**arguments)
                    content = result if isinstance(result, str) else json.dumps(result, ensure_ascii=False)
                except (ValueError, TypeError, KeyError, json.JSONDecodeError) as exc:
                    content = json.dumps({'error': str(exc), 'external_effects': False}, ensure_ascii=False)
                messages.append({'role': 'tool', 'tool_call_id': call['id'], 'content': content})
            guard()
            if not missing():
                return
    raise ModelsError('Holo4 n’a pas demandé tous les outils de démonstration dans la limite de tours prévue.')
