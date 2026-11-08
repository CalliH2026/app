"""Safety and attribution of background PRONOTE route replay, without a browser."""
import copy

import pytest

from . import pronote_routes as routes


class Element:
    tag_name = 'div'
    accessible_name = 'Notes'
    text = 'Notes'
    attrs = {'role': 'tab'}
    clicked = False

    def is_displayed(self): return True
    def is_enabled(self): return True
    def get_attribute(self, name): return self.attrs.get(name)
    def click(self): self.clicked = True


class Driver:
    current_url = routes.DEMO_URL
    title = 'Saisie des notes - Espace Professeurs - PRONOTE 2026.2.8 - SITE DE DEMONSTRATION'
    text = 'Saisie des notes\nClasse/Groupe\nSélectionnez une classe ou un groupe'
    login = False

    def __init__(self):
        self.element = Element()
        self.elements = [self.element]
        self.scripts = []

    def execute_script(self, script):
        self.scripts.append(script)
        return {'login': self.login, 'text': self.text}

    def find_elements(self, by, selector):
        assert by == 'css selector'
        assert selector == '[role="tab"][data-observed="notes"]'
        return self.elements


def verified_catalog():
    catalog = routes.official_catalog()
    view = copy.deepcopy(catalog['routes']['notes'])
    view.update(status='verified', steps=[{'selector': '[role="tab"][data-observed="notes"]',
                                        'label': 'Notes', 'role': 'tab', 'purpose': 'navigation'}],
                verification={'observer': 'codex_harness', 'recorded_at': '2026-11-07T15:00:00Z',
                              'source_url': routes.DEMO_URL, 'app_version': routes.DEMO_VERSION,
                              'snapshot_sha256': 'a' * 64, 'evidence_id': 'test-fixture-not-a-live-route'})
    return routes.verified_route(catalog, view)


def test_no_demo_routes_are_inherited_by_a_school():
    catalog = routes.catalog_for_url('https://school.test/pronote/professeur.html')
    assert catalog['source_kind'] == 'school'
    assert catalog['routes'] == {}
    with pytest.raises(routes.RouteError):
        routes.navigate_route(Driver(), 'notes', routes.official_catalog())
    with pytest.raises(routes.RouteError):
        routes.read_route(Driver(), 'submitted_work', routes.official_catalog())


@pytest.mark.parametrize('url', ['https://ent.test/login', 'https://demo.index-education.net/other.html',
                                 'http://demo.index-education.net/pronote/professeur.html'])
def test_unexpected_source_is_not_read_or_clicked(url):
    driver = Driver()
    driver.current_url = url
    with pytest.raises(routes.RouteError): routes.navigate_route(driver, 'notes', verified_catalog())
    assert not driver.scripts and not driver.element.clicked


def test_login_and_stale_version_do_not_click():
    driver = Driver()
    driver.login = True
    with pytest.raises(routes.RouteError): routes.navigate_route(driver, 'notes', verified_catalog())
    assert not driver.element.clicked
    driver.login = False
    driver.title = driver.title.replace('2026.2.8', '2026.2.9')
    with pytest.raises(routes.RouteError): routes.navigate_route(driver, 'notes', verified_catalog())
    assert not driver.element.clicked


def test_read_has_content_hash_and_redacts_query():
    driver = Driver()
    driver.current_url += '&session=private-session'
    result = routes.read_route(driver, 'notes', routes.official_catalog())
    assert result['content_sha256'] == routes.hashlib.sha256(driver.text.encode()).hexdigest()
    assert '?' not in result['source_url'] and 'private-session' not in str(result)
    assert result['route_verification'] is None
    assert 'pièce jointe' in ' '.join(result['limitations'])
    driver.text = 'Page d’accueil'
    with pytest.raises(routes.RouteError): routes.read_route(driver, 'notes', routes.official_catalog())


def test_verified_route_rejects_changed_or_ambiguous_controls():
    driver = Driver()
    driver.element.accessible_name = 'Supprimer'
    with pytest.raises(routes.RouteError): routes.navigate_route(driver, 'notes', verified_catalog())
    assert not driver.element.clicked
    driver.element.accessible_name = 'Notes'
    driver.elements = [driver.element, Element()]
    with pytest.raises(routes.RouteError): routes.navigate_route(driver, 'notes', verified_catalog())
    assert not driver.element.clicked


def test_proof_cannot_be_reused_for_another_origin_or_version():
    catalog = verified_catalog()
    catalog['source_url'] = 'https://school.test/pronote/professeur.html'
    catalog['source_kind'] = 'school'
    with pytest.raises(ValueError): routes.validate_catalog(catalog)
    catalog = verified_catalog()
    catalog['app_version'] = '2026.2.9'
    with pytest.raises(ValueError): routes.validate_catalog(catalog)


def test_verified_read_does_not_invoke_app_internal_ids():
    driver = Driver()
    result = routes.navigate_route(driver, 'notes', verified_catalog())
    assert driver.element.clicked and result['route_verification']['observer'] == 'codex_harness'
    assert all(script == routes.READ_VIEW for script in driver.scripts)
    assert result['route_id'] == 'notes'


def test_write_named_control_and_submit_are_refused():
    catalog = verified_catalog()
    catalog['routes']['notes']['steps'][0]['label'] = 'Enregistrer'
    driver = Driver()
    with pytest.raises(routes.RouteError): routes.navigate_route(driver, 'notes', catalog)
    assert not driver.element.clicked
    driver.element.attrs = {'role': 'tab', 'type': 'submit'}
    with pytest.raises(routes.RouteError): routes.navigate_route(driver, 'notes', verified_catalog())
    assert not driver.element.clicked


def test_waits_for_breadcrumb_instead_of_accepting_a_stale_title():
    catalog = verified_catalog()
    catalog['routes']['notes']['expected_breadcrumb'] = 'Relevé de notes'
    catalog['routes']['notes']['expected_heading'] = ''
    driver = Driver()
    driver.text = 'Classe/Groupe\n3A\nMATHÉMATIQUES'
    def delayed_read(script):
        driver.scripts.append(script)
        return {'login': False, 'text': driver.text,
                'breadcrumb': 'Mon agenda' if len(driver.scripts) < 3 else 'Relevé de notes'}
    driver.execute_script = delayed_read
    result = routes.navigate_route(driver, 'notes', catalog, timeout=1)
    assert result['breadcrumb'] == 'Relevé de notes'
    assert result['visible_text'] == driver.text
    assert driver.element.clicked


def test_breadcrumb_mismatch_never_returns_an_unrelated_view():
    catalog = verified_catalog()
    catalog['routes']['notes']['expected_breadcrumb'] = 'Relevé de notes'
    driver = Driver()
    driver.execute_script = lambda script: {'login': False, 'text': driver.text, 'breadcrumb': 'Mon agenda'}
    with pytest.raises(routes.RouteError):
        routes.navigate_route(driver, 'notes', catalog, timeout=0)


def test_same_breadcrumb_does_not_accept_the_wrong_student_selection():
    catalog = verified_catalog()
    catalog['routes']['notes']['expected_breadcrumb'] = 'Relevé de notes'
    catalog['routes']['notes']['expected_heading'] = 'Relevé de notes 3A Trimestre 1 BERNARD Fanny'
    driver = Driver()
    driver.execute_script = lambda script: {'login': False,
                                            'text': 'Relevé de notes 3A Trimestre 1 Autre élève',
                                            'breadcrumb': 'Relevé de notes'}
    with pytest.raises(routes.RouteError):
        routes.navigate_route(driver, 'notes', catalog, timeout=0)


def test_redirect_during_click_is_rejected_before_reading_the_other_site():
    driver = Driver()
    driver.element.click = lambda: setattr(driver, 'current_url', 'https://ent.test/reauth')
    with pytest.raises(routes.RouteError): routes.navigate_route(driver, 'notes', verified_catalog())
    assert len(driver.scripts) == 1  # Only the initial PRONOTE auth/version guard.


def test_student_selection_is_verified_and_returned_without_input_values():
    catalog = verified_catalog()
    route = catalog['routes']['notes']
    route['expected_heading'] = 'MATHÉMATIQUES'
    route['expected_breadcrumb'] = 'Relevé de notes'
    route['expected_selections'] = [{'selector': '[role="combobox"][data-class]', 'text': '3A'},
                                    {'selector': '[role="combobox"][data-student]', 'text': 'BERNARD Fanny'}]
    driver = Driver()
    class_control, student_control = Element(), Element()
    class_control.attrs = {'role': 'combobox', 'aria-label': 'Sélectionnez une classe ou un groupe'}
    student_control.attrs = {'role': 'combobox', 'aria-label': 'Sélectionnez un élève'}
    class_control.text, student_control.text = '3A', 'BERNARD Fanny'
    original_find = driver.find_elements
    def find(by, selector):
        if selector.endswith('[data-class]'): return [class_control]
        if selector.endswith('[data-student]'): return [student_control]
        return original_find(by, selector)
    driver.find_elements = find
    driver.execute_script = lambda script: {'login': False, 'text': 'MATHÉMATIQUES\n16,00',
                                            'breadcrumb': 'Relevé de notes'}
    result = routes.navigate_route(driver, 'notes', catalog, timeout=0)
    assert [selection['text'] for selection in result['selections']] == ['3A', 'BERNARD Fanny']
    assert result['selections'][1]['label'] == 'Sélectionnez un élève'
    student_control.text = 'Autre élève'
    with pytest.raises(routes.RouteError): routes.navigate_route(driver, 'notes', catalog, timeout=0)
