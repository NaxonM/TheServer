#!/bin/sh
set -e
DATA_DIR="/data"
DB_FILE="${DATA_DIR}/proxy.db"
DOWNLOADS_DIR="${DATA_DIR}/downloads"

if [ ! -f "${DB_FILE}" ]; then
    echo "Database not found, skipping cleanup."
    exit 0
fi

# Use sqlite3 to get cleanup interval, with a fallback of 60 if it fails
CLEANUP_MINUTES=$(sqlite3 "${DB_FILE}" "SELECT value FROM setting WHERE key = 'cleanup_interval';" 2>/dev/null || echo "60")

# Simple numeric check for sh (more portable than bash regex)
case "$CLEANUP_MINUTES" in
    ''|*[!0-9]*) CLEANUP_MINUTES=60 ;;
esac

echo "Running cleanup. Deleting files in ${DOWNLOADS_DIR} older than ${CLEANUP_MINUTES} minutes..."
# Redirect find's potential errors to null in case the directory is empty, but still proceed
find "${DOWNLOADS_DIR}" -type f -mmin "+${CLEANUP_MINUTES}" -not -name "*.tmp" -print -delete 2>/dev/null || true
echo "Cleanup finished."