from flask import Blueprint, render_template, send_from_directory, abort, request, current_app
from flask_login import login_required, current_user
from ..models import db, DownloadLog, SecurityLog, LogEventType, UserRole
from werkzeug.utils import secure_filename
import os

main_bp = Blueprint('main', __name__)

@main_bp.route('/')
@login_required
def dashboard():
    return render_template('dashboard.html', UserRole=UserRole)

@main_bp.route('/download/<path:filename>')
@login_required
def download_file(filename):
    safe_filename = secure_filename(filename)

    if '/' in safe_filename or '\\' in safe_filename or '..' in safe_filename:
        abort(400, "Invalid filename")

    if not DownloadLog.query.filter_by(filename=safe_filename).first():
        abort(404, "File not found in proxy records.")

    DOWNLOADS_DIR = current_app.config['DOWNLOADS_DIR']
    file_path = os.path.join(DOWNLOADS_DIR, safe_filename)
    if not os.path.exists(file_path):
        abort(404, "Physical file not found on disk.")

    log_entry = SecurityLog(
        event_type=LogEventType.DOWNLOAD_SUCCESS,
        ip_address=request.remote_addr,
        user_id=current_user.id,
        details=f"User '{current_user.username}' downloaded file: {safe_filename}"
    )
    db.session.add(log_entry)
    db.session.commit()

    return send_from_directory(DOWNLOADS_DIR, safe_filename, as_attachment=True)