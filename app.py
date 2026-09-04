"""CourtCall - scheduling and confirmation for PCT sessions."""
import os
from datetime import datetime, timedelta
from functools import wraps

from flask import (Flask, flash, redirect, render_template, request, session as flask_session,
                   url_for)

import engine
import importer
import messaging
from config import Config
from models import (CLAIMED, CONFIRMED, DECLINED, EXPIRED, Group, Invite, Message, Player,
                    PLAYING, Session, db, local_now)


def create_app():
    app = Flask(__name__)
    app.config.from_object(Config)
    db.init_app(app)

    with app.app_context():
        db.create_all()
        _seed_group()

    _register_routes(app)
    if app.config["SCHEDULER_ENABLED"]:
        _start_scheduler(app)
    return app


def _seed_group():
    if not Group.query.first():
        db.session.add(Group(name="Saturday 9am Drill", players_needed=8, courts=2,
                             start_time="09:00", organizer_email=""))
        db.session.commit()


def _start_scheduler(app):
    from apscheduler.schedulers.background import BackgroundScheduler

    def job():
        with app.app_context():
            count = engine.run_cycle()
            app.logger.info("cycle finished, %s session(s) reviewed", count)

    scheduler = BackgroundScheduler(timezone=app.config["TIMEZONE"], daemon=True)
    scheduler.add_job(job, "interval", hours=1, id="cycle", replace_existing=True,
                      next_run_time=datetime.now() + timedelta(seconds=30))
    scheduler.start()
    app.extensions["scheduler"] = scheduler


# ---------- organiser authentication ----------

def login_required(view):
    @wraps(view)
    def wrapper(*args, **kwargs):
        if not Config.ADMIN_PASSWORD:
            return view(*args, **kwargs)
        if not flask_session.get("admin"):
            return redirect(url_for("login", next=request.path))
        return view(*args, **kwargs)
    return wrapper


def _register_routes(app):

    @app.template_filter("when")
    def when(value):
        return value.strftime("%a %b %-d, %-I:%M %p") if value else "—"

    @app.route("/login", methods=["GET", "POST"])
    def login():
        if request.method == "POST":
            if request.form.get("password") == app.config["ADMIN_PASSWORD"]:
                flask_session["admin"] = True
                return redirect(request.args.get("next") or url_for("dashboard"))
            flash("Wrong password.", "error")
        return render_template("login.html")

    @app.route("/logout")
    def logout():
        flask_session.clear()
        return redirect(url_for("login"))

    # ---------- dashboard ----------

    @app.route("/")
    @login_required
    def dashboard():
        now = local_now()
        sessions = (Session.query.join(Group).filter(Session.starts_at >= now)
                    .order_by(Session.starts_at).limit(20).all())
        return render_template("dashboard.html", sessions=sessions,
                               groups=Group.query.all(), dry_run=app.config["DRY_RUN"])

    @app.route("/sessions/<int:session_id>")
    @login_required
    def session_detail(session_id):
        record = db.session.get(Session, session_id)
        if not record:
            return redirect(url_for("dashboard"))
        return render_template("session.html", s=record,
                               candidates=engine.eligible(record))

    @app.route("/sessions/<int:session_id>/action", methods=["POST"])
    @login_required
    def session_action(session_id):
        record = db.session.get(Session, session_id)
        action = request.form.get("action")
        if record:
            if action == "confirmations":
                engine.open_confirmations(record)
                flash("Confirmation requests sent.", "ok")
            elif action == "remind":
                sent = 0
                for invite in record.pending:
                    messaging.confirmation(record.group, record, invite.player, invite,
                                           reminder=True)
                    invite.reminded_at = local_now()
                    sent += 1
                flash(f"{sent} reminder(s) sent.", "ok")
            elif action == "subs":
                count = engine.fill_spots(record)
                flash(f"{count} substitute invitation(s) sent.", "ok")
            elif action == "lineup":
                record.lineup_sent_at = None
                flash("Lineup sent." if engine.day_of_lineup(record)
                      else "Nothing to send: some answers are still missing.", "ok")
            db.session.commit()
        return redirect(url_for("session_detail", session_id=session_id))

    # ---------- import ----------

    @app.route("/upload", methods=["GET", "POST"])
    @login_required
    def upload():
        groups = Group.query.all()
        if request.method == "POST":
            kind = request.form.get("kind")
            uploaded = request.files.get("file")
            if not uploaded or not uploaded.filename:
                flash("No file selected.", "error")
                return redirect(url_for("upload"))

            if kind == "players":
                created, updated, errors = importer.import_players(uploaded)
                flash(f"{created} player(s) created, {updated} updated.", "ok")
                for err in errors:
                    flash(err, "error")
            else:
                group = db.session.get(Group, int(request.form.get("group_id")))
                year = int(request.form.get("year") or local_now().year)
                counts, warnings = importer.import_schedule(
                    uploaded, group, year, group.start_time)
                flash(f"{counts['sessions']} session(s), "
                      f"{counts['assignments']} assignment(s).", "ok")
                for warning in warnings[:10]:
                    flash(warning, "error")
            return redirect(url_for("dashboard"))
        return render_template("upload.html", groups=groups, year=local_now().year)

    # ---------- players, broadcast, log ----------

    @app.route("/players", methods=["GET", "POST"])
    @login_required
    def players():
        if request.method == "POST":
            player = db.session.get(Player, int(request.form["player_id"]))
            if player:
                player.email = request.form.get("email", "").strip()
                player.phone = request.form.get("phone", "").strip()
                player.active = bool(request.form.get("active"))
                db.session.commit()
                flash(f"{player.name} updated.", "ok")
            return redirect(url_for("players"))
        return render_template("players.html",
                               players=Player.query.order_by(Player.name).all())

    @app.route("/compose", methods=["GET", "POST"])
    @login_required
    def compose():
        groups = Group.query.all()
        if request.method == "POST":
            group = db.session.get(Group, int(request.form["group_id"]))
            targets = [p for p in group.roster if p.contactable]
            messaging.broadcast(group, targets, request.form["subject"], request.form["body"])
            db.session.commit()
            flash(f"Message sent to {len(targets)} player(s).", "ok")
            return redirect(url_for("compose"))
        return render_template("compose.html", groups=groups)

    @app.route("/log")
    @login_required
    def log():
        return render_template("log.html",
                               messages=Message.query.order_by(Message.created_at.desc())
                               .limit(200).all())

    @app.route("/run-cycle", methods=["POST"])
    @login_required
    def run_cycle():
        flash(f"Cycle ran over {engine.run_cycle()} session(s).", "ok")
        return redirect(url_for("dashboard"))

    # ---------- public route, no login ----------

    @app.route("/r/<token>")
    def respond(token):
        title, message = engine.respond(token, request.args.get("a", "").lower())
        return render_template("respond.html", title=title, message=message,
                               club=app.config["CLUB_NAME"])

    @app.route("/healthz")
    def healthz():
        return {"ok": True, "sessions": Session.query.count()}


app = create_app()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
