"""Data model. A single table carries the state of every request."""
import os
from datetime import datetime
from zoneinfo import ZoneInfo

from flask_sqlalchemy import SQLAlchemy


def local_now():
    """Wall-clock time in the club timezone, naive.

    Session times come from the CSV as naive local times, so every comparison
    must use the same clock. Using UTC shifted every send by the offset.
    """
    tz = os.environ.get("TIMEZONE", "America/Chicago")
    return datetime.now(ZoneInfo(tz)).replace(tzinfo=None)

db = SQLAlchemy()

# kind
SLOT = "SLOT"   # player on the season grid
FILL = "FILL"   # invitation to substitute

# status
PENDING = "PENDING"      # SLOT awaiting an answer
CONFIRMED = "CONFIRMED"  # SLOT is playing
DECLINED = "DECLINED"    # SLOT or FILL turned it down
EXPIRED = "EXPIRED"      # SLOT never answered
OFFERED = "OFFERED"      # FILL invitation open
CLAIMED = "CLAIMED"      # FILL took the spot
CLOSED = "CLOSED"        # FILL spot taken by someone else

PLAYING = (CONFIRMED, CLAIMED)
TERMINAL = (CONFIRMED, DECLINED, EXPIRED, CLAIMED, CLOSED)

memberships = db.Table(
    "memberships",
    db.Column("group_id", db.Integer, db.ForeignKey("groups.id"), primary_key=True),
    db.Column("player_id", db.Integer, db.ForeignKey("players.id"), primary_key=True),
)


class Group(db.Model):
    __tablename__ = "groups"
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), nullable=False, unique=True)
    players_needed = db.Column(db.Integer, default=8, nullable=False)
    courts = db.Column(db.Integer, default=2)
    start_time = db.Column(db.String(5), default="09:00")
    organizer_email = db.Column(db.String(200), default="")
    active = db.Column(db.Boolean, default=True)

    roster = db.relationship("Player", secondary=memberships, back_populates="groups", lazy="joined")
    sessions = db.relationship("Session", back_populates="group", cascade="all, delete-orphan")


class Player(db.Model):
    __tablename__ = "players"
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), nullable=False, unique=True)
    email = db.Column(db.String(200), default="")
    phone = db.Column(db.String(40), default="")
    active = db.Column(db.Boolean, default=True)

    groups = db.relationship("Group", secondary=memberships, back_populates="roster")

    @property
    def contactable(self):
        return self.active and bool(self.email.strip())

    @property
    def first_name(self):
        return (self.name or "").split(" ")[0] or "there"


class Session(db.Model):
    __tablename__ = "sessions"
    id = db.Column(db.Integer, primary_key=True)
    group_id = db.Column(db.Integer, db.ForeignKey("groups.id"), nullable=False)
    starts_at = db.Column(db.DateTime, nullable=False, index=True)
    lineup_sent_at = db.Column(db.DateTime)
    alerted_at = db.Column(db.DateTime)

    group = db.relationship("Group", back_populates="sessions")
    invites = db.relationship("Invite", back_populates="session", order_by="Invite.id",
                              cascade="all, delete-orphan")
    scheduled = db.relationship("Roster", back_populates="session", order_by="Roster.id",
                                cascade="all, delete-orphan")

    __table_args__ = (db.UniqueConstraint("group_id", "starts_at", name="uq_session"),)

    @property
    def needed(self):
        return self.group.players_needed

    @property
    def playing(self):
        return [i for i in self.invites if i.status in PLAYING]

    @property
    def pending(self):
        return [i for i in self.invites if i.status == PENDING]

    @property
    def gap(self):
        return max(0, self.needed - len(self.playing) - len(self.pending))

    @property
    def open_spots(self):
        return max(0, self.needed - len(self.playing))


class Roster(db.Model):
    """Who the season grid had down for this session."""
    __tablename__ = "rosters"
    id = db.Column(db.Integer, primary_key=True)
    session_id = db.Column(db.Integer, db.ForeignKey("sessions.id"), nullable=False)
    player_id = db.Column(db.Integer, db.ForeignKey("players.id"), nullable=False)

    session = db.relationship("Session", back_populates="scheduled")
    player = db.relationship("Player")

    __table_args__ = (db.UniqueConstraint("session_id", "player_id", name="uq_roster"),)


class Invite(db.Model):
    __tablename__ = "invites"
    id = db.Column(db.Integer, primary_key=True)
    session_id = db.Column(db.Integer, db.ForeignKey("sessions.id"), nullable=False)
    player_id = db.Column(db.Integer, db.ForeignKey("players.id"), nullable=False)
    kind = db.Column(db.String(8), nullable=False)
    wave = db.Column(db.Integer, default=0)
    status = db.Column(db.String(12), nullable=False)
    token = db.Column(db.String(48), unique=True, nullable=False, index=True)
    sent_at = db.Column(db.DateTime, default=local_now)
    reminded_at = db.Column(db.DateTime)
    responded_at = db.Column(db.DateTime)

    session = db.relationship("Session", back_populates="invites")
    player = db.relationship("Player")

    __table_args__ = (db.UniqueConstraint("session_id", "player_id", name="uq_invite"),)


class Message(db.Model):
    """Delivery log. Doubles as the audit trail and the dry-run output."""
    __tablename__ = "messages"
    id = db.Column(db.Integer, primary_key=True)
    created_at = db.Column(db.DateTime, default=local_now, index=True)
    channel = db.Column(db.String(10), default="email")
    recipient = db.Column(db.String(200))
    subject = db.Column(db.String(240))
    status = db.Column(db.String(20), default="sent")
    detail = db.Column(db.Text, default="")
