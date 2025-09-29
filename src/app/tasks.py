import threading
import time
import os
from datetime import datetime, timedelta
from werkzeug.security import generate_password_hash
from sqlalchemy.exc import IntegrityError
from .models import db, User, Setting, DownloadLog, UserRole, DownloadStatus

def setup_database(app):
    # This import is scoped locally as fcntl is not available on Windows
    import fcntl
    lock_file = '/data/db_init.lock'

    with app.app_context():
        try:
            with open(lock_file, 'w') as f:
                # Get an exclusive, non-blocking lock
                fcntl.flock(f.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)

                db.create_all()

                # Robustly reconcile the admin user based on environment variables.
                username = os.environ.get('ADMIN_USERNAME')
                password = os.environ.get('ADMIN_PASSWORD')

                if not username or not password:
                    app.logger.warning("Admin username or password not set in environment. Skipping admin setup.")
                else:
                    # Demote all existing admins to ensure only the configured user is admin.
                    # This handles cases where the admin username changes between deployments.
                    existing_admins = User.query.filter_by(role=UserRole.ADMIN).all()
                    for old_admin in existing_admins:
                        if old_admin.username != username:
                            app.logger.info(f"Demoting old admin user '{old_admin.username}' to USER.")
                            old_admin.role = UserRole.USER

                    # Find the user designated as admin by the environment.
                    target_user = User.query.filter_by(username=username).first()
                    hashed_password = generate_password_hash(password, method='pbkdf2:sha256')

                    if target_user:
                        # User exists, ensure they are an admin with the correct password.
                        app.logger.info(f"Found user '{username}'. Ensuring they are admin with the correct password.")
                        target_user.password = hashed_password
                        target_user.role = UserRole.ADMIN
                    else:
                        # User does not exist, create them as the admin.
                        app.logger.info(f"No user named '{username}' found. Creating as new admin.")
                        target_user = User(username=username, password=hashed_password, role=UserRole.ADMIN)
                        db.session.add(target_user)

                    db.session.commit()

                # Create default setting if it doesn't exist
                if not Setting.query.filter_by(key='cleanup_interval').first():
                    db.session.add(Setting(key='cleanup_interval', value='60'))

                if not Setting.query.filter_by(key='auto_cleanup_enabled').first():
                    db.session.add(Setting(key='auto_cleanup_enabled', value='false'))

                db.session.commit()

        except (IOError, IntegrityError) as e:
            # This will happen if another worker has already acquired the lock
            app.logger.info(f"Database setup likely handled by another process: {e}")
            db.session.rollback()
        except Exception as e:
            app.logger.error(f"An unexpected error occurred during DB setup: {e}")
            db.session.rollback()

def cleanup_thread_target(flask_app):
    with flask_app.app_context():
        while True:
            try:
                auto_cleanup_enabled = Setting.query.filter_by(key='auto_cleanup_enabled').first()
                if auto_cleanup_enabled and auto_cleanup_enabled.value == 'true':
                    cleanup_interval_setting = Setting.query.filter_by(key='cleanup_interval').first()
                    interval_minutes = int(cleanup_interval_setting.value) if cleanup_interval_setting else 60

                    cleanup_threshold = datetime.utcnow() - timedelta(minutes=interval_minutes)

                    old_files = DownloadLog.query.filter(
                        DownloadLog.status == DownloadStatus.COMPLETED,
                        DownloadLog.updated_at < cleanup_threshold
                    ).all()

                    if old_files:
                        flask_app.logger.info(f"Auto-cleanup: Found {len(old_files)} old files to delete.")
                        for log_entry in old_files:
                            try:
                                file_path = os.path.join(flask_app.config['DOWNLOADS_DIR'], log_entry.filename)
                                if os.path.exists(file_path):
                                    os.remove(file_path)
                                    flask_app.logger.info(f"Auto-cleanup: Deleted physical file: {file_path}")

                                db.session.delete(log_entry)
                                db.session.commit()
                                flask_app.logger.info(f"Auto-cleanup: Deleted file log: {log_entry.filename}")

                            except Exception as e:
                                flask_app.logger.error(f"Auto-cleanup: Error deleting file {log_entry.filename}: {e}", exc_info=True)
                                db.session.rollback()

                # Check every 5 minutes
                time.sleep(300)

            except Exception as e:
                flask_app.logger.error(f"An error occurred in the cleanup thread: {e}", exc_info=True)
                # Wait a bit before retrying to avoid spamming logs on persistent errors
                time.sleep(60)