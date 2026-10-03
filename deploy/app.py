"""One web service for the whole demo: the phone app, the wallet API and Shield, on one address.

    uvicorn deploy.app:app --host 0.0.0.0 --port $PORT

 - The wallet API is the main application.
 - Shield is mounted inside it at /shield and the wallet talks to it on the same machine.
 - The built phone app (wallet-app/dist) is served at "/".
 - On start-up the database is created and, if empty, filled with the demo world (about 5 seconds).

Settings (environment variables)
    PORT           set by the hosting service
    SEED_ON_START  "0" to start with an empty database (default "1")
    SEED_USERS     size of the demo world (default 1500)
    DEMO_MODE      "0" hides the demo tools (default "1")
    PIN_PEPPER     secret mixed into PIN hashes (set a random value in production)
"""
import mimetypes
import os
import pathlib
import sys
from contextlib import asynccontextmanager

ROOT = pathlib.Path(__file__).resolve().parents[1]
for sub in ("wallet-api", "shield-api", "shield-api/transfer_risk", "simulator"):
    sys.path.insert(0, str(ROOT / sub))

# the wallet reaches Shield over HTTP, on this same machine
os.environ.setdefault("SHIELD_API_URL", f"http://127.0.0.1:{os.getenv('PORT', '8000')}/shield")
mimetypes.add_type("application/manifest+json", ".webmanifest")

from fastapi import FastAPI  # noqa: E402
from fastapi.middleware.cors import CORSMiddleware  # noqa: E402
from fastapi.routing import APIRoute  # noqa: E402
from fastapi.staticfiles import StaticFiles  # noqa: E402

import database  # noqa: E402
import messages  # noqa: E402
import models  # noqa: E402,F401  (registers the tables)
import scorer  # noqa: E402
import shield_api  # noqa: E402
import wallet_api  # noqa: E402

DIST = ROOT / "wallet-app" / "dist"


def start_shield() -> None:
    """Load the model into the mounted Shield app. If this fails the wallet keeps working (Shield reports 'degraded')."""
    try:
        shield_api.app.state.artifacts = scorer.load_artifacts()
        shield_api.app.state.load_error = None
    except Exception as exc:
        shield_api.app.state.artifacts = None
        shield_api.app.state.load_error = str(exc)
    shield_api.app.state.llm = messages.make_llm_from_env()


def start_database(engine=None, session_factory=None) -> bool:
    """Create the tables and fill them with the demo world if the database is empty. Returns True if it seeded."""
    engine = engine or database.engine
    session_factory = session_factory or database.SessionLocal
    database.Base.metadata.create_all(engine)
    if os.getenv("SEED_ON_START", "1") == "0":
        return False
    db = session_factory()
    try:
        if db.query(models.User).count() > 0:
            return False
        import seed_wallet
        seed_wallet.seed(db, n_users=int(os.getenv("SEED_USERS", "1500")))
        return True
    finally:
        db.close()


@asynccontextmanager
async def lifespan(application):
    start_shield()
    start_database()
    yield


def create_app() -> FastAPI:
    """A new application that reuses the wallet's routes, so the original wallet app is never modified."""
    outer = FastAPI(title="upay-trustflow (wallet + Shield + phone app)", version="1.0", lifespan=lifespan)
    outer.add_middleware(CORSMiddleware, allow_origins=os.getenv("CORS_ORIGINS", "*").split(","), allow_methods=["*"], allow_headers=["*"])
    outer.exception_handlers.update(wallet_api.app.exception_handlers)
    outer.router.routes.extend(r for r in wallet_api.app.router.routes if isinstance(r, APIRoute))
    outer.mount("/shield", shield_api.app)          # a mounted app does not run its own start-up, so lifespan() does it
    if DIST.exists():                               # the phone app, last, so that every API route above takes priority
        outer.mount("/", StaticFiles(directory=DIST, html=True), name="web")
    return outer


app = create_app()
