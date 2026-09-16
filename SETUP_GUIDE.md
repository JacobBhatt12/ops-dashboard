# 🚀 Thera Web Design — Monthly Agent Setup Guide

Follow these steps to configure the agent for manual runs.

---

## Step 1 — Install Python

Open **Terminal** (press `Cmd + Space`, type "Terminal", hit Enter).

Check if Python is installed:
```
python3 --version
```
If you see `Python 3.x.x` you're good.
If not, go to **python.org/downloads** and install it.

---

## Step 2 — Install Required Packages

In Terminal, from this folder, paste this and press Enter:
```
pip3 install -r requirements.txt
```
Wait for it to finish. You'll see a lot of text — that's normal.

---

## Step 3 — Get Your Hostinger API Key

1. Log in to **hPanel** at hostinger.com
2. Click your profile icon → **Developer Tools** or **API Tokens**
3. Click **Create New Token**, give it a name like `Monthly Agent`
4. Copy the key — you'll only see it once, so paste it somewhere safe

---

## Step 4 — Get Your Gmail App Password

*(This lets the script send email without exposing your main password)*

1. Go to **myaccount.google.com**
2. Click **Security** in the left sidebar
3. Make sure **2-Step Verification is ON** (required)
4. Search for **"App Passwords"** at the top of the page
5. Select App: **Mail** — Select Device: **Mac** → Click **Generate**
6. Copy the 16-character password (spaces don't matter)

---

## Step 5 — Get a Free Google PageSpeed API Key

*(Used for the speed test scores in each report)*

1. Go to **console.cloud.google.com**
2. Sign in with your Google account → Create a project (name it anything)
3. In the search bar at the top, search: `PageSpeed Insights API`
4. Click **Enable**
5. Go to **APIs & Services → Credentials → Create Credentials → API Key**
6. Copy that key

---

## Step 6 — Fill In the Config

1. Copy `.env.example` to a new file named `.env` in this same folder
   *(Right-click → Duplicate, then rename it, or in Terminal: `cp .env.example .env`)*
2. Open `.env` in **TextEdit** or any text editor and fill in every value:

```
HOSTINGER_API_KEY=paste your Hostinger key here
GMAIL_ADDRESS=the Gmail address reports are sent from
GMAIL_APP_PASSWORD=paste your Gmail app password here
PAGESPEED_API_KEY=paste your PageSpeed key here
YOUR_SMS_EMAIL=yournumber@tmomail.net
```

No Twilio needed — texts are sent free via your carrier's email-to-SMS gateway
(e.g. T-Mobile's `@tmomail.net`).

3. Copy `clients.example.json` to `data/clients.json` and replace the example
   entries with your real clients (name, website, contacts). See the "Client
   List" section in `CLAUDE.md` for the exact shape.

4. Save both files. `.env` and `data/` are gitignored, so these never get
   committed if this project is under version control.

---

## Step 7 — Open the Management Dashboard

Double-click `Open Management Dashboard.command`. Your browser will open the
private dashboard at `http://127.0.0.1:8787`.

1. Check the contacts who should receive the report, or click **Select all**.
2. Click **Send management emails**.
3. Keep the dashboard and Terminal window open while the website checks run.

The existing Canva-style Website Care design is used for every selected contact.

---

## Verification Checklist

Before sending reports:

- [ ] `.env` created from `.env.example` with all values filled in
- [ ] `data/clients.json` created from `clients.example.json` with your real clients
- [ ] Dashboard opened and showed the correct client contacts

---

## Troubleshooting

**Gmail auth error** → Double-check your App Password and that 2FA is enabled

**Text not received** → Make sure you're on T-Mobile; if you switched carriers, update `YOUR_SMS_EMAIL` in the config to match your new carrier's gateway

**SSL check fails** → The domain may not support HTTPS — check manually

**Backup shows "Unable to retrieve"** → Your Hostinger plan may be on shared hosting;
the backup API is primarily for VPS plans. Log into hPanel and check manually.

---

## Adding More Clients Later

Just add another entry to the array in `data/clients.json`:

```json
{
    "name": "New Client Name",
    "website": "theirdomain.com",
    "github_repo": null,
    "ga4_property_id": null,
    "contacts": [
        {"name": "First Name", "email": "their@email.com"}
    ]
}
```

Save the file. Done — they'll be included the next time you run the agent.

---

*Built for Thera Web Design · you@example.com*
