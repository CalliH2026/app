"""Execute only the independent outing tools actually requested by Holo4."""
from concurrent.futures import ThreadPoolExecutor, wait
from copy import deepcopy
from time import perf_counter
import uuid


TOOLS = {
    'search_museum_visit': 'visit',
    'prepare_transport_and_calendar': 'route',
    'read_class_and_template': 'roster',
}


class OutingExecutionPool:
    def __init__(self, job):
        from . import outings
        self.outings = outings
        self.job = job
        self.executor = ThreadPoolExecutor(max_workers=3, thread_name_prefix='holo4-outing')
        self.futures = {}
        self.closed = False
        self.inputs = deepcopy(job['input'])

    def _parallel(self):
        executions = self.job.setdefault('executions', [])
        active = sum(e['status'] == 'running' for e in executions)
        previous = self.job.get('parallel') or {}
        self.job['parallel'] = {'active_count': active, 'requested_count': len(executions),
                                'max_concurrent': max(active, previous.get('max_concurrent', 0))}

    def _ticket(self, execution, cached=False):
        return {'execution_id': execution['id'], 'task_id': execution['task_id'],
                'status': execution['status'], 'cached': cached,
                'message': 'Le résultat arrive dans le suivi des exécutions.'}

    def request(self, tool_name, tool_call_id=None):
        o = self.outings
        if tool_name not in TOOLS:
            raise ValueError('Outil de collecte inconnu.')
        with o.LOCK:
            if self.closed or self.job['status'] != 'preparing':
                raise RuntimeError('La session de préparation est terminée.')
            previous = next((e for e in self.job.get('executions', []) if e['tool_name'] == tool_name), None)
            if previous:
                return self._ticket(previous, cached=True)
            execution = {'id': uuid.uuid4().hex, 'tool_name': tool_name, 'task_id': TOOLS[tool_name],
                         'tool_call_id': tool_call_id, 'requested_by': 'holo4', 'status': 'requested',
                         'requested_at': o.now(), 'started_at': None, 'ended_at': None,
                         'duration_ms': None, 'result_summary': '', 'error': None}
            self.job.setdefault('executions', []).append(execution)
            next(t for t in self.job['tasks'] if t['id'] == execution['task_id'])['requested_at'] = execution['requested_at']
            self.job.setdefault('agent', {})['status'] = 'collecting'
            self._parallel()
            o._event(self.job, 'dispatch', 'Holo4 appelle ' + tool_name + ' : exécution demandée.')
            self.futures[tool_name] = self.executor.submit(self._run, execution)
            o._persist(self.job)
            return self._ticket(execution)

    def _run(self, execution):
        o = self.outings
        started = perf_counter()
        with o.LOCK:
            if self.closed or self.job['status'] != 'preparing':
                return
            execution.update(status='running', started_at=o.now())
            self._parallel()
            o._task(self.job, execution['task_id'], status='running')
            o._event(self.job, execution['task_id'], 'Exécution de l’outil demandé par Holo4 démarrée.')
        try:
            if execution['task_id'] == 'visit':
                result = {'visit': o._search_visit(self.inputs)}
                summary = 'Sources officielles recherchées et conservées.'
            elif execution['task_id'] == 'route':
                route, calendar = o._route_and_calendar(self.inputs, self.job['agenda_snapshot'])
                result = {'route': route, 'calendar': calendar}
                summary = 'Aller-retour calculé et agenda local comparé.'
            else:
                result = {'roster': o._read_roster(self.inputs)}
                summary = f"{result['roster']['student_count']} élèves lus ; modèle administratif chargé."
            error = None
        except Exception as exc:
            result, summary, error = {}, '', o._error(exc)
        with o.LOCK:
            # An HTTP operation cannot always be interrupted, but a closed
            # session must never publish its late results into the dossier.
            if self.closed or self.job['status'] != 'preparing':
                return
            execution.update(status='failed' if error else 'succeeded', ended_at=o.now(),
                             duration_ms=round((perf_counter() - started) * 1000, 2),
                             result_summary=summary, error=error)
            self._parallel()
            if not self.missing() and self.job['parallel']['active_count'] == 0:
                self.job.setdefault('agent', {})['status'] = 'results_available'
            if error:
                o._task(self.job, execution['task_id'], status='failed', error=error)
            else:
                o._change(self.job, **result)
                o._task(self.job, execution['task_id'], status='done', summary=summary)
            budget, dossier, warnings = o._build_dossier(self.job)
            o._change(self.job, budget=budget, dossier=dossier, warnings=warnings)
            o._event(self.job, execution['task_id'], error or summary)

    def missing(self):
        with self.outings.LOCK:
            return [name for name in TOOLS if name not in self.futures]

    def ready(self):
        with self.outings.LOCK:
            return (not self.missing() and all(e['status'] in ('succeeded', 'failed')
                    for e in self.job.get('executions', [])))

    def assert_ready(self):
        missing = self.missing()
        if missing:
            raise ValueError('Holo4 doit encore appeler : ' + ', '.join(missing))
        if not self.ready():
            raise ValueError('Des outils sont encore en cours. Appeler wait_for_outing_results avant le remplissage.')

    def wait_for_results(self, timeout=100):
        o = self.outings
        with o.LOCK:
            missing = self.missing()
            if missing:
                raise ValueError('Demander d’abord les outils indépendants : ' + ', '.join(missing))
            futures = list(self.futures.values())
            self.job.setdefault('agent', {})['status'] = 'waiting_for_results'
            o._event(self.job, 'wait', 'Holo4 attend les résultats des outils qu’il a appelés.')
        wait(futures, timeout=timeout)
        with o.LOCK:
            ready = self.ready()
            if ready:
                self.job['agent']['status'] = 'reviewing'
            o._persist(self.job)
            return {'ready': ready, 'pending': [e['tool_name'] for e in self.job.get('executions', [])
                                                if e['status'] in ('requested', 'running')],
                    'executions': deepcopy(self.job.get('executions', []))}

    def close(self):
        o = self.outings
        with o.LOCK:
            if self.closed:
                return
            self.closed = True
            for execution in self.job.get('executions', []):
                if execution['status'] in ('requested', 'running'):
                    execution.update(status='cancelled', ended_at=o.now(),
                                     error='La session Holo4 est terminée avant la réception du résultat.')
                    o._task(self.job, execution['task_id'], status='failed', error=execution['error'])
            for name in self.missing():
                o._task(self.job, TOOLS[name], status='failed', error='Holo4 n’a pas lancé cet outil.')
            self._parallel()
            o._persist(self.job)
        self.executor.shutdown(wait=False, cancel_futures=True)
