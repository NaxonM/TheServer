import os
from flask_limiter.util import get_remote_address

class Config:
    SECRET_KEY = os.environ['SECRET_KEY']
    SERVER_NAME = os.environ.get('SERVER_NAME')
    SQLALCHEMY_DATABASE_URI = 'sqlite:////data/proxy.db'
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    DOWNLOADS_DIR = '/data/downloads'
    LOG_DIR = '/data'
    LOG_FILE = os.path.join(LOG_DIR, 'app.log')
    RATELIMIT_STORAGE_URI = "redis://redis:6379/0"
    RATELIMIT_DEFAULT = "200 per day;50 per hour"
    RATELIMIT_KEY_FUNC = get_remote_address