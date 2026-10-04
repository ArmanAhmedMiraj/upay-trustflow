# Demo video script (about 4 to 5 minutes)

Before you record: open the live link a minute early so the service is awake, log in as the **Fraud analyst**, and press
**Reset demo** (two clicks). Use two browser windows side by side: a normal one for the customer and a private one for the analyst.

## 0:00 The problem (20 seconds)
Say: "In mobile money, the biggest fraud is not hacking. The customer is talked into sending the money themselves, with the
correct PIN on their own phone, so normal security sees nothing wrong. Our system, upay Shield, stops that at the moment of sending."
Show: the login screen of the app.

## 0:20 Everyday payments stay smooth (25 seconds)
Do: log in as **Rahim**. Send Money, `01711000002`, `1000`, Continue.
Say: "Rahim pays his mother. Shield checks 23 signals in about 4 milliseconds and finds nothing, so there is no friction."
Show: the green "No risk signs found", then send with PIN 12345.

## 0:45 The scam (90 seconds)
Do: Home, **Demo tools**, **Drop SMS**, close. Open **Messages**.
Say: "A scammer sends a fake 'money received' SMS and phones Rahim asking him to return the money."
Show: the red "Not from upay!" warning on the message.
Do: Send Money, `01711999999`, `5000`, tick "I'm on a phone call", Continue.
Say: "Shield shows a 100 percent risk before the PIN. The key reason is a verified fact: the SMS claims money arrived, but the
upay ledger shows no such credit. Only upay can check that. The other reasons are learned patterns: a brand-new wallet that
received money from twelve strangers today."
Do: open "Why am I seeing this?", then tap the language button on the home screen later to show the Bangla warning (or have it ready).
Do: "Hold my money for 30 minutes", PIN 12345.
Say: "The money leaves Rahim's balance but the scammer does not get it. Rahim can cancel at any time."
Show: the countdown. Leave it running.

## 2:15 The analyst (45 seconds)
Do: in the private window, log in as **Fraud analyst**.
Say: "A fraud analyst sees the held case with the reasons, in plain words. They can approve or reject."
Do: type a short note and press **Reject**.
Do: back in Rahim's window, refresh: his balance is back.
Say: "Every taka is back. Shield never blocks money on its own: the customer can cancel, an analyst decides, and an
unanswered hold is released when its time is up."

## 3:00 The safety questions and the network (30 seconds)
Do: log in as **Nusrat**, Send Money to `01711000007` with an amount that the checker shows lands in the question tier
(run `python simulator/check_demo_scenarios.py` beforehand), answer Yes to the first question.
Say: "When the risk is in the middle, Shield asks two short questions in Bangla. A 'yes' raises the risk; a 'no' can only lower
it a little, because victims are coached to say no."
Optional: report `01711999998` from a few accounts and show the risk rising for the next sender.

## 3:30 The impact and the honesty (30 seconds)
Do: analyst, **Impact** tab.
Say: "The dashboard measures what customers actually did after a warning, in taka. Below it are the offline results on synthetic
data where the truth is known: about 72 percent of fraud caught while disturbing 0.2 percent of genuine transfers. These prove
the method; the next step is shadow-mode validation on governed upay data."
Say: "Known limits are in the report: a calm fraudster using an old account can slip through, and wallets with no history look
risky. Agent cash forecasting is designed as the next module."

## 4:00 Module 2: agent cash (45 seconds, if time allows)
Do: analyst console, **Agents** tab. Click *Festival rush*, then *A normal day*.
Say: "The second module keeps agents stocked. On a normal day every agent is green. In the festival rush, all 120 turn red, and the
system says who runs out, when, and how much cash to bring."
Do: click an agent, show the chart and the Bangla message. Open a second window as **Agent Babul** and tap **Ask upay to bring cash**,
then **Dispatch** it in the console.
Say: "The agent gets the same message in Bangla on their phone and can ask for cash with one tap. We tested it against copying last
week's numbers: that approach turns away 26 percent of demand, ours under 1 percent, with the same average cash. It costs more
refills, and on quiet days it is no better."

## Tips
- Keep your voice calm and slow. Show the screen, not your face.
- If anything shows an unexpected tier, say so: the time of day changes the score, and that is part of the design.
- Record in one take; if you fail, press Reset demo and start again.
