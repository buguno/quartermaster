"""Gunicorn settings (`poetry prod`), light enough for a Raspberry Pi.

One process with two threads is enough for a household and keeps RAM low, so
the same settings work on any machine. Everything can be overridden with an
environment variable (e.g. more workers on a bigger server).
"""

import os
from pathlib import Path

bind = os.environ.get('GUNICORN_BIND', '0.0.0.0:8000')  # noqa: S104
workers = int(os.environ.get('GUNICORN_WORKERS', '1'))
threads = int(os.environ.get('GUNICORN_THREADS', '2'))
worker_class = 'gthread'
timeout = int(os.environ.get('GUNICORN_TIMEOUT', '30'))

# Recycle the worker now and then so memory use cannot creep up on a Pi.
max_requests = 1000
max_requests_jitter = 100

# Heartbeat files in RAM when possible: avoids small writes to the SD card.
worker_tmp_dir = '/dev/shm' if Path('/dev/shm').is_dir() else None

# No extra control socket (one less moving part on the Pi).
control_socket_disable = True

# No per-request access log (chatty writes); errors go to stderr/journal.
accesslog = None
errorlog = '-'
loglevel = os.environ.get('GUNICORN_LOG_LEVEL', 'info')
