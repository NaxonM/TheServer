# This file will contain helper functions.
import re
import socket
from urllib.parse import urlparse
from ipaddress import ip_address, AddressValueError

def get_filename_from_headers(headers):
    if cd := headers.get('content-disposition'):
        if filenames := re.findall('filename="(.+?)"', cd):
            return filenames[0]
    return None

def is_safe_url(url):
    """
    Checks if a URL is safe to be requested by the server.
    It prevents requests to private, reserved, or loopback IP addresses.
    """
    try:
        hostname = urlparse(url).hostname
        if not hostname:
            return False

        ip = ip_address(socket.gethostbyname(hostname))
        return ip.is_global and not ip.is_multicast
    except (socket.gaierror, AddressValueError, ValueError):
        # Could not resolve hostname or invalid IP, treat as unsafe.
        return False

import os
from collections import deque

def read_last_n_lines(filepath, n):
    """
    Reads the last n lines of a file efficiently without reading the entire
    file into memory. It seeks to the end and reads backwards.
    """
    try:
        if not os.path.exists(filepath) or os.path.getsize(filepath) == 0:
            return []

        with open(filepath, "rb") as f:
            f.seek(0, os.SEEK_END)
            buffer = bytearray()
            end_pos = f.tell()
            lines_found = 0

            while lines_found <= n and end_pos > 0:
                # Seek backwards from current position
                seek_pos = max(0, end_pos - 1024)
                f.seek(seek_pos)

                # Prepend read chunk to our buffer
                buffer = f.read(end_pos - seek_pos) + buffer
                end_pos = seek_pos

                # Count newlines in the current buffer
                lines_found = buffer.count(b'\n')

            # Decode buffer and split into lines
            lines = buffer.decode('utf-8', errors='ignore').splitlines()

            # Return the last n lines
            return lines[-n:]

    except FileNotFoundError:
        return [] # Log file might not have been created yet.
    except Exception as e:
        # Broad exception to ensure the log reader itself doesn't crash the app.
        return [f"Error reading log file: {e}"]