"""UI smoke test generated from the API contract. Do not edit; fix the page instead."""
from fastapi.testclient import TestClient

from backend.main import app

client = TestClient(app)


def test_page_is_served_and_loads_its_assets():
    r = client.get('/')
    assert r.status_code == 200 and '/static/app.js' in r.text and '/static/shell.js' in r.text and '/static/shell.css' in r.text
    assert '/static/ui-kit.css' in r.text  # the UI kit is always linked


def test_assets_are_served():
    for path in ('/static/style.css', '/static/ui-kit.css', '/static/shell.css', '/static/shell.js', '/static/app.js', '/static/fonts/inter-latin-wght-normal.woff2'):
        assert client.get(path).status_code == 200, path


def test_element_ids_are_unique():
    import collections, re
    ids = re.findall(r'\sid=["\']([^"\']+)["\']', client.get('/').text)
    dup = sorted(i for i, n in collections.Counter(ids).items() if n > 1)
    assert not dup, f'these element ids appear more than once: {dup}'
