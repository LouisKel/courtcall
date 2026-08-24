# Deploying CourtCall on Replit

A complete walkthrough, from an empty account to a system the club can rely on.
Budget about 45 minutes for steps 1-7, and a separate sitting for step 8.

Work through it in order. Steps 1-7 send no email at all, so nothing can reach a real
player by accident while you are still setting up.

---

## Step 0 — What you need first

| Item | Notes |
|---|---|
| A Replit account | The free plan is fine for setup. Step 10 explains why it is not enough for production. |
| The season grid as CSV | In Excel or Google Sheets: File → Save As / Download → CSV. |
| Player email addresses | The grid does not contain them. Collect them before step 6. |
| A SendGrid account | Free tier, 100 emails/day. Only needed at step 8. |
| An email address the club controls | For the SendGrid sender identity. A personal Gmail works for testing, but the club's own domain looks far better to members. |

---

## Step 1 — Create the Repl

1. Go to replit.com and click **Create Repl**.
2. Choose the **Python** template.
3. Name it `courtcall`.
4. Click **Create Repl**.

You land in an editor with a single `main.py`. You can delete that file — this project uses
`app.py` as its entry point.

---

## Step 2 — Add the project files

Drag the whole `courtcall` folder into the Replit file pane, or upload the files one by one.

Two things people get wrong here:

- `templates/` and `static/` must stay **folders**, not flattened. Flask will not find the
  pages otherwise.
- Files beginning with a dot (`.replit`, `.env.example`, `.gitignore`) are hidden by
  default. Turn on **Show hidden files** in the file pane's three-dot menu to confirm
  `.replit` uploaded — without it, Replit will not know how to start the app.

Your tree should read:

```
app.py  config.py  engine.py  importer.py  messaging.py  models.py
smoke_test.py  requirements.txt  README.md  SETUP.md
sample_players.csv  sample_schedule.csv
.replit  .env.example  .gitignore
templates/   (9 .html files)
static/style.css
```

---

## Step 3 — Install the dependencies

Open the **Shell** tab (not the Console) and run:

```bash
pip install -r requirements.txt
```

Wait for it to finish. Then confirm the engine works before touching any configuration:

```bash
python smoke_test.py
```

You should see 19 lines starting with `PASS`. If they all pass, the logic is sound in your
environment and anything that goes wrong later is configuration, not code. That distinction
will save you a lot of time.

---

## Step 4 — Set the secrets

Open the **Secrets** tab (padlock icon) and add these keys one at a time. Secrets are
environment variables that never appear in your code or your Git history.

| Key | Value | Why |
|---|---|---|
| `SECRET_KEY` | any long random string | Signs the login session cookie. |
| `ADMIN_PASSWORD` | a password you choose | Protects the dashboard. **Leave this blank and anyone with the URL can read the club's roster and email every member.** |
| `CLUB_NAME` | e.g. `Country Club Tennis League` | Appears in the header of every email. |
| `DRY_RUN` | `true` | Nothing is sent while this is true. |
| `TIMEZONE` | `America/Chicago` | Wisconsin. Get this wrong and every send shifts by hours. |
| `SCHEDULER_ENABLED` | `true` | Runs the hourly cycle. |

Leave `BASE_URL`, `SENDGRID_API_KEY` and `FROM_EMAIL` for now. `.env.example` lists every
available key with its default if you want to tune the timing later.

---

## Step 5 — First run and the BASE_URL

1. Click **Run**. A web preview opens with a sign-in page.
2. Copy the public URL. It looks like `https://courtcall.yourname.repl.co`, and it is shown
   above the preview or via the **New tab** icon.
3. Back in **Secrets**, add:

   | Key | Value |
   |---|---|
   | `BASE_URL` | the URL you just copied, **no trailing slash** |

4. Stop and re-run the Repl so the new secret is picked up.

This is the single most common setup failure. `BASE_URL` is what the Yes/No buttons in every
email point at. If it is wrong, missing, or has a trailing slash, players click and land
nowhere — and you will not notice until real emails are going out.

Sign in with your `ADMIN_PASSWORD`. You should see an empty **Upcoming sessions** page and
an amber banner telling you dry-run mode is on. That banner is your safety net; it stays
until step 9.

---

## Step 6 — Import the club's data

Go to **Upload**. There are two forms and the order matters, because the grid links to
players by name.

**First, the players.** Upload `sample_players.csv` to see the shape, or your own file with
the columns `name, email, phone`. You should get a confirmation like "17 player(s) created".

**Then, the season grid.** Pick the group, set the year, upload `sample_schedule.csv` or the
club's own export. You should get "13 session(s), 104 assignment(s)".

If any warnings appear saying *player not in directory*, the grid spells a name differently
from the player list. Fix the spelling in one of the two files and re-import — re-importing
is safe and will not duplicate anything.

Now open **Players** and fill in every email address. Missing ones are highlighted in yellow.
A player with no email is skipped silently by the engine, which means a spot that quietly
never gets filled. This step is worth doing carefully.

---

## Step 7 — Rehearse the whole thing with nothing being sent

Still in dry-run. This is where you find out whether the system behaves before a single
player is involved.

1. On **Sessions**, open the nearest upcoming session.
2. Click **Send confirmations**. Nothing leaves the app.
3. Open **Log**. You should see one row per scheduled player, marked `dry-run`, with the
   subject line the player would have received.
4. Go back to the session. Every player now shows as `pending`.
5. To test the response flow end to end, you need a real token. In the **Shell**:

   ```bash
   python -c "
   from app import app
   from models import Invite
   with app.app_context():
       i = Invite.query.first()
       print(f'{i.player.name}: /r/{i.token}?a=no')
   "
   ```

   Paste that path onto the end of your `BASE_URL` and open it in a browser. You should get
   a "Thanks for telling us" page, and back on the session the player flips to `declined`
   while substitute invitations appear for the least-played members of the group.

6. Click through **Request subs**, **Remind pending** and **Send lineup** to see each email
   land in the log.

When you are done rehearsing, reset the data so the club starts clean:

```bash
rm courtcall.db
```

Re-run the Repl and redo step 6. This wipes every request and message while leaving your
CSVs untouched.

---

## Step 8 — SendGrid

This is the step where people get stuck, and always at the same place: SendGrid will not
send from an address it has not verified.

1. Create a free account at sendgrid.com.
2. **Settings → Sender Authentication**. Choose one:
   - *Single Sender Verification* — quick. Enter one address, click the link SendGrid emails
     you. Good enough to start.
   - *Domain Authentication* — better. Requires adding DNS records for the club's domain,
     but messages then arrive as the club rather than as an unfamiliar address, and far
     fewer land in spam. Worth doing before the club's members ever see it.
3. **Settings → API Keys → Create API Key**. Choose *Restricted Access* and enable **Mail
   Send** only. Copy the key immediately — SendGrid shows it exactly once.
4. Back in Replit **Secrets**:

   | Key | Value |
   |---|---|
   | `SENDGRID_API_KEY` | the key you just copied |
   | `FROM_EMAIL` | **the address you verified in step 8.2, character for character** |

A mismatch between `FROM_EMAIL` and the verified sender is the cause of almost every
"why is nothing arriving" problem. The failure is recorded in **Log** with the SendGrid error
attached, so check there first.

---

## Step 9 — Going live

1. Set `DRY_RUN` to `false` in **Secrets**.
2. Re-run the Repl.
3. Before anything else: temporarily set your own email on one player in **Players**, run a
   cycle, and confirm the email arrives, looks right on a phone, and that both buttons work.
4. Put the real address back.

The amber banner on the dashboard disappears once dry-run is off. If you still see it, the
secret did not take — re-run the Repl.

For the first two weeks, keep the manual email running in parallel. If the system misses
something you will know immediately, and the club will not have felt it.

---

## Step 10 — Keeping it awake

**This is the real operational constraint of hosting on Replit, and it deserves a decision
before you promise anything to the club.**

On the free plan a Repl sleeps after a period of inactivity. When it sleeps, APScheduler
stops with it, and the confirmation emails simply do not go out. Nobody gets an error — the
session just quietly arrives with nobody confirmed.

Two ways to prevent it:

- **Always On** — a paid Replit toggle that keeps the Repl running.
- **Reserved VM Deployment** — Replit's production hosting. More predictable, and the
  deployment configuration is already in `.replit`.

Whichever you choose, verify it afterwards: leave the app untouched overnight, then open
`BASE_URL/healthz` in the morning. An immediate JSON response means it stayed up. A slow
cold-start page means it slept, and the scheduler slept with it.

---

## Step 11 — Each new season

1. Export the new grid as CSV.
2. **Upload** → import the schedule against the same group.
3. Check **Players** for anyone who has joined or left; set `active` off rather than
   deleting, so past seasons keep their history.

Nothing else. Old sessions stay in the database as the club's record.

---

## Step 12 — When something looks wrong

| Symptom | Where to look |
|---|---|
| Buttons in emails lead nowhere | `BASE_URL` is wrong or has a trailing slash. Fix it and re-run. |
| No emails arriving, log shows `failed` | Read the error in **Log**. Almost always `FROM_EMAIL` not matching the verified sender. |
| No emails, log shows `dry-run` | `DRY_RUN` is still `true`. |
| Log shows `skipped` | That player has no email address. Fill it in under **Players**. |
| Nothing happens automatically | The Repl is asleep (step 10) or `SCHEDULER_ENABLED` is `false`. |
| Sends arrive at odd hours | `TIMEZONE` is wrong. |
| A grid import creates no sessions | Row 1 dates are not recognised. Use `6/6/2026` or `2026-06-06`, and make sure they are in row 1 from column B onward. |
| Two players got the same spot | Should be impossible with `--workers 1`. If `.replit` has been edited to use more workers, that is the cause. |

The **Log** page answers most of these on its own. Read it before changing anything.

---

## Step 13 — Handing it over

Two things make the difference between a project that survives and one that dies when you
move on.

**Put it in the club's account, not yours.** Create the Repl and the SendGrid account under
an address the club controls, then add yourself as a collaborator. A system that lives in a
student account is a system with an expiry date, and the club will sense that.

**Leave a one-page sheet for the organiser**, in plain English: how to read the dashboard,
what to do when a "short" alert arrives, how to upload next season. Not this document — this
one is for whoever maintains the code. Those are two different readers.
