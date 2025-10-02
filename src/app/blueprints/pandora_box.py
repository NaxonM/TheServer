from flask import Blueprint, render_template
from flask_login import login_required
from ..models import DownloadLog, DownloadSource
from ..decorators import web_admin_required

pandora_box_bp = Blueprint(
    'pandora_box',
    __name__,
    template_folder='../templates/pandora_box',
    static_folder='../static'
)

@pandora_box_bp.route('/pandora-box')
@login_required
@web_admin_required
def index():
    # Fetch only the downloads initiated by the PORN_FETCH source
    download_history_objs = DownloadLog.query.filter_by(source=DownloadSource.PORN_FETCH).order_by(DownloadLog.created_at.desc()).all()
    # Convert the list of objects to a list of dictionaries so it can be serialized to JSON
    download_history = [d.to_dict() for d in download_history_objs]
    return render_template('pandora_box/index.html', download_history=download_history)