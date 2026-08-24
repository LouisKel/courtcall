# CourtCall

Scheduling and confirmation for a country club's PCT tennis groups.
Flask + SQLite, deployable on Replit as a single project.

New here? Follow **SETUP.md** for the step-by-step deployment guide.

## The model

A PCT group has a roster (17 players for the Saturday 9am Drill) and a fixed requirement per
date (8 players, 2 courts). Each week some of the group is scheduled and the rest are free:
**the substitute pool is the group members who are not on that week's sheet** — not a
designated backup per player. The system reasons in terms of a headcount to reach, not
one-for-one replacement.

The organiser imports the season grid — a CSV export of the Excel file they already keep —
and never touches it again. Players create no account: they click a link in an email.

## How a session unfolds

| When | What happens |
|---|---|
| T-48h | Confirmation request to the scheduled players, *Yes* / *No* buttons. |
| T-36h | Reminder to anyone who has not answered. |
| T-24h | No answer means the spot is released. |
| Spot open, wave 1 | Invitation to the least-played players of the season, 8 hours of priority. |
| Spot open, wave 2 | Invitation to the whole group, first to answer takes it. |
| Spot taken | Everyone else gets a "spot filled" note and is never chased again. |
| T-14h | Final lineup to the confirmed players. |
| T-3h | Still short: alert to the organiser. |

Nobody is asked twice for the same date, and nobody is asked who is already playing in
another group that day.

## CSV formats

**Players** — `name, email, phone`. Re-importing updates existing players without
duplicating them and without clearing fields you left blank.

**Season grid** — the club's current format, unchanged:

```
player,6/6/2026,6/13/2026,6/20/2026,...
Amit Singh,,1,1,...
Charles Wollensak,1,,1,...
```

Row 1 holds the dates from column B onward. Column A holds the name, spelled exactly as in
the player directory. A cell of `1` means that player is on. `Total` columns are ignored,
and a week with no `1` at all (July 4) creates no session.

Re-importing a corrected grid is safe: sessions that have already gone out are never
rewritten. A new season is simply a new CSV.

## Architecture

| File | Role |
|---|---|
| `app.py` | Flask factory, routes, APScheduler startup |
| `engine.py` | engine: confirmations, chasing, waves, lineup, responses |
| `models.py` | SQLAlchemy schema and state machine |
| `messaging.py` | SendGrid / Twilio delivery and email templates |
| `importer.py` | CSV reading |
| `config.py` | configuration from environment variables |

**Request states.** `kind = SLOT` (scheduled player): `PENDING` → `CONFIRMED`, `DECLINED`
or `EXPIRED`. `kind = FILL` (substitute): `OFFERED` → `CLAIMED`, `DECLINED` or `CLOSED`.
No terminal state is reversible by the player: a change of mind goes through the organiser,
deliberately.

**Double-booking prevention.** `engine.LOCK` serialises the hourly cycle against player
clicks, and the headcount is recounted after the lock is acquired. Two players claiming the
same spot in the same second are separated cleanly: the second sees "Just missed it". This
assumes a single process, which is why `.replit` pins `--workers 1`. Moving to several
workers without replacing the lock with a database-level lock would break the guarantee.

## Tests

```
python smoke_test.py
```

Runs a full scenario against the real grid: import, 8 confirmations sent, 6 accepted,
2 declined, wave 1 triggered, least-played player asked first, both spots filled, remaining
offer closed, a late claim rejected, lineup sent. 19 assertions, all in dry-run mode.

## Known limits

- A claim accepted after the lineup has gone out does not trigger a second lineup email.
- `messaging` records the log row then sends: a SendGrid failure is stored as `failed` while
  the request stays open, which is the intended behaviour.
- SQLite is comfortable at this volume; moving to Postgres is a `DATABASE_URL` change with
  no code edits.
- The timezone comes from `TIMEZONE`. Set it wrong and every send shifts with no visible
  error.
