from functools import wraps
from flask_login import current_user
from flask import jsonify, flash, redirect, url_for
from .models import UserRole

def api_admin_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not current_user.is_authenticated or not current_user.is_admin:
            return jsonify({"error": "Admin access required"}), 403
        return f(*args, **kwargs)
    return decorated_function

def web_admin_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not current_user.is_authenticated or not current_user.is_admin:
            flash("You do not have permission to access this page.")
            return redirect(url_for('main.dashboard'))
        return f(*args, **kwargs)
    return decorated_function