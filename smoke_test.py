"""End-to-end test: import, cycle, decline, cascade, claim."""
import io, os, tempfile
os.environ.update(DRY_RUN="true", SCHEDULER_ENABLED="false", ADMIN_PASSWORD="",
                  BASE_URL="http://localhost:5000",
                  DATABASE_URL="sqlite:///" + tempfile.mktemp(suffix=".db"))

import app as application
import engine, importer
from models import *

app = application.app
ok = lambda c, m: print(("PASS  " if c else "FAIL  ") + m) or c

with app.app_context():
    class F:
        def __init__(self, path): self.data = open(path, "rb").read()
        def read(self): return self.data

    created, updated, errs = importer.import_players(F("sample_players.csv"))
    ok(created == 17 and not errs, f"player directory imported: {created} players")

    for p in Player.query.all():
        p.email = p.name.lower().replace(" ", ".") + "@example.com"
    db.session.commit()

    group = Group.query.first()
    group.organizer_email = "pro@example.com"
    db.session.commit()
    counts, warns = importer.import_schedule(F("sample_schedule.csv"), group, 2026, "09:00")
    ok(counts["sessions"] == 13, f"sessions created: {counts['sessions']} (July 4 skipped)")
    ok(counts["assignments"] == 104, f"assignments: {counts['assignments']}")
    ok(len(group.roster) == 17, f"group roster: {len(group.roster)}")

    from datetime import datetime, timedelta
    now = local_now()
    s = Session.query.filter(Session.starts_at > now).order_by(Session.starts_at).first()
    s.starts_at = now + timedelta(hours=47)
    db.session.commit()
    ok(len(s.scheduled) == 8, f"8 players scheduled on the test session: {len(s.scheduled)}")

    print(f"      (test session: {s.starts_at:%a %b %-d})")
    engine.run_cycle()
    ok(len(s.invites) == 8, f"confirmations sent: {len(s.invites)}")
    ok(all(i.status == PENDING for i in s.invites), "all PENDING")

    for i in s.invites[:6]:
        engine.respond(i.token, "yes")
    ok(len(s.playing) == 6, f"6 confirmations recorded: {len(s.playing)}")

    expected = engine.eligible(s)[0]
    engine.respond(s.invites[6].token, "no")
    fills = [i for i in s.invites if i.kind == FILL]
    ok(len(fills) == 3, f"wave 1: {len(fills)} invitations (1 spot + buffer of 2)")
    ok(fills[0].player_id == expected.id,
       f"least-played player asked first: {fills[0].player.name}")
    ok(not {i.player_id for i in fills} & {r.player_id for r in s.scheduled},
       "no substitute invited who was already on the roster")

    engine.respond(s.invites[7].token, "no")
    outstanding = [i for i in s.invites if i.kind == FILL and i.status == "OFFERED"]
    ok(len(outstanding) == s.gap + app.config["INVITE_EXTRA"],
       f"outstanding invitations track the gap: {len(outstanding)}")

    engine.respond(fills[0].token, "yes")
    ok(len(s.playing) == 7, f"1 spot filled: {len(s.playing)}/8")
    engine.respond(fills[1].token, "yes")
    ok(len(s.playing) == 8, f"roster complete: {len(s.playing)}/8")

    closed = [i for i in fills if i.status == CLOSED]
    ok(len(closed) == 1, f"remaining offer closed automatically: {len(closed)}")

    third = engine.respond(fills[2].token, "yes")
    ok(third[0] == "This spot is closed", f"late claim rejected: {third[0]}")

    ok(s.open_spots == 0 and s.gap == 0, "no open spots")

    s.starts_at = now + timedelta(hours=13)
    db.session.commit()
    ok(engine.day_of_lineup(s), "lineup sent")
    ok(not engine.day_of_lineup(s), "lineup not sent twice")

    # one-at-a-time mode: INVITE_EXTRA = 0 means a single open invitation
    app.config["INVITE_EXTRA"] = 0
    s2 = Session.query.filter(Session.id != s.id).order_by(Session.starts_at).first()
    s2.starts_at = now + timedelta(hours=47)
    db.session.commit()
    engine.open_confirmations(s2)
    db.session.commit()
    for i in s2.invites[:7]:
        engine.respond(i.token, "yes")
    engine.respond(s2.invites[7].token, "no")
    offers = [i for i in s2.invites if i.kind == FILL and i.status == "OFFERED"]
    ok(len(offers) == 1, f"one-at-a-time: a single invitation is open ({len(offers)})")

    first_sub = offers[0]
    engine.respond(first_sub.token, "no")
    offers = [i for i in s2.invites if i.kind == FILL and i.status == "OFFERED"]
    ok(len(offers) == 1 and offers[0].id != first_sub.id,
       "a decline moves the invitation to the next name, not to everyone")

    sent = Message.query.count()
    print(f"\n{sent} messages logged (dry run, nothing actually sent)")
