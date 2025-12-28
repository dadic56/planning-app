import os
import pytest

playwright = pytest.importorskip("playwright.sync_api", reason="Playwright non installé")

from backend import create_app
from backend.models import db


@pytest.fixture(scope="module")
def live_server():
    """Démarre un serveur Flask en mode test pour Playwright."""
    app = create_app()
    app.config.update({
        "TESTING": True,
        "SQLALCHEMY_DATABASE_URI": "sqlite:///:memory:",
    })

    with app.app_context():
        db.create_all()

    import threading
    from werkzeug.serving import make_server

    server = make_server("127.0.0.1", 5005, app)

    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield "http://127.0.0.1:5005"
    server.shutdown()
    thread.join(timeout=1)


@pytest.mark.e2e
def test_homepage_loads(live_server):
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        page.goto(live_server)
        assert page.title() == "Planning Hebdomadaire"
        browser.close()
