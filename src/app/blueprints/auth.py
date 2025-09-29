from flask import Blueprint, render_template, request, redirect, url_for, flash, current_app
from flask_login import login_user, logout_user, login_required, current_user
from werkzeug.security import check_password_hash
from ..models import db, User, SecurityLog, LogEventType
from ..forms import LoginForm
from ..extensions import limiter

auth_bp = Blueprint('auth', __name__)

@auth_bp.route('/login', methods=['GET', 'POST'])
@limiter.limit("10 per minute")
def login():
    if current_user.is_authenticated:
        return redirect(url_for('main.dashboard'))
    form = LoginForm()
    if form.validate_on_submit():
        username = form.username.data
        password = form.password.data
        user = User.query.filter_by(username=username).first()
        if user and check_password_hash(user.password, password):
            login_user(user)
            current_app.logger.info(f"User '{username}' logged in successfully from {request.remote_addr}")
            return redirect(url_for('main.dashboard'))

        current_app.logger.warning(f"Failed login attempt for username '{username}' from {request.remote_addr}")
        log_entry = SecurityLog(
            event_type=LogEventType.LOGIN_FAIL,
            ip_address=request.remote_addr,
            details=f"Failed login attempt for username: {username}"
        )
        db.session.add(log_entry)
        db.session.commit()

        flash('Invalid username or password')
    return render_template('login.html', form=form)

@auth_bp.route('/logout')
@login_required
def logout():
    current_app.logger.info(f"User '{current_user.username}' logged out.")
    logout_user()
    return redirect(url_for('auth.login'))