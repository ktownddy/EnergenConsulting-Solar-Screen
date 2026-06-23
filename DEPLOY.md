# How to Deploy the Snapshot to the Web

> **Note (June 23, 2026):** Updated to a flat folder structure — `snapshot_calc.py` and `finance_math.py` now sit at the root next to `app.py` instead of inside a `src/` folder. This eliminates a common GitHub drag-and-drop failure mode where empty `__init__.py` files get silently dropped.


A step-by-step walkthrough to get the Energen Solar Deal Snapshot hosted online at a public URL, free of charge, using GitHub + Streamlit Community Cloud.

Total time: ~15 minutes start to finish.

---

## What you'll need

- Your GitHub account (you mentioned you have one — sign in with the old email)
- 15 minutes

That's it. No payment, no credit card, no server config.

---

## Step 1 — Sign in to GitHub

1. Go to **https://github.com**
2. If you're not logged in, click **Sign in** and use your existing account credentials.
3. If you can't remember the password, click "Forgot password" — GitHub will email a reset link.

## Step 2 — Create a new repository

1. In the top-right corner of GitHub, click the **+** icon → **New repository**.
2. Repository name: **`energen-solar-snapshot`** (or whatever you'd like — this becomes part of the URL).
3. Description (optional): "Solar deal screening tool for commercial projects."
4. Select **Public** (required for the free Streamlit Cloud tier).
5. **Do NOT** check "Add a README file," "Add .gitignore," or "Choose a license" — we'll provide those.
6. Click **Create repository**.

You'll land on a page that says "Quick setup — if you've done this kind of thing before" with some commands. Leave that page open; you'll come back to it.

## Step 3 — Upload the files

You have two options here. Option A (drag and drop) is simpler if you don't use Git on the command line.

### Option A — Drag and drop (recommended, no terminal needed)

1. On the repo page from Step 2, click the **"uploading an existing file"** link in the middle of the page.
2. In Finder, navigate to your `energen_solar_deal_snapshot` folder.
3. Open it so you see the contents (`app.py`, `requirements.txt`, `src/`, `assets/`, etc.).
4. Select **ALL the files and folders inside** `energen_solar_deal_snapshot/` (Cmd+A) — but NOT the parent folder itself.
5. Drag them onto the GitHub upload area.
6. Wait for the upload to finish (10–30 seconds).
7. At the bottom, in "Commit changes" → leave the default message → click **Commit changes**.

You should now see all your files listed on the GitHub repo page.

### Option B — Git command line (if you prefer)

```bash
cd /Users/Energen/Documents/Claude/Projects/Solar_Deal_Screener/energen_solar_deal_snapshot
git init
git add .
git commit -m "Initial commit"
git branch -M main
git remote add origin https://github.com/<your-username>/energen-solar-snapshot.git
git push -u origin main
```

## Step 4 — Connect to Streamlit Community Cloud

1. Go to **https://share.streamlit.io**
2. Sign in **with GitHub** (top-right). This authorizes Streamlit Cloud to read your public repos.
3. Click **New app** (or **Deploy an app**).
4. You should see a form with these fields:
   - **Repository:** Pick `<your-username>/energen-solar-snapshot` from the dropdown.
   - **Branch:** `main` (the default).
   - **Main file path:** `app.py`
   - **App URL (optional):** You can customize this — e.g., `energen-snapshot`. The full URL becomes `energen-snapshot.streamlit.app`.
5. Click **Deploy**.
6. Wait 2–5 minutes while Streamlit Cloud builds the app (installs dependencies, starts the server). You'll see logs streaming.
7. When it's done, you'll see "Your app is live!" and a button to open it.

## Step 5 — Test it

Open the URL. You should see:
- The dark navy Energen-branded header at the top
- All the same controls and outputs as the local version
- Same calc engine, same results

Try a quick test case to make sure everything works:
- Customer-owned, 1 MW rooftop, $2.50/Wdc, customer rate $0.12/kWh
- Check that the OBBBA gate, tax credit Q&A, and depreciation toggle all behave correctly
- Toggle senior debt on/off to confirm DSCR appears/disappears

## Step 6 — Share or link from your Netlify site

Once it's live, you have a public URL you can:

- **Email to a prospect:** "Run our quick screen here: https://energen-snapshot.streamlit.app"
- **Link from your existing Netlify index.html:** I can write a styled button/link snippet you can paste when you're ready. Just say the word.
- **Embed in your website with an iframe** (more advanced, optional): wraps the tool inside an iframe on a page of energenconsulting.com.

---

## When to upgrade off the free tier

Streamlit Community Cloud's free tier has two limitations to know about:

1. **The app goes to sleep after ~7 days of inactivity.** When someone visits a sleeping app, they wait ~15 seconds for it to wake up. Fine for occasional internal use; not great for high-traffic customer-facing.
2. **The URL is `<your-name>.streamlit.app`** — not your own domain.

When you're ready to upgrade, two paths:

- **Streamlit Teams** (~$20/mo): private repos allowed, no sleep, custom domain optional.
- **Render** ($7/mo) or **Fly.io** ($5/mo): host the same Streamlit app on a server you control. Custom subdomain like `snapshot.energenconsulting.com` is straightforward. Same code; just different host. I can walk you through this if/when you want to migrate.

For now, the free Streamlit Cloud tier is the right call. Get it live, see how it feels, then upgrade if traffic justifies.

---

## If anything goes wrong

Common issues and fixes:

| Issue | Fix |
|---|---|
| Streamlit Cloud says "App build failed" | Check the logs. Most likely a missing file. Make sure `requirements.txt`, `app.py`, `runtime.txt`, and the entire `src/` folder were uploaded. |
| App loads but the brand header looks broken | Likely a CSS issue. Send me a screenshot and I'll fix the styling. |
| "ModuleNotFoundError" in logs | A required package isn't in `requirements.txt`. Send me the error and I'll add it. |
| App is "stuck" loading after deploy | Streamlit Cloud can be slow on first build (up to 5 minutes). Give it time. If it's still stuck after 10 minutes, click "Reboot" in the Streamlit Cloud dashboard. |
| Repo upload was missing files | Re-do the drag-and-drop. GitHub's UI sometimes drops sub-folders silently — confirm `src/`, `assets/`, and `.streamlit/` all uploaded by clicking into them on the repo page. |

If you get stuck on any step, take a screenshot of where you are and let me know.
