import threading as native_threading

from gevent import monkey
monkey.patch_all()

import os
import logging
from logging.handlers import RotatingFileHandler
from flask import Flask
from .config import Config
from .extensions import db, login_manager, limiter, csrf
from .models import User
from .tasks import setup_database, cleanup_thread_target
from .stats_collector import stats_collector_thread
import threading

def create_app(config_class=Config):
    app = Flask(__name__)
    app.config.from_object(config_class)

    # Initialize extensions
    db.init_app(app)
    login_manager.init_app(app)
    limiter.init_app(app)
    csrf.init_app(app)

    # Configure login manager
    login_manager.login_view = 'auth.login'
    @login_manager.user_loader
    def load_user(user_id):
        return User.query.get(int(user_id))

    # Import and register blueprints
    from .blueprints.main import main_bp
    from .blueprints.auth import auth_bp
    from .blueprints.api import api_bp
    from .blueprints.admin import admin_bp

    app.register_blueprint(main_bp)
    app.register_blueprint(auth_bp)
    app.register_blueprint(api_bp, url_prefix='/api')
    app.register_blueprint(admin_bp, url_prefix='/admin')

    # Configure logging
    log_dir = app.config['LOG_DIR']
    log_file = app.config['LOG_FILE']
    os.makedirs(log_dir, exist_ok=True)
    file_handler = RotatingFileHandler(log_file, maxBytes=1024*1024*5, backupCount=5)
    stream_handler = logging.StreamHandler()
    formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
    file_handler.setFormatter(formatter)
    stream_handler.setFormatter(formatter)

    if not app.logger.handlers:
        app.logger.addHandler(file_handler)
        app.logger.addHandler(stream_handler)
        app.logger.setLevel(logging.INFO)

    app.logger.info("Flask app created and configured.")

    # Setup database and start background tasks
    with app.app_context():
        setup_database(app)

    cleanup_thread = threading.Thread(target=cleanup_thread_target, args=(app,))
    cleanup_thread.daemon = True
    cleanup_thread.start()

    # Start the system stats collector thread in a native thread to avoid gevent conflicts
    stats_thread = native_threading.Thread(target=stats_collector_thread)
    stats_thread.daemon = True
    stats_thread.start()

    return app