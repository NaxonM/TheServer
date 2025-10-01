from flask import Blueprint, render_template, request, flash, redirect, url_for
from flask_login import login_required
import requests
import os
from ..models import db, DownloadLog, DownloadSource, DownloadStatus

porn_fetch_bp = Blueprint('porn_fetch', __name__)

# The porn-fetch service is available at this hostname within the Docker network.
# The service name is defined in the docker-compose.yml file.
PORN_FETCH_API_URL = "http://porn-fetch:5000/api/download"

@porn_fetch_bp.route('/porn-fetch', methods=['GET', 'POST'])
@login_required
def index():
    if request.method == 'POST':
        download_type = request.form.get('download_type')
        quality = request.form.get('quality', 'best')
        payload = {'quality': quality}
        success_message = "Successfully requested download."

        if download_type == 'url':
            query = request.form.get('query')
            if not query:
                flash('The URL field cannot be empty.', 'danger')
                return redirect(url_for('porn_fetch.index'))
            payload['url'] = query
            success_message = f"Successfully requested download for URL: {query}"

        elif download_type == 'batch':
            urls = request.form.getlist('urls')
            if not urls:
                flash('You must select at least one video to download.', 'danger')
                return redirect(url_for('porn_fetch.index'))

            payload['urls'] = urls
            success_message = f"Successfully requested batch download of {len(urls)} videos."

        elif download_type == 'file':
            url_list = request.form.get('url_list', '')
            urls = [url.strip() for url in url_list.splitlines() if url.strip()]
            if not urls:
                flash('You must provide at least one URL in the text area.', 'danger')
                return redirect(url_for('porn_fetch.index'))

            payload['urls'] = urls
            success_message = f"Successfully requested batch download of {len(urls)} videos from file."

        else:
            # This case now only handles direct form submissions for single URLs and batch downloads.
            # Other interactions (fetching videos) are handled via the API blueprint.
            flash(f"Invalid or unsupported form submission: {download_type}", 'danger')
            return redirect(url_for('porn_fetch.index'))

        try:
            # Set a timeout for the request to avoid hanging the web worker.
            response = requests.post(PORN_FETCH_API_URL, json=payload, timeout=10)

            if response.status_code == 202:
                flash(success_message, 'success')
            else:
                # Try to get a specific error message from the service's response.
                error_message = response.json().get('error', 'Unknown error from porn-fetch service.')
                flash(f"Failed to start download. Service responded with: {error_message}", 'danger')

        except requests.exceptions.RequestException as e:
            flash(f"An error occurred while communicating with the porn-fetch service: {e}", 'danger')

        return redirect(url_for('porn_fetch.index'))

    # Fetch history for the Porn Fetch source
    download_history_objs = DownloadLog.query.filter_by(source=DownloadSource.PORN_FETCH).order_by(DownloadLog.created_at.desc()).all()
    # Convert database objects to dictionaries to make them JSON serializable
    download_history = [d.to_dict() for d in download_history_objs]
    return render_template('porn_fetch/index.html', download_history=download_history)