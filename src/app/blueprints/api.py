from flask import Blueprint, jsonify, request, current_app, abort, Response
from flask_login import login_required, current_user
from werkzeug.security import generate_password_hash
from werkzeug.utils import secure_filename
from sqlalchemy.exc import IntegrityError
import psutil
import threading
import json
import time
import os
import requests

from ..models import db, DownloadLog, Setting, DownloadStatus, User, UserRole
from ..worker import download_thread_target
from ..helpers import get_filename_from_headers, is_safe_url, read_last_n_lines
from ..stats_collector import system_stats
from ..decorators import api_admin_required
from ..forms import ProxyUrlForm
from ..extensions import csrf

api_bp = Blueprint('api', __name__)

@api_bp.route('/stats')
@login_required
def api_stats():
    with system_stats['lock']:
        # Read the latest stats from the background collector.
        current_stats = {
            "cpu_percent": system_stats['cpu_percent'],
            "memory_percent": system_stats['memory_percent']
        }

    downloads = DownloadLog.query.order_by(DownloadLog.created_at.desc()).all()
    all_downloads = [d.to_dict() for d in downloads]

    total_traffic = db.session.query(db.func.sum(DownloadLog.size_bytes)).filter(DownloadLog.status == DownloadStatus.COMPLETED).scalar() or 0

    stored_files_count = DownloadLog.query.filter_by(status=DownloadStatus.COMPLETED).count()
    total_stored_size = db.session.query(db.func.sum(DownloadLog.size_bytes)).filter(DownloadLog.status == DownloadStatus.COMPLETED).scalar() or 0

    return jsonify({
        "system": current_stats,
        "proxy": {
            "downloads": all_downloads,
            "total_traffic": total_traffic,
            "stored_files_count": stored_files_count,
            "total_stored_size": total_stored_size,
        }
    })

@api_bp.route('/proxy', methods=['POST'])
@login_required
def start_proxy_download():
    form = ProxyUrlForm()
    if not form.validate_on_submit():
        # This will catch CSRF errors and validation errors.
        current_app.logger.warning(f"Proxy URL submission failed for user {current_user.username}: {form.errors}")
        return jsonify({"error": "Invalid submission.", "details": form.errors}), 400

    remote_url = form.url.data
    custom_filename = form.filename.data

    if not is_safe_url(remote_url):
        current_app.logger.warning(f"User '{current_user.username}' submitted unsafe URL for proxy: {remote_url}")
        return jsonify({"error": "The provided URL is not allowed as it resolves to a private or reserved IP address."}), 400

    current_app.logger.info(f"User '{current_user.username}' submitted URL for proxy: {remote_url}")
    if custom_filename:
        current_app.logger.info(f"User provided custom filename: '{custom_filename}'")

    try:
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/58.0.3029.110 Safari/537.36'
        }
        with requests.get(remote_url, stream=True, timeout=10, headers=headers) as r:
            r.raise_for_status()

            if custom_filename:
                unsafe_filename = custom_filename
            else:
                unsafe_filename = get_filename_from_headers(r.headers) or remote_url.split('/')[-1].split('?')[0]

            if not unsafe_filename:
                current_app.logger.error(f"Could not determine filename for URL: {remote_url}")
                return jsonify({"error": "Could not determine filename from URL"}), 400

            filename = secure_filename(unsafe_filename)
            total_size = int(r.headers.get('content-length', 0))

        existing_log = DownloadLog.query.filter_by(filename=filename).first()
        if existing_log and existing_log.status != DownloadStatus.FAILED:
            current_app.logger.info(f"Proxy request for '{filename}' rejected: file already exists or is queued.")
            return jsonify({"message": f"File '{filename}' already exists or is queued."}), 200

        if existing_log and existing_log.status == DownloadStatus.FAILED:
            current_app.logger.info(f"Deleting previously failed log for '{filename}' to re-download.")
            db.session.delete(existing_log)
            db.session.commit()

        log_entry = DownloadLog(
            filename=filename,
            remote_url=remote_url,
            size_bytes=total_size,
            status=DownloadStatus.QUEUED
        )
        db.session.add(log_entry)
        db.session.commit()
        current_app.logger.info(f"Queued '{filename}' for download. Starting worker thread.")

        thread = threading.Thread(target=download_thread_target, args=(current_app._get_current_object(), log_entry.id))
        thread.start()

        return jsonify(log_entry.to_dict()), 202

    except requests.exceptions.RequestException as e:
        current_app.logger.error(f"Failed to connect to remote source '{remote_url}': {e}", exc_info=True)
        return jsonify({"error": f"Failed to connect to remote source: {e}"}), 502
    except IntegrityError:
        db.session.rollback()
        current_app.logger.warning(f"Proxy request for '{filename}' failed due to integrity error (likely duplicate).")
        return jsonify({"error": f"File '{filename}' already exists."}), 409
    except Exception as e:
        db.session.rollback()
        current_app.logger.critical(f"An unexpected internal error occurred while proxying '{remote_url}': {e}", exc_info=True)
        return jsonify({"error": f"An internal error occurred: {e}"}), 500

@api_bp.route('/files/<filename>', methods=['DELETE'])
@login_required
def delete_file(filename):
    safe_filename = secure_filename(filename)
    log_entry = DownloadLog.query.filter_by(filename=safe_filename).first()

    if not log_entry:
        current_app.logger.warning(f"User '{current_user.username}' failed to delete non-existent file: {safe_filename}")
        abort(404, "File not found")

    DOWNLOADS_DIR = current_app.config['DOWNLOADS_DIR']
    file_path = os.path.join(DOWNLOADS_DIR, safe_filename)
    if os.path.exists(file_path):
        try:
            os.remove(file_path)
            current_app.logger.info(f"User '{current_user.username}' deleted physical file: {file_path}")
        except OSError as e:
            current_app.logger.error(f"Error deleting physical file {file_path} for user '{current_user.username}': {e}", exc_info=True)

    db.session.delete(log_entry)
    db.session.commit()
    current_app.logger.info(f"User '{current_user.username}' deleted file log: {safe_filename}")
    return jsonify({"success": True}), 200

@api_bp.route('/files/<filename>/rename', methods=['POST'])
@login_required
def rename_file_api(filename):
    safe_filename = secure_filename(filename)
    log_entry = DownloadLog.query.filter_by(filename=safe_filename).first_or_404()

    new_filename_unsafe = request.json.get('new_filename')
    if not new_filename_unsafe:
        return jsonify({"error": "New filename is required."}), 400

    new_filename = secure_filename(new_filename_unsafe)
    if not new_filename:
        return jsonify({"error": "Invalid new filename."}), 400

    if DownloadLog.query.filter_by(filename=new_filename).first():
        return jsonify({"error": f"File with name '{new_filename}' already exists."}), 409

    DOWNLOADS_DIR = current_app.config['DOWNLOADS_DIR']
    old_path = os.path.join(DOWNLOADS_DIR, safe_filename)
    new_path = os.path.join(DOWNLOADS_DIR, new_filename)

    try:
        if os.path.exists(old_path):
            os.rename(old_path, new_path)
            current_app.logger.info(f"User '{current_user.username}' renamed file '{safe_filename}' to '{new_filename}'")

        log_entry.filename = new_filename
        db.session.commit()
        current_app.logger.info(f"Updated database record for '{safe_filename}' to '{new_filename}'")

        return jsonify({"success": True, "new_filename": new_filename}), 200
    except OSError as e:
        current_app.logger.error(f"Error renaming file '{safe_filename}' to '{new_filename}': {e}", exc_info=True)
        db.session.rollback()
        return jsonify({"error": "Failed to rename file on disk."}), 500

@api_bp.route('/files/<filename>/cancel', methods=['POST'])
@login_required
def cancel_download(filename):
    safe_filename = secure_filename(filename)
    log_entry = DownloadLog.query.filter_by(filename=safe_filename).first()

    if not log_entry:
        current_app.logger.warning(f"User '{current_user.username}' failed to cancel non-existent download: {safe_filename}")
        abort(404, "File not found")

    if log_entry.status not in [DownloadStatus.QUEUED, DownloadStatus.DOWNLOADING]:
        current_app.logger.warning(f"User '{current_user.username}' attempted to cancel a download that is not active: {safe_filename} (Status: {log_entry.status.value})")
        return jsonify({"error": "Download is not in a cancellable state."}), 400

    log_entry.status = DownloadStatus.CANCELLED
    log_entry.speed_bps = 0
    db.session.commit()
    current_app.logger.info(f"User '{current_user.username}' cancelled download: {safe_filename}")

    return jsonify({"success": True}), 200

@api_bp.route('/stream')
@login_required
def stream():
    app = current_app._get_current_object()
    def event_stream():
        while True:
            with app.app_context():
                active_downloads = DownloadLog.query.filter(
                    DownloadLog.status.in_([DownloadStatus.QUEUED, DownloadStatus.DOWNLOADING])
                ).order_by(DownloadLog.created_at.desc()).all()

                finished_downloads = DownloadLog.query.filter(
                    DownloadLog.status.in_([DownloadStatus.COMPLETED, DownloadStatus.FAILED, DownloadStatus.CANCELLED])
                ).order_by(DownloadLog.updated_at.desc()).limit(5).all()

                payload = {
                    "active": [d.to_dict() for d in active_downloads],
                    "finished": [d.to_dict() for d in finished_downloads]
                }
                yield f"data: {json.dumps(payload)}\n\n"
            time.sleep(2)
    return Response(event_stream(), mimetype='text/event-stream')

@api_bp.route('/settings', methods=['GET', 'POST'])
@login_required
def manage_settings():
    if request.method == 'POST':
        data = request.json
        interval = data.get('cleanup_interval')
        enabled = data.get('auto_cleanup_enabled')

        if interval:
            setting = Setting.query.filter_by(key='cleanup_interval').first()
            if setting and interval.isdigit():
                setting.value = str(interval)

        if enabled is not None:
            setting = Setting.query.filter_by(key='auto_cleanup_enabled').first()
            if setting:
                setting.value = str(enabled).lower()

        db.session.commit()

    interval_setting = Setting.query.filter_by(key='cleanup_interval').first()
    enabled_setting = Setting.query.filter_by(key='auto_cleanup_enabled').first()

    return jsonify({
        "cleanup_interval": interval_setting.value if interval_setting else '60',
        "auto_cleanup_enabled": enabled_setting.value if enabled_setting else 'false'
    })

# --- Admin API Routes ---

@api_bp.route('/users', methods=['GET'])
@login_required
@api_admin_required
def get_users():
    users = User.query.all()
    return jsonify([{"id": u.id, "username": u.username, "role": u.role.value} for u in users])

@api_bp.route('/users', methods=['POST'])
@login_required
@api_admin_required
def create_user():
    data = request.json
    username = data.get('username')
    password = data.get('password')
    role = data.get('role', 'USER')

    if not username or not password:
        current_app.logger.warning(f"Admin '{current_user.username}' failed to create user: username or password missing.")
        return jsonify({"error": "Username and password are required"}), 400
    if User.query.filter_by(username=username).first():
        current_app.logger.warning(f"Admin '{current_user.username}' failed to create user '{username}': user already exists.")
        return jsonify({"error": "Username already exists"}), 409

    hashed_password = generate_password_hash(password, method='pbkdf2:sha256')
    new_user = User(
        username=username,
        password=hashed_password,
        role=UserRole[role.upper()]
    )
    db.session.add(new_user)
    db.session.commit()
    current_app.logger.info(f"Admin '{current_user.username}' created new user: '{username}' with role '{role}'")
    return jsonify({"id": new_user.id, "username": new_user.username, "role": new_user.role.value}), 201

@api_bp.route('/users/<int:user_id>', methods=['DELETE'])
@login_required
@api_admin_required
def delete_user(user_id):
    if user_id == current_user.id:
        current_app.logger.warning(f"Admin '{current_user.username}' attempted to delete their own account.")
        return jsonify({"error": "You cannot delete your own account."}), 403

    user = User.query.get_or_404(user_id)
    deleted_username = user.username
    db.session.delete(user)
    db.session.commit()
    current_app.logger.info(f"Admin '{current_user.username}' deleted user: '{deleted_username}' (ID: {user_id})")
    return jsonify({"success": True}), 200

@api_bp.route('/logs', methods=['GET'])
@login_required
@api_admin_required
def get_logs():
    log_file = current_app.config.get('LOG_FILE')
    log_lines = read_last_n_lines(log_file, 100)
    return jsonify({"logs": "\n".join(log_lines)})

@api_bp.route('/log-settings', methods=['GET', 'POST'])
@login_required
@api_admin_required
def manage_log_settings():
    log_setting_key = 'show_logs'

    if request.method == 'POST':
        show_logs = request.json.get('show_logs')
        if show_logs is not None:
            setting = Setting.query.filter_by(key=log_setting_key).first()
            if setting:
                setting.value = str(show_logs).lower()
            else:
                db.session.add(Setting(key=log_setting_key, value=str(show_logs).lower()))
            db.session.commit()
            current_app.logger.info(f"Admin '{current_user.username}' set show_logs to {show_logs}")

    setting = Setting.query.filter_by(key=log_setting_key).first()
    return jsonify({"show_logs": setting.value if setting else 'false'})