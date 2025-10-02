FROM python:3.11-slim
WORKDIR /app
RUN pip install Flask Flask-SQLAlchemy Flask-Login gunicorn psutil requests Werkzeug Flask-Limiter Flask-WTF gevent redis python-slugify hqporner-api phub xvideos-api xnxx-api eporner-api youporn-api spankbang-api missav-api xhamster-api mutagen
COPY ./src /app
EXPOSE 8000
CMD ["gunicorn", "--workers", "4", "--worker-class", "gevent", "--bind", "0.0.0.0:8000", "wsgi:app"]