"""Human login endpoint qualification; peer credentials and engine are not started."""
import os
from datetime import datetime,timezone
from unittest.mock import patch
from fastapi import FastAPI
from fastapi.testclient import TestClient
from animus.server import app as app_module
from animus.server import admin_routes,admin_auth,turnstile

def test_human_login_requires_fresh_token_and_preserves_peer_boundary():
    consumed=set()
    def provider(secret,token):
        valid=token not in consumed and token!='denied';consumed.add(token)
        return {'success':valid,'action':'login','hostname':'animus.datano.com.br','challenge_ts':datetime.now(timezone.utc).isoformat()}
    async def verify(token):await turnstile.verify_turnstile(token,transport=provider)
    app=FastAPI();app.include_router(admin_routes.router)
    with patch.dict(os.environ,{'TURNSTILE_SITE_KEY':'fixture-public','TURNSTILE_SECRET_KEY':'fixture-private','TURNSTILE_HOSTNAMES':'animus.datano.com.br'}),patch.multiple(admin_auth,ADMIN_USER='fixture',ADMIN_PASSWORD='fixture-password',_ADMIN_SECRET_RAW='fixture-session-secret',ADMIN_SECRET='fixture-session-secret',_ADMIN_INSECURE=False),patch.object(admin_routes,'verify_turnstile',verify),TestClient(app) as client:
        html=client.get('/login');assert html.status_code==200;assert 'fixture-public' in html.text;assert 'fixture-private' not in html.text;assert 'login-security.js' in html.text
        assert client.get('/login-security.js').status_code==200
        base={'username':'fixture','password':'fixture-password'}
        headers={'Accept':'application/json'}
        for token in ['', 'denied']:
            response=client.post('/login',data={**base,'cf-turnstile-response':token},headers=headers)
            assert response.status_code==403;assert 'set-cookie' not in response.headers
        response=client.post('/login',data={**base,'cf-turnstile-response':'fresh'},headers=headers)
        assert response.status_code==200;assert response.json()=={'redirect':'/admin'};assert 'HttpOnly' in response.headers['set-cookie']
        replay=client.post('/login',data={**base,'cf-turnstile-response':'fresh'},headers=headers)
        assert replay.status_code==403;assert 'set-cookie' not in replay.headers
