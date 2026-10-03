"""The one-address deployment: wallet + Shield + phone app must start up and work together."""
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import sessionmaker

import database
import scorer
import shield_client
import wallet_api
from models import User
from wallet_helpers import make_engine

pytestmark = pytest.mark.skipif(not (scorer.ARTIFACT_DIR / "model.txt").exists(), reason="run train.py first")

import deploy.app as deployed  # noqa: E402


@pytest.fixture()
def live(monkeypatch):
    engine = make_engine()
    Session = sessionmaker(bind=engine, autoflush=False)
    monkeypatch.setattr(database, "engine", engine)
    monkeypatch.setattr(database, "SessionLocal", Session)
    monkeypatch.setenv("SEED_USERS", "150")
    app = deployed.create_app()
    with TestClient(app) as client:
        # the wallet reaches Shield over HTTP; here that call is routed to the mounted Shield inside the same app
        def to_shield(path, payload):
            response = client.post("/shield" + path, json=payload)
            response.raise_for_status()
            return response.json()
        monkeypatch.setattr(shield_client, "_post", to_shield)
        client.Session = Session
        yield client


def login(client, phone, pin="12345"):
    return {"Authorization": "Bearer " + client.post("/auth/login", json={"phone": phone, "pin": pin}).json()["token"]}


def test_start_up_fills_an_empty_database_with_the_demo_world(live):
    db = live.Session()
    assert db.scalar(select(func.count()).select_from(User)) > 150
    assert db.scalar(select(User).where(User.phone == "01711000001")).name == "Rahim Uddin"
    db.close()


def test_start_up_does_not_wipe_a_database_that_already_has_data(live):
    db = live.Session()
    before = db.scalar(select(func.count()).select_from(User))
    assert deployed.start_database(database.engine, live.Session) is False
    assert db.scalar(select(func.count()).select_from(User)) == before


def test_seeding_can_be_switched_off(monkeypatch):
    engine = make_engine()
    monkeypatch.setenv("SEED_ON_START", "0")
    assert deployed.start_database(engine, sessionmaker(bind=engine)) is False


def test_the_wallet_and_the_mounted_shield_both_answer(live):
    assert live.get("/health").json() == {"status": "ok"}
    shield = live.get("/shield/health").json()
    assert shield["status"] == "ok" and shield["model_loaded"] is True and shield["feature_count"] == 23


def test_the_scam_is_caught_through_the_one_address_setup(live):
    h = login(live, "01711000001")
    live.post("/demo/fake-sms", headers=h, json={"amount": 5000, "from_number": "01711999999"})
    r = live.post("/wallet/send/preview", headers=h, json={"recipient_phone": "01711999999", "amount": 5000, "behavior": {"on_call": True}})
    risk = r.json()["risk"]
    assert risk["shield_available"] and risk["action"] == "hold_30min" and risk["risk_pct"] >= 90
    mum = live.post("/wallet/send/preview", headers=h, json={"recipient_phone": "01711000002", "amount": 1000}).json()["risk"]
    assert mum["action"] == "allow"


def test_the_analyst_pages_and_the_demo_reset_work(live):
    nadia = login(live, "01911000001", "99999")
    assert live.get("/analyst/impact", headers=nadia).status_code == 200
    assert live.get("/analyst/model-report", headers=nadia).json()["report"]["test_fraud"] > 0
    assert live.post("/demo/reset", headers=nadia).status_code == 200


def test_importing_the_deployment_does_not_change_the_normal_wallet_app():
    assert not any(getattr(r, "path", "") == "/shield" for r in wallet_api.app.router.routes)
    assert deployed.app is not wallet_api.app


@pytest.mark.skipif(not deployed.DIST.exists(), reason="build the phone app first (npm run build)")
def test_the_phone_app_is_served_from_the_same_address(live):
    page = live.get("/")
    assert page.status_code == 200 and "<div id=\"root\">" in page.text
    assert live.get("/manifest.webmanifest").headers["content-type"].startswith("application/manifest+json")
    assert live.get("/sw.js").status_code == 200
    assert live.get("/icons/icon-512.png").status_code == 200
    assert live.get("/me").status_code == 401                 # API routes still win over the static files
