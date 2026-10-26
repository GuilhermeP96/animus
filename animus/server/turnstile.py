"""Server-side Turnstile validation for human login; no peer/API authentication changes."""
from __future__ import annotations
import asyncio
import json
import os
import re
import time
from datetime import datetime
from urllib.parse import urlencode
from urllib.request import Request, urlopen

ENDPOINT = 'https://challenges.cloudflare.com/turnstile/v0/siteverify'

class TurnstileError(Exception):
    def __init__(self, status=403):
        self.status = status
        super().__init__('A verificação de segurança não foi concluída. Seus dados foram preservados; tente novamente.')

def public_config():
    return {'enabled': True, 'siteKey': os.environ.get('TURNSTILE_SITE_KEY', '') or None}

def _siteverify(secret, token):
    request = Request(ENDPOINT, data=urlencode({'secret': secret, 'response': token}).encode(),
                      headers={'Content-Type':'application/x-www-form-urlencoded'}, method='POST')
    with urlopen(request, timeout=8) as response:
        if response.status != 200:
            raise TurnstileError(503)
        data = response.read(16385)
        if len(data) > 16384:
            raise TurnstileError(503)
        return json.loads(data)

async def verify_turnstile(token, action='login', *, transport=None, now=None):
    secret = os.environ.get('TURNSTILE_SECRET_KEY') or os.environ.get('TURNSTILE_SECRET', '')
    hosts = [host.strip() for host in os.environ.get('TURNSTILE_HOSTNAMES', '').split(',') if host.strip()]
    if not secret or not os.environ.get('TURNSTILE_SITE_KEY') or len(hosts) != 1 or \
       not re.fullmatch(r'[a-z0-9](?:[a-z0-9.-]*[a-z0-9])?', hosts[0]) or \
       hosts[0] in ('localhost','127.0.0.1','0.0.0.0') or '.' not in hosts[0]:
        raise TurnstileError(503)
    if action != 'login' or not isinstance(token, str) or not 0 < len(token) <= 2048 or re.search(r'\s', token):
        raise TurnstileError()
    try:
        result = await asyncio.wait_for(asyncio.to_thread(transport or _siteverify, secret, token), timeout=9)
    except Exception:
        raise TurnstileError(503) from None
    if not isinstance(result, dict):
        raise TurnstileError()
    errors = result.get('error-codes', [])
    try:
        timestamp = datetime.fromisoformat(result['challenge_ts'].replace('Z', '+00:00')).timestamp()
        age = (time.time() if now is None else now) - timestamp
    except (ValueError, KeyError, TypeError, AttributeError, OverflowError):
        raise TurnstileError() from None
    if result.get('success') is not True or result.get('action') != action or result.get('hostname') != hosts[0] or \
       'error' in result or not isinstance(errors, list) or errors or not -5 <= age <= 300:
        raise TurnstileError()
