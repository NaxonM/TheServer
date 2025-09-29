import enum
from datetime import datetime
from flask_login import UserMixin
from .extensions import db

class DownloadStatus(enum.Enum):
    QUEUED = "QUEUED"
    DOWNLOADING = "DOWNLOADING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"

class UserRole(enum.Enum):
    ADMIN = "ADMIN"
    USER = "USER"

class LogEventType(enum.Enum):
    LOGIN_FAIL = "LOGIN_FAIL"
    DOWNLOAD_SUCCESS = "DOWNLOAD_SUCCESS"

class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(150), unique=True, nullable=False)
    password = db.Column(db.String(150), nullable=False)
    role = db.Column(db.Enum(UserRole), nullable=False, default=UserRole.USER)

    @property
    def is_admin(self):
        """Checks if the user has the ADMIN role, handling both enum and string values."""
        return self.role == UserRole.ADMIN or self.role == UserRole.ADMIN.value

class Setting(db.Model):
    key = db.Column(db.String(50), primary_key=True)
    value = db.Column(db.String(150), nullable=False)

class DownloadLog(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    filename = db.Column(db.String(255), unique=True, nullable=False)
    remote_url = db.Column(db.String(2048), nullable=False)
    size_bytes = db.Column(db.Integer, nullable=False, default=0)
    progress_bytes = db.Column(db.Integer, nullable=False, default=0)
    speed_bps = db.Column(db.BigInteger, nullable=False, default=0)
    status = db.Column(db.Enum(DownloadStatus), nullable=False, default=DownloadStatus.QUEUED)
    error_message = db.Column(db.String(255), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    def to_dict(self):
        return {
            "id": self.id,
            "filename": self.filename,
            "remote_url": self.remote_url,
            "size_bytes": self.size_bytes,
            "progress_bytes": self.progress_bytes,
            "speed_bps": self.speed_bps,
            "status": self.status.value,
            "error_message": self.error_message,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat()
        }

class SecurityLog(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    event_type = db.Column(db.Enum(LogEventType), nullable=False)
    ip_address = db.Column(db.String(45))
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)
    details = db.Column(db.String(255))
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)