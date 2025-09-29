from flask import Blueprint, render_template
from flask_login import login_required
from ..decorators import web_admin_required

admin_bp = Blueprint('admin', __name__)

@admin_bp.route('')
@login_required
@web_admin_required
def dashboard():
    return render_template('admin.html')