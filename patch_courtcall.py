"""Applique les deux corrections : heure locale, et file d'attente des remplacants."""
import pathlib, sys

ok = True
def edit(path, old, new, label):
    global ok
    p = pathlib.Path(path); s = p.read_text()
    if new in s and old not in s:
        print(f"  deja fait : {label}"); return
    if s.count(old) != 1:
        print(f"  ECHEC ({s.count(old)} occurrences) : {label}"); ok = False; return
    p.write_text(s.replace(old, new)); print(f"  ok : {label}")

print("models.py")
edit("models.py",
"""from datetime import datetime

from flask_sqlalchemy import SQLAlchemy""",
'''import os
from datetime import datetime
from zoneinfo import ZoneInfo

from flask_sqlalchemy import SQLAlchemy


def local_now():
    """Wall-clock time in the club timezone, naive.

    Session times come from the CSV as naive local times, so every comparison
    must use the same clock. Using UTC shifted every send by the offset.
    """
    tz = os.environ.get("TIMEZONE", "America/Chicago")
    return datetime.now(ZoneInfo(tz)).replace(tzinfo=None)''', "local_now()")
edit("models.py", "default=datetime.utcnow, index=True", "default=local_now, index=True", "Message.created_at")
edit("models.py", "default=datetime.utcnow)", "default=local_now)", "Invite.sent_at")

print("config.py")
edit("config.py",
'    WAVE1_HOURS = _int("WAVE1_HOURS", 8)\n    WAVE1_EXTRA = _int("WAVE1_EXTRA", 2)',
'    OFFER_HOURS = _int("OFFER_HOURS", _int("WAVE1_HOURS", 8))\n    INVITE_EXTRA = _int("INVITE_EXTRA", _int("WAVE1_EXTRA", 2))',
"OFFER_HOURS / INVITE_EXTRA")

print("engine.py")
edit("engine.py", "                    Session, db)", "                    Session, db, local_now)", "import local_now")
p = pathlib.Path("engine.py"); s = p.read_text()
n = s.count("datetime.utcnow()")
p.write_text(s.replace("datetime.utcnow()", "local_now()")); print(f"  ok : {n} appels utcnow -> local_now")

s = pathlib.Path("engine.py").read_text()
try:
    i, j = s.index("def fill_spots(session, now=None):"), s.index("def eligible(session):")
except ValueError:
    print("  ECHEC : fill_spots introuvable"); sys.exit(1)
s = s[:i] + '''def fill_spots(session, now=None):
    """Keep a bounded number of substitute invitations open at a time.

    The batch size is gap + INVITE_EXTRA. With INVITE_EXTRA at 0 the club is
    asked strictly one player at a time: when someone declines, or lets an
    invitation go stale, the next name on the fairness list is asked.
    """
    now = now or local_now()
    if now >= session.starts_at - _hours("CUTOFF_HOURS"):
        alert_if_short(session, now)
        return 0

    if session.gap <= 0:
        if len(session.playing) >= session.needed:
            close_offers(session)
        return 0

    for invite in session.invites:
        if (invite.kind == FILL and invite.status == OFFERED
                and now - invite.sent_at >= _hours("OFFER_HOURS")):
            _close(invite, CLOSED, now)

    outstanding = [i for i in session.invites
                   if i.kind == FILL and i.status == OFFERED]
    batch = session.gap + current_app.config["INVITE_EXTRA"]
    room = batch - len(outstanding)
    if room <= 0:
        return 0

    wave = max((i.wave for i in session.invites if i.kind == FILL), default=0) + 1
    candidates = eligible(session)[:room]
    if not candidates:
        if not outstanding:
            alert_if_short(session, now)
        return 0

    for player in candidates:
        _create(session, player, FILL, wave, OFFERED, now)
    return len(candidates)


''' + s[j:]
pathlib.Path("engine.py").write_text(s); print("  ok : file d'attente des remplacants")

edit("engine.py",
'        _close(invite, DECLINED)\n        return "Noted"',
'        _close(invite, DECLINED)\n        fill_spots(session)\n        return "Noted"',
"refus -> suivant immediatement")

print("app.py")
edit("app.py", "                    PLAYING, Session, db)", "                    PLAYING, Session, db, local_now)", "import local_now")
p = pathlib.Path("app.py"); s = p.read_text()
n = s.count("datetime.utcnow()")
p.write_text(s.replace("datetime.utcnow()", "local_now()")); print(f"  ok : {n} appels utcnow -> local_now")
edit("app.py", "count = engine._invite_wave(record, 2, None, local_now())",
     "count = engine.fill_spots(record)", "bouton Request subs")

print("\nOK" if ok else "\nDES ETAPES ONT ECHOUE")
