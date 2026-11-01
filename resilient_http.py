"""Bounded GET retries; TLS verification remains enabled and URLs are never logged."""
import os
import random
import socket
import ssl
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime


def retryable(exc):
    if isinstance(exc, urllib.error.HTTPError):
        return exc.code in (408, 429, 500, 502, 503, 504)
    reason = exc.reason if isinstance(exc, urllib.error.URLError) else exc
    if isinstance(reason, ssl.SSLCertVerificationError):
        return False
    return isinstance(reason, (TimeoutError, socket.timeout, ConnectionError, socket.gaierror))


def retry_after(exc):
    value = exc.headers.get('Retry-After') if isinstance(exc, urllib.error.HTTPError) and exc.headers else None
    if not value:
        return 0
    try:
        return max(0, float(value))
    except ValueError:
        try:
            return max(0, (parsedate_to_datetime(value) - datetime.now(timezone.utc)).total_seconds())
        except (ValueError, TypeError, OverflowError):
            return 0


def get_text(url):
    attempts = max(1, min(6, int(os.getenv('RTMS_HTTP_ATTEMPTS', '4'))))
    timeout = max(10, min(180, float(os.getenv('RTMS_HTTP_TIMEOUT', '90'))))
    for attempt in range(attempts):
        try:
            with urllib.request.urlopen(url, timeout=min(180, timeout + attempt * 30)) as response:
                return response.read().decode('utf-8')
        except (urllib.error.URLError, TimeoutError, ConnectionError, socket.gaierror) as exc:
            if not retryable(exc) or attempt + 1 == attempts:
                raise RuntimeError(f'HTTP request exhausted or non-retryable: {type(exc).__name__}') from None
            wait = max(min(60, 3 * 2**attempt + random.uniform(0, 1)), retry_after(exc))
            if wait > 120:
                raise RuntimeError('Server requested a cooldown beyond retry budget') from None
            print(f'[HTTP retry {attempt + 1}/{attempts - 1}] {type(exc).__name__}; wait={wait:.1f}s', flush=True)
            time.sleep(wait)
