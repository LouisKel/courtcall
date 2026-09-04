"""Engine: opening confirmations, chasing, substitute waves, lineup."""
import secrets
import threading
from datetime import datetime, timedelta

from flask import current_app
from sqlalchemy import func

import messaging
from models import (CLAIMED, CLOSED, CONFIRMED, DECLINED, EXPIRED, FILL, OFFERED,
                    PENDING, PLAYING, SLOT, Group, Invite, Message, Player, Roster,
                    Session, db, local_now)

# Replit runs a single process, so an in-memory lock is enough to serialise
# the hourly cycle against player clicks.
LOCK = threading.RLock()


def _hours(name):
    return timedelta(hours=current_app.config[name])


def run_cycle(now=None):
    """Entry point for the hourly trigger."""
    now = now or local_now()
    touched = 0
    with LOCK:
        horizon = now + _hours("CONFIRM_HOURS_BEFORE")
        sessions = (Session.query.join(Group)
                    .filter(Group.active.is_(True), Session.starts_at > now,
                            Session.starts_at <= horizon)
                    .order_by(Session.starts_at).all())
        for session in sessions:
            open_confirmations(session, now)
            chase(session, now)
            fill_spots(session, now)
            day_of_lineup(session, now)
            touched += 1
        db.session.commit()
    return touched


# ---------- 1. confirmations ----------

def open_confirmations(session, now=None):
    now = now or local_now()
    asked = {i.player_id for i in session.invites}
    for row in session.scheduled:
        if row.player_id in asked:
            continue
        if not row.player.contactable:
            db.session.add(Message(channel="email", recipient=row.player.name,
                                   subject="skipped", status="skipped",
                                   detail="inactive player or no email"))
            continue
        _create(session, row.player, SLOT, 0, PENDING, now)


def _create(session, player, kind, wave, status, now):
    invite = Invite(session_id=session.id, player_id=player.id, kind=kind, wave=wave,
                    status=status, token=secrets.token_urlsafe(24), sent_at=now)
    db.session.add(invite)
    db.session.flush()
    session.invites.append(invite)
    group = session.group
    if kind == SLOT:
        messaging.confirmation(group, session, player, invite)
    else:
        messaging.invitation(group, session, player, invite)
    return invite


# ---------- 2. reminders and expiry ----------

def chase(session, now=None):
    now = now or local_now()
    cutoff = session.starts_at - _hours("CUTOFF_HOURS")
    for invite in session.invites:
        if invite.status == PENDING:
            expiry = min(invite.sent_at + _hours("EXPIRE_HOURS"), cutoff)
            if now >= expiry:
                _close(invite, EXPIRED, now)
                continue
            if not invite.reminded_at and now >= invite.sent_at + _hours("REMINDER_HOURS"):
                messaging.confirmation(session.group, session, invite.player, invite, reminder=True)
                invite.reminded_at = now
        elif invite.status == OFFERED and now >= cutoff:
            _close(invite, CLOSED, now)


def _close(invite, status, now=None):
    invite.status = status
    invite.responded_at = now or local_now()


# ---------- 3. filling open spots ----------

def fill_spots(session, now=None):
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


def eligible(session):
    """Group members free that day, ranked by fairness."""
    scheduled = {r.player_id for r in session.scheduled}
    asked = {i.player_id for i in session.invites}
    busy = _busy_same_day(session)

    load = dict(db.session.query(Invite.player_id, func.count(Invite.id))
                .join(Session).filter(Session.group_id == session.group_id,
                                      Invite.status.in_(PLAYING))
                .group_by(Invite.player_id).all())
    planned = dict(db.session.query(Roster.player_id, func.count(Roster.id))
                   .join(Session).filter(Session.group_id == session.group_id)
                   .group_by(Roster.player_id).all())

    pool = [p for p in session.group.roster
            if p.id not in scheduled and p.id not in asked
            and p.id not in busy and p.contactable]
    return sorted(pool, key=lambda p: (load.get(p.id, 0), planned.get(p.id, 0), p.name))


def _busy_same_day(session):
    day = session.starts_at.date()
    start = datetime.combine(day, datetime.min.time())
    rows = (db.session.query(Invite.player_id).join(Session)
            .filter(Session.starts_at >= start, Session.starts_at < start + timedelta(days=1),
                    Session.id != session.id,
                    Invite.status.in_((PENDING, CONFIRMED, CLAIMED))).all())
    return {r[0] for r in rows}


def close_offers(session):
    for invite in session.invites:
        if invite.kind == FILL and invite.status == OFFERED:
            _close(invite, CLOSED)
            messaging.spot_filled(session.group, session, invite.player)


# ---------- 4. lineup and alert ----------

def day_of_lineup(session, now=None):
    now = now or local_now()
    if session.lineup_sent_at or now < session.starts_at - _hours("LINEUP_HOURS_BEFORE"):
        return False
    if session.pending:
        return False
    players = [i.player for i in session.playing]
    if not players:
        return False
    messaging.lineup(session.group, session, players)
    session.lineup_sent_at = now
    return True


def alert_if_short(session, now=None):
    now = now or local_now()
    if session.alerted_at or len(session.playing) >= session.needed:
        return False
    if not session.group.organizer_email:
        return False
    messaging.short_alert(session.group, session)
    session.alerted_at = now
    return True


# ---------- 5. player response ----------

def respond(token, answer):
    """Returns (title, message). Serialised: this is where double-booking is prevented."""
    with LOCK:
        invite = Invite.query.filter_by(token=token).first()
        if not invite:
            return "Link not recognised", "This link is no longer valid. Contact the organiser."

        session, player = invite.session, invite.player
        when = session.starts_at.strftime("%A, %B %-d at %-I:%M %p")

        if answer not in ("yes", "no"):
            return "Answer missing", "Use one of the two buttons in the email."

        if invite.kind == SLOT:
            result = _respond_slot(invite, session, answer, when)
        else:
            result = _respond_fill(invite, session, answer, when)
        db.session.commit()
        return result


def _respond_slot(invite, session, answer, when):
    if invite.status != PENDING:
        label = {CONFIRMED: "playing", DECLINED: "not playing",
                 EXPIRED: "passed to a substitute"}.get(invite.status, invite.status)
        return "Already recorded", f"Your answer for {when} is <strong>{label}</strong>."

    if answer == "yes":
        _close(invite, CONFIRMED)
        return "You are in", f"See you {when}."

    _close(invite, DECLINED)
    fill_spots(session)
    return "Thanks for telling us", f"You are off the sheet for {when}. We are finding a sub."


def _respond_fill(invite, session, answer, when):
    if invite.status == CLAIMED:
        return "You already have this spot", f"See you {when}."
    if invite.status != OFFERED:
        return "This spot is closed", "It has been filled or the session has started."

    if answer == "no":
        _close(invite, DECLINED)
        fill_spots(session)
        return "Noted", "We will offer it to someone else."

    if len(session.playing) >= session.needed:
        _close(invite, CLOSED)
        return "Just missed it", "Someone claimed the last spot a moment ago."

    _close(invite, CLAIMED)
    if len(session.playing) >= session.needed:
        close_offers(session)
    return "The spot is yours", f"You are playing {when}."
