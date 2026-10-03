# upay Wallet (Concept): customer phone app

A React web app that works like a phone app: it fits a phone screen, installs to the home screen, and on a laptop sits in a
phone-shaped frame. It talks to the wallet API in `../wallet-api`. All data is synthetic.

## Run it
```
npm install        # once
npm test           # runs the app tests
npm run dev        # starts the app at http://localhost:5173
```
Needs Node.js 22.22 or newer (or 24.15+). The wallet API must be running on port 8000, and Shield on port 8001 for the live risk meter.
Copy `.env.example` to `.env` to change the wallet address (`VITE_WALLET_API`) or to hide the demo tools (`VITE_DEMO=0`).

## Screens
Login / create account · Home (balance, recent activity) · **Send money** with the live security-risk meter, Bangla warnings,
safety-check questions and PIN · **Hold screen** with a 30-minute countdown and a cancel button · Messages (fake "money
received" texts are flagged) · History · Add money · Cash out · Report a number · Demo tools (plant a fake SMS, skip the wait).
Everything is in English and Bangla.

## Install on a phone
Build with `npm run build` and serve the `dist` folder over HTTPS (the deployment step does this). Open the link on the phone and
choose "Add to Home Screen". The app opens full screen, with its own icon.
