# Deploying upay-trustflow (one live link)

The whole demo runs as ONE web service: the phone app, the wallet API and Shield, on one address.
On start-up it fills itself with the synthetic demo world (about 5 seconds), so there is nothing else to set up.

## Run it on your own computer first (same setup as the live one)
```
cd wallet-app
npm run build
cd ..
python -m uvicorn deploy.app:app --port 9000
```
Open http://localhost:9000

## Put it on Render (free)
1. Push this repository to GitHub.
2. Go to https://render.com and sign in with GitHub.
3. Click **New +**, then **Blueprint**, choose the `upay-trustflow` repository, and click **Apply**.
   Render reads `render.yaml` and builds the Dockerfile. The first build takes 5 to 10 minutes.
4. When the service shows **Live**, open its address (it ends in `.onrender.com`).

If Blueprint is not offered: **New +**, **Web Service**, pick the repository, set **Language** to **Docker**, **Instance type** to
**Free**, **Health Check Path** to `/health`, and add the environment variables `PIN_PEPPER` (any long random text),
`DEMO_MODE` = `1` and `SEED_ON_START` = `1`.

## Things to know about the free plan
- The service **sleeps after 15 minutes without visitors**. The first visit afterwards takes about a minute. Open the link a
  minute before a demo or a recording.
- Data is not kept when the service restarts; it is rebuilt on start-up. Use **Reset demo** in the analyst console to start
  fresh before presenting.
- The demo accounts are public: customers use PIN `12345`, the analyst uses `99999`. Do not put real data in this service.

## Settings
| Variable | Meaning | Default |
|---|---|---|
| `PIN_PEPPER` | secret mixed into PIN hashes | random (Blueprint) |
| `DEMO_MODE` | `0` hides the demo tools and the reset button | `1` |
| `SEED_ON_START` | `0` starts with an empty database | `1` |
| `SEED_USERS` | size of the demo world | `1500` |
| `LLM_API_KEY` | optional: lets Shield write warnings with an AI model; without it, fixed Bangla templates are used | none |
