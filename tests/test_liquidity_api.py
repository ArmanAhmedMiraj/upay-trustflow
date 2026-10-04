"""Module 2 over HTTP: operations see every agent, an agent sees only their own forecast, and refill requests flow to operations."""
import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import sessionmaker

import database
import liq_model as M
import security
import wallet_api
import wallet_service as svc
from wallet_helpers import make_engine

pytestmark = pytest.mark.skipif(not M.exists(), reason="run shield-api/liquidity/liq_train.py first")


@pytest.fixture(autouse=True)
def fast_hashing(monkeypatch):
    monkeypatch.setattr(security, "ITERATIONS", 1000)


@pytest.fixture()
def client():
    engine = make_engine()
    Session = sessionmaker(bind=engine, autoflush=False)

    def override():
        d = Session()
        try:
            yield d
        finally:
            d.close()

    wallet_api.app.dependency_overrides[database.get_db] = override
    d = Session()
    svc.create_user(d, "01711000001", "Rahim", "12345")
    svc.create_user(d, "01811000001", "Agent Babul", "12345", role="agent")
    svc.create_user(d, "01811000009", "Agent Not In Demo", "12345", role="agent")
    svc.create_user(d, "01911000001", "Nadia", "99999", role="analyst")
    d.close()
    with TestClient(wallet_api.app) as c:
        yield c
    wallet_api.app.dependency_overrides.clear()


def login(client, phone, pin="12345"):
    return {"Authorization": "Bearer " + client.post("/auth/login", json={"phone": phone, "pin": pin}).json()["token"]}


def test_only_operations_staff_see_the_agent_overview(client):
    customer, agent, analyst = login(client, "01711000001"), login(client, "01811000001"), login(client, "01911000001", "99999")
    for path in ("/ops/agents?scenario=festival", "/ops/coverage", "/ops/liquidity-report", "/ops/refill-requests"):
        assert client.get(path).status_code == 401
        assert client.get(path, headers=customer).status_code == 403
        assert client.get(path, headers=agent).status_code == 403
        assert client.get(path, headers=analyst).status_code == 200


def test_the_overview_has_every_agent_with_counts_and_a_calendar(client):
    h = login(client, "01911000001", "99999")
    festival = client.get("/ops/agents?scenario=festival", headers=h).json()
    normal = client.get("/ops/agents?scenario=normal", headers=h).json()
    assert len(festival["agents"]) == 120 and festival["scenario"] == "festival" and festival["calendar"]["festival_rush"] is True
    assert festival["counts"]["red"] > 100 and normal["counts"]["green"] > 100
    assert festival["total_refill_cash"] > 20 * normal["total_refill_cash"] + 1
    assert festival["agents"][0]["status"] == "red" and {"cash_now", "runout_label", "refill_cash", "briefing_bn"} <= set(festival["agents"][0])


def test_bad_days_and_unknown_agents_are_refused_clearly(client):
    h = login(client, "01911000001", "99999")
    assert client.get("/ops/agents?day=5", headers=h).status_code == 422
    assert client.get("/ops/agents?day=500", headers=h).json()["code"] == "invalid_day"
    assert client.get("/ops/agents/9999?scenario=normal", headers=h).status_code == 404
    detail = client.get("/ops/agents/3?scenario=festival", headers=h).json()
    assert len(detail["p90_out"]) == 48 and detail["agent_id"] == 3


def test_coverage_and_the_evidence_for_the_forecasts(client):
    h = login(client, "01911000001", "99999")
    cov = client.get("/ops/coverage", headers=h).json()
    assert len(cov["agents"]) == 120 and len(cov["recommendations"]) >= 3
    rep = client.get("/ops/liquidity-report", headers=h).json()
    assert rep["scenarios"] == {"normal": 82, "payday": 88, "festival": 74} and rep["quality"]["p90_coverage_cash_out"] > 0.85
    assert rep["policy"]["forecast_driven"]["unmet_bdt"] < rep["policy"]["guess_with_same_average_cash"]["unmet_bdt"] * 0.05


def test_an_agent_sees_only_their_own_forecast(client):
    babul = login(client, "01811000001")
    mine = client.get("/agent/forecast?scenario=festival", headers=babul).json()
    assert mine["name"] == "Agent Babul" and mine["status"] == "red" and mine["refill_cash"] > 0 and mine["briefing_bn"]
    assert client.get("/agent/forecast?scenario=normal", headers=babul).json()["status"] == "green"
    assert client.get("/agent/forecast", headers=login(client, "01711000001")).status_code == 403          # customers cannot
    assert client.get("/agent/forecast", headers=login(client, "01911000001", "99999")).status_code == 403
    assert client.get("/agent/forecast", headers=login(client, "01811000009")).status_code == 404         # an agent outside the demo


def test_refill_requests_flow_from_the_agent_to_operations(client):
    babul, nadia = login(client, "01811000001"), login(client, "01911000001", "99999")
    assert client.post("/agent/refill-request", headers=babul, json={"scenario": "normal"}).json()["code"] == "nothing_needed"
    sent = client.post("/agent/refill-request", headers=babul, json={"scenario": "festival"}).json()["request"]
    assert sent["status"] == "open" and sent["cash_bdt"] > 0 and sent["needed_by"]
    mine = client.get("/agent/refill-requests", headers=babul).json()["requests"]
    assert [r["id"] for r in mine] == [sent["id"]]
    queue = client.get("/ops/refill-requests", headers=nadia).json()["requests"]
    assert queue[0]["agent"]["name"] == "Agent Babul" and queue[0]["cash_bdt"] == sent["cash_bdt"]
    done = client.post(f"/ops/refill-requests/{sent['id']}/dispatch", headers=nadia).json()["request"]
    assert done["status"] == "dispatched"
    assert client.post(f"/ops/refill-requests/{sent['id']}/dispatch", headers=nadia).status_code == 409
    assert client.post("/ops/refill-requests/9999/dispatch", headers=nadia).status_code == 404
    assert client.get("/agent/refill-requests", headers=babul).json()["requests"][0]["status"] == "dispatched"
    assert client.post(f"/ops/refill-requests/{sent['id']}/dispatch", headers=babul).status_code == 403   # agents cannot dispatch
