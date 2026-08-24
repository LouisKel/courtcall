"""CSV import: player directory and season grid."""
import csv
import io
from datetime import datetime

from models import Player, Roster, Session, db

DATE_FORMATS = ("%m/%d/%Y", "%Y-%m-%d", "%m/%d/%y", "%d/%m/%Y", "%m/%d")


def _rows(file_storage):
    text = file_storage.read().decode("utf-8-sig")
    return list(csv.reader(io.StringIO(text)))


def parse_date(raw, default_year):
    raw = (raw or "").strip()
    for fmt in DATE_FORMATS:
        try:
            parsed = datetime.strptime(raw, fmt)
            if "%Y" not in fmt and "%y" not in fmt:
                parsed = parsed.replace(year=default_year)
            return parsed.date()
        except ValueError:
            continue
    return None


def import_players(file_storage):
    """Expects name, email, phone. Updates existing players without clearing blanks."""
    created = updated = 0
    rows = _rows(file_storage)
    if not rows:
        return 0, 0, ["file is empty"]

    header = [c.strip().lower() for c in rows[0]]
    idx = {key: header.index(key) for key in ("name", "email", "phone") if key in header}
    if "name" not in idx:
        return 0, 0, ["missing 'name' column"]

    for row in rows[1:]:
        if not any(c.strip() for c in row):
            continue
        name = row[idx["name"]].strip()
        if not name:
            continue
        player = Player.query.filter(db.func.lower(Player.name) == name.lower()).first()
        if player:
            updated += 1
        else:
            player = Player(name=name)
            db.session.add(player)
            created += 1
        for key in ("email", "phone"):
            if key in idx and idx[key] < len(row) and row[idx[key]].strip():
                setattr(player, key, row[idx[key]].strip())
    db.session.commit()
    return created, updated, []


def import_schedule(file_storage, group, year, start_time="09:00"):
    """
    The club's own grid format: row 1 holds dates from column B onward,
    column A holds player names, a cell of 1 means that player is on.
    Sessions that have already been invited out are never rewritten.
    """
    rows = _rows(file_storage)
    if len(rows) < 2:
        return {"sessions": 0, "assignments": 0}, ["grid is empty"]

    warnings = []
    header = rows[0]
    columns = []
    for col in range(1, len(header)):
        day = parse_date(header[col], year)
        if day:
            columns.append((col, day))
        elif header[col].strip() and header[col].strip().lower() != "total":
            warnings.append(f"ignored header: {header[col]}")
    if not columns:
        return {"sessions": 0, "assignments": 0}, ["no dates recognised in row 1"]

    hour, minute = (int(x) for x in start_time.split(":"))
    sessions = {}
    for col, day in columns:
        starts_at = datetime.combine(day, datetime.min.time()).replace(hour=hour, minute=minute)
        session = Session.query.filter_by(group_id=group.id, starts_at=starts_at).first()
        if not session:
            session = Session(group_id=group.id, starts_at=starts_at)
            db.session.add(session)
            db.session.flush()
        sessions[col] = session

    roster_ids, assignments = set(), 0
    for row in rows[1:]:
        if not row or not row[0].strip():
            continue
        name = row[0].strip()
        if name.lower() == "total":
            continue
        player = Player.query.filter(db.func.lower(Player.name) == name.lower()).first()
        if not player:
            warnings.append(f"player not in directory: {name}")
            continue
        roster_ids.add(player.id)
        for col, session in sessions.items():
            if col < len(row) and row[col].strip() in ("1", "x", "X"):
                if session.invites:
                    continue
                exists = Roster.query.filter_by(session_id=session.id,
                                                player_id=player.id).first()
                if not exists:
                    db.session.add(Roster(session_id=session.id, player_id=player.id))
                    assignments += 1

    for player in Player.query.filter(Player.id.in_(roster_ids)).all():
        if player not in group.roster:
            group.roster.append(player)

    db.session.commit()
    counts = {"sessions": len(sessions), "assignments": assignments}
    empty = [s for s in sessions.values() if not s.scheduled]
    for session in empty:
        if not session.invites:
            db.session.delete(session)
    db.session.commit()
    counts["sessions"] -= len(empty)
    return counts, warnings
