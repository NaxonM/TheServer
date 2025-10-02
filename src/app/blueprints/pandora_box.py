from flask import Blueprint, render_template, request, jsonify
from flask_login import login_required
from ..models import DownloadLog, DownloadSource
from ..decorators import web_admin_required
from PF-Repo.downloader import HeadlessDownloader

pandora_box_bp = Blueprint(
    'pandora_box',
    __name__,
    template_folder='../templates/pandora_box',
    static_folder='../static'
)

downloader = HeadlessDownloader()

@pandora_box_bp.route('/pandora-box')
@login_required
@web_admin_required
def index():
    # Fetch only the downloads initiated by the PORN_FETCH source
    download_history_objs = DownloadLog.query.filter_by(source=DownloadSource.PORN_FETCH).order_by(DownloadLog.created_at.desc()).all()
    # Convert the list of objects to a list of dictionaries so it can be serialized to JSON
    download_history = [d.to_dict() for d in download_history_objs]
    return render_template('pandora_box/index.html', download_history=download_history)

@pandora_box_bp.route('/pandora-box/download', methods=['POST'])
@login_required
@web_admin_required
def download_video():
    data = request.get_json()
    url = data.get('url')
    quality = data.get('quality', 'best')

    if not url:
        return jsonify({'error': 'URL is required'}), 400

    try:
        output_path, status = downloader.download_video_by_url(url, quality=quality)
        return jsonify({'status': status, 'output_path': output_path})
    except Exception as e:
        return jsonify({'error': str(e)}), 500
