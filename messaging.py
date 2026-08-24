"""Delivery and templates. Under DRY_RUN nothing is sent, everything is logged."""
from flask import current_app

from models import Message, db

INK, GREEN, PAPER, LINE, MUTED = "#1B2A24", "#2F5D45", "#FBFAF7", "#E2E0D8", "#6E7B74"


def _record(channel, recipient, subject, status, detail=""):
    db.session.add(Message(channel=channel, recipient=recipient, subject=subject,
                           status=status, detail=detail))


def send_email(to, subject, html):
    cfg = current_app.config
    to = (to or "").strip()
    if not to:
        _record("email", to, subject, "skipped", "no email address")
        return False
    if cfg["DRY_RUN"] or not cfg["SENDGRID_API_KEY"]:
        _record("email", to, subject, "dry-run")
        current_app.logger.info("DRY_RUN email -> %s : %s", to, subject)
        return True
    try:
        from sendgrid import SendGridAPIClient
        from sendgrid.helpers.mail import Mail

        mail = Mail(from_email=cfg["FROM_EMAIL"], to_emails=to,
                    subject=subject, html_content=html)
        resp = SendGridAPIClient(cfg["SENDGRID_API_KEY"]).send(mail)
        _record("email", to, subject, "sent", f"HTTP {resp.status_code}")
        return True
    except Exception as exc:
        _record("email", to, subject, "failed", str(exc))
        current_app.logger.exception("Delivery failed for %s", to)
        return False


def send_sms(to, text):
    cfg = current_app.config
    if not cfg["SMS_ENABLED"] or not (to or "").strip():
        return False
    if cfg["DRY_RUN"] or not cfg["TWILIO_SID"]:
        _record("sms", to, text[:80], "dry-run")
        return True
    try:
        from twilio.rest import Client

        Client(cfg["TWILIO_SID"], cfg["TWILIO_TOKEN"]).messages.create(
            to=to, from_=cfg["TWILIO_FROM"], body=text)
        _record("sms", to, text[:80], "sent")
        return True
    except Exception as exc:
        _record("sms", to, text[:80], "failed", str(exc))
        return False


# ---------- templates ----------

def _url(token, answer):
    return f"{current_app.config['BASE_URL']}/r/{token}?a={answer}"


def _button(url, label, primary):
    bg = GREEN if primary else "#FFFFFF"
    fg = "#FFFFFF" if primary else INK
    bd = GREEN if primary else LINE
    return (f'<a href="{url}" style="display:inline-block;padding:13px 24px;background:{bg};'
            f'color:{fg};border:1px solid {bd};font-size:16px;text-decoration:none;">{label}</a>')


def shell(group, inner):
    club = current_app.config["CLUB_NAME"]
    return (
        f'<div style="background:{PAPER};padding:26px 14px;font-family:Helvetica,Arial,sans-serif;">'
        f'<div style="max-width:520px;margin:0 auto;background:#FFF;border:1px solid {LINE};">'
        f'<div style="background:{GREEN};padding:16px 26px;color:#FFF;font-family:Georgia,serif;'
        f'font-size:18px;">{club}</div><div style="padding:26px;">{inner}</div>'
        f'<div style="border-top:1px solid {LINE};padding:13px 26px;color:{MUTED};font-size:12px;">'
        f'Questions? {group.organizer_email}</div></div></div>')


def _card(group, session, player, intro, note, buttons):
    when = session.starts_at
    rows = "".join(
        f'<tr><td style="padding:5px 16px 5px 0;color:{MUTED};font-size:12px;letter-spacing:.06em;'
        f'text-transform:uppercase;">{label}</td>'
        f'<td style="padding:5px 0;color:{INK};font-size:16px;">{value}</td></tr>'
        for label, value in (("Date", when.strftime("%A, %B %-d, %Y")),
                             ("Time", when.strftime("%-I:%M %p")),
                             ("Group", group.name)))
    cta = ""
    if buttons:
        cells = "".join(f'<td style="padding-right:10px;">{_button(u, l, p)}</td>'
                        for l, u, p in buttons)
        cta = f'<table cellpadding="0" cellspacing="0"><tr>{cells}</tr></table>'
    return shell(group, (
        f'<p style="margin:0 0 6px;color:{INK};font-size:16px;">Hi {player.first_name},</p>'
        f'<p style="margin:0 0 18px;color:{INK};font-size:16px;line-height:1.5;">{intro}</p>'
        f'<table cellpadding="0" cellspacing="0" style="margin:0 0 22px;">{rows}</table>{cta}'
        f'<p style="margin:20px 0 0;color:{MUTED};font-size:14px;line-height:1.5;">{note}</p>'))


def confirmation(group, session, player, invite, reminder=False):
    note = ("Still no answer from you. Without one, the spot goes to a substitute."
            if reminder else
            "Please answer either way — a spot with no answer is offered to a substitute.")
    html = _card(group, session, player, "You are on the schedule for this session.", note,
                 [("Yes, I will play", _url(invite.token, "yes"), True),
                  ("No, I cannot", _url(invite.token, "no"), False)])
    subject = f"{'Reminder: ' if reminder else ''}Confirm {session.starts_at:%a %b %-d}"
    send_email(player.email, subject, html)
    send_sms(player.phone, f"Tennis {session.starts_at:%a %b %-d}: {_url(invite.token, 'yes')}")


def invitation(group, session, player, invite):
    note = ("You are getting first refusal because you have played the fewest sessions so far."
            if invite.wave == 1 else
            "The spot is open to the whole group — first to answer takes it.")
    html = _card(group, session, player, "A spot has opened up. Want it?", note,
                 [("Yes, I will take it", _url(invite.token, "yes"), True),
                  ("No thanks", _url(invite.token, "no"), False)])
    send_email(player.email, f"Spot open — {session.starts_at:%a %b %-d}", html)
    send_sms(player.phone, f"Tennis spot open {session.starts_at:%a %b %-d}: {_url(invite.token,'yes')}")


def spot_filled(group, session, player):
    html = _card(group, session, player, "The spot for this session has been filled.",
                 "Nothing to do. We will come back to you next time one opens up.", [])
    send_email(player.email, f"Spot filled — {session.starts_at:%a %b %-d}", html)


def lineup(group, session, players):
    items = "".join(f'<li style="margin:0 0 4px;">{p.name}</li>' for p in players)
    html = shell(group, (
        f'<p style="margin:0 0 6px;font-size:16px;color:{INK};">'
        f'Playing {session.starts_at:%A, %B %-d at %-I:%M %p}</p>'
        f'<p style="margin:0 0 16px;font-size:14px;color:{MUTED};">'
        f'{group.courts} courts — {len(players)} players</p>'
        f'<ol style="margin:0;padding-left:20px;font-size:16px;color:{INK};">{items}</ol>'))
    for p in players:
        send_email(p.email, f"Lineup — {session.starts_at:%a %b %-d}", html)


def short_alert(group, session):
    out = ", ".join(
        f"{i.player.name} ({i.status.lower()})"
        for i in session.invites if i.status in ("DECLINED", "EXPIRED"))
    html = shell(group, (
        f'<p style="margin:0 0 12px;font-size:16px;color:{INK};">'
        f'<strong>{len(session.playing)} of {session.needed} players</strong> confirmed for '
        f'{session.starts_at:%A, %B %-d}.</p>'
        f'<p style="margin:0 0 12px;font-size:15px;color:{INK};">Everyone available has been '
        f'asked. This one needs a phone call.</p>'
        f'<p style="margin:0;font-size:14px;color:{MUTED};">Out: {out or "—"}</p>'))
    send_email(group.organizer_email,
               f"Short {session.needed - len(session.playing)} — {group.name}, "
               f"{session.starts_at:%a %b %-d}", html)


def broadcast(group, players, subject, body):
    safe = body.replace("\n", "<br>")
    html = shell(group, f'<div style="font-size:16px;line-height:1.6;color:{INK};">{safe}</div>')
    for p in players:
        send_email(p.email, subject, html)
