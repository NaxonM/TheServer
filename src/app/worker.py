import os
import time
import uuid
import requests
from .models import db, DownloadLog, DownloadStatus

class OperationAborted(Exception):
    """Custom exception for cancelled operations."""
    pass

def download_thread_target(flask_app, download_id):
    with flask_app.app_context():
        log_entry = DownloadLog.query.get(download_id)
        if not log_entry:
            flask_app.logger.warning(f"Download ID {download_id} not found for worker, aborting.")
            return

        if log_entry.status == DownloadStatus.CANCELLED:
            flask_app.logger.info(f"Download '{log_entry.filename}' was cancelled before starting. Worker exiting.")
            return

        unique_id = uuid.uuid4().hex
        DOWNLOADS_DIR = flask_app.config['DOWNLOADS_DIR']
        temp_filepath = os.path.join(DOWNLOADS_DIR, f"{log_entry.filename}.{unique_id}.tmp")
        final_filepath = os.path.join(DOWNLOADS_DIR, log_entry.filename)
        os.makedirs(DOWNLOADS_DIR, exist_ok=True)

        try:
            log_entry.status = DownloadStatus.DOWNLOADING
            db.session.commit()
            flask_app.logger.info(f"Starting download for '{log_entry.filename}' from {log_entry.remote_url}")

            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/58.0.3029.110 Safari/537.36'
            }
            with requests.get(log_entry.remote_url, stream=True, timeout=300, headers=headers) as r:
                r.raise_for_status()

                if log_entry.size_bytes == 0:
                    log_entry.size_bytes = int(r.headers.get('content-length', 0))
                    flask_app.logger.info(f"Updated size for '{log_entry.filename}' to {log_entry.size_bytes} bytes")

                downloaded_bytes = 0
                last_update_time = time.time()
                last_update_bytes = 0

                with open(temp_filepath, 'wb') as f:
                    for chunk in r.iter_content(chunk_size=8192):
                        if chunk:
                            f.write(chunk)
                            downloaded_bytes += len(chunk)

                            current_time = time.time()
                            elapsed_time = current_time - last_update_time

                            if elapsed_time > 2:
                                db.session.refresh(log_entry)
                                if log_entry.status == DownloadStatus.CANCELLED:
                                    flask_app.logger.info(f"Cancellation detected for '{log_entry.filename}'. Stopping download.")
                                    raise OperationAborted("Download was cancelled by user.")

                                bytes_since_last_update = downloaded_bytes - last_update_bytes
                                speed_bps = (bytes_since_last_update / elapsed_time) * 8

                                log_entry.progress_bytes = downloaded_bytes
                                log_entry.speed_bps = int(speed_bps)
                                db.session.commit()

                                last_update_time = current_time
                                last_update_bytes = downloaded_bytes

            os.rename(temp_filepath, final_filepath)

            log_entry.progress_bytes = log_entry.size_bytes
            log_entry.status = DownloadStatus.COMPLETED
            log_entry.speed_bps = 0
            db.session.commit()
            flask_app.logger.info(f"Successfully completed download for '{log_entry.filename}'")

        except OperationAborted:
            if os.path.exists(temp_filepath):
                os.remove(temp_filepath)
                flask_app.logger.info(f"Removed temporary file for cancelled download: {temp_filepath}")
        except Exception as e:
            error_message = str(e)
            flask_app.logger.error(f"Error downloading '{log_entry.filename}': {error_message}", exc_info=True)
            log_entry.status = DownloadStatus.FAILED
            log_entry.speed_bps = 0
            log_entry.error_message = error_message[:255]
            db.session.commit()

            if os.path.exists(temp_filepath):
                os.remove(temp_filepath)
                flask_app.logger.info(f"Removed temporary file for failed download: {temp_filepath}")