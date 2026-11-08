"""A queued H message must not consume the preceding idle answer as a retry."""
from types import SimpleNamespace
from copy import deepcopy
import json
import pytest
from . import engine


@pytest.mark.parametrize('fresh_answer', [{'version':'corrected'}, {'version':'old'}])
def test_repair_waits_for_new_request_answer_even_when_value_is_identical(monkeypatch, fresh_answer):
    old_answer = {'version':'old'}
    previous = SimpleNamespace(next_from_index=50, answer=old_answer)
    batches = iter([
        SimpleNamespace(next_from_index=51, answer=old_answer, status='idle', error=None,
                        events=[{'type':'AgentCompletionEvent','data':{'reason':'finished'}}]),
        SimpleNamespace(next_from_index=53, answer=old_answer, status='idle', error=None,
                        events=[{'type':'RequestStartEvent','data':{}}, {'type':'AgentStartedEvent','data':{}}]),
        SimpleNamespace(next_from_index=54, answer=fresh_answer, status='idle', error=None,
                        events=[{'type':'AgentEvent','data':{'kind':'tool_result','tool_req':{'tool_name':'answer'},'result':'Answer sent'}}]),
    ])
    cursors = []
    class Session:
        def wait_for_completion(self, **kwargs):
            cursors.append(kwargs['from_index'])
            return next(batches)
    monkeypatch.setattr(engine.time, 'sleep', lambda _: None)
    result = engine.wait_for_fresh_answer(Session(), previous)
    assert result.answer == fresh_answer
    assert cursors == [50, 51, 53]


def test_quote_candidates_are_literal_school_excerpts():
    documents = engine.FIXTURE['documents']
    candidates = engine.quote_candidates(documents)
    for document in documents:
        assert candidates[document['id']]
        assert all(quote in document['text'] for quote in candidates[document['id']])
    assert any('conclusion rédigée' in quote for quote in candidates['copie'])
    answer = engine.offline_dossier('points')
    answer['evidence'][0]['quote'] = 'conclusion réduite 0/1'
    with pytest.raises(ValueError, match='Citation non conforme'):
        engine.checked_answer(answer, [])


def test_source_ids_and_typographic_quotes_return_the_literal_source():
    answer = engine.offline_dossier('points')
    answer['evidence'][0].update(source_ids=['  Copie  '], quote="NOTE de l'exercice :  3/6.")
    answer['evidence'][1].update(source_ids=[' Consigne '], quote="Justifier le choix du théorème, écrire l'égalité, détailler le calcul et conclure avec l'unité.")
    answer['scenes'][-1]['source_ids'] = [' Methode', 'WEB-2']
    result = engine.checked_answer(answer, [{'id':'web-2'}])
    assert result['evidence'][0]['source_ids'] == ['copie']
    assert result['evidence'][0]['quote'] == 'Note de l’exercice : 3/6.'
    assert result['evidence'][1]['quote'] == 'Justifier le choix du théorème, écrire l’égalité, détailler le calcul et conclure avec l’unité.'
    assert result['scenes'][-1]['source_ids'] == ['methode', 'web-2']


def test_identifier_accents_resolve_only_unambiguous_known_sources():
    answer = engine.offline_dossier('progress')
    answer['scenes'][-1]['source_ids'] = [' méthode']
    assert engine.checked_answer(answer, [])['scenes'][-1]['source_ids'] == ['methode']
    with pytest.raises(ValueError, match='ambiguë'):
        engine.checked_answer(answer, [{'id':'méthode'}])
    answer['scenes'][-1]['source_ids'] = ['méthode-inventée']
    with pytest.raises(ValueError, match='inconnue'):
        engine.checked_answer(answer, [])


def test_repair_server_error_fails_without_waiting_for_timeout(monkeypatch):
    previous = SimpleNamespace(next_from_index=50)
    class Session:
        def wait_for_completion(self, **kwargs):
            return SimpleNamespace(next_from_index=52, answer={'version':'old'}, status='idle', error=None,
                                   events=[{'type':'AgentEvent','data':{'kind':'error_event','error':'Error','origin':'agent'}}])
    monkeypatch.setattr(engine.time, 'sleep', lambda _: pytest.fail('Must not sleep after H error'))
    with pytest.raises(RuntimeError, match='signalé une erreur'):
        engine.wait_for_fresh_answer(Session(), previous)


def test_dossier_repair_uses_a_new_session_and_existing_frozen_evidence(monkeypatch):
    context = deepcopy(engine.FIXTURE)
    original_text = context['documents'][0]['text']
    transcription = {'text':'Comment peut-il progresser ?', 'job_id':'existing-gladia'}
    search = {'query':'rédaction guidée', 'sources':[{'id':'web-1','title':'Ressource existante'}]}
    job = {'id':'repair-test', 'session_id':'original-navigation', 'events':[]}
    captured = {}
    class Session:
        id = 'fresh-validation'
        def wait_for_completion(self, **kwargs):
            return SimpleNamespace(status='idle', answer=engine.offline_dossier('progress'))
        def cancel(self):
            pytest.fail('Successful correction must not cancel its session')
    class Client:
        def start_session(self, **kwargs):
            captured['agent'] = kwargs['agent']
            captured['tools'] = [tool.__name__ for tool in kwargs['tools']]
            assert kwargs['answer_schema'] is engine.AgentDossier
            context['documents'][0]['text'] = 'Changed after snapshot'
            captured['context'] = json.loads(kwargs['tools'][0]())
            return Session()
    monkeypatch.setattr(engine, 'save', lambda _: None)
    monkeypatch.setattr(engine, 'transcribe', lambda *a, **kw: pytest.fail('Repair must not retranscribe'))
    monkeypatch.setattr(engine, 'search', lambda *a, **kw: pytest.fail('Repair must not search again'))
    result = engine.repair_dossier(Client(), job, context, transcription, search, {'invalid':'answer'}, ValueError('Invalid quote'))
    assert captured['agent']['environments'] == []
    assert captured['tools'] == ['read_repair_context']
    assert captured['context']['documents'][0]['text'] == original_text
    assert captured['context']['transcription'] == transcription
    assert captured['context']['search'] == search
    assert result.answer['intent'] == 'progress'
    assert job['session_id'] == 'original-navigation'
    assert job['validation_session_ids'] == ['fresh-validation']


def test_selected_quote_is_extracted_from_catalog_without_model_transcription():
    documents = engine.FIXTURE['documents']
    catalog = engine.quote_catalog(documents)
    assert catalog == engine.quote_catalog(deepcopy(documents))
    selected = next(identifier for identifier, entry in catalog.items() if 'un exemple autonome' in entry['quote'])
    answer = engine.offline_dossier('progress')
    answer['evidence'] = [
        {'claim':'Un exemple autonome permet de vérifier la méthode.', 'quote_id':selected,
         'quote':'un exemple autonomes', 'source_ids':['source-inventée']},
        {'claim':'La consigne décrit les étapes attendues.', 'quote_id':'q001'},
    ]
    agent_answer = engine.AgentDossier.model_validate(answer)
    assert 'quote' not in agent_answer.model_dump()['evidence'][0]
    result = engine.checked_answer(agent_answer, [], documents)
    assert result['evidence'][0]['quote'] == catalog[selected]['quote']
    assert result['evidence'][0]['source_ids'] == [catalog[selected]['source_id']]
    assert result['evidence'][0]['quote_id'] == selected
    assert 'autonomes' not in result['evidence'][0]['quote']
    answer['evidence'][0]['quote_id'] = 'q999'
    with pytest.raises(ValueError, match='Extrait scolaire inconnu'):
        engine.checked_answer(answer, [], documents)
