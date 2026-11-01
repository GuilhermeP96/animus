"""Offline provider-boundary regressions; no production endpoint is contacted."""
import os
import time
import unittest
from datetime import datetime, timezone
from unittest.mock import patch
from animus.server import turnstile

ENV={'TURNSTILE_SITE_KEY':'fixture-public','TURNSTILE_SECRET_KEY':'fixture-protected','TURNSTILE_SECRET':'','TURNSTILE_HOSTNAMES':'app.example.test'}

def accepted(**patches):
    return {'success':True,'action':'login','hostname':'app.example.test','challenge_ts':datetime.now(timezone.utc).isoformat(),**patches}

class TurnstileTests(unittest.IsolatedAsyncioTestCase):
    async def test_valid_token_sent_only_to_canonical_provider_transport(self):
        captured=[]
        def transport(secret,token):
            captured.append((secret,token))
            return accepted()
        with patch.dict(os.environ,ENV):
            await turnstile.verify_turnstile('fixture-token',transport=transport)
        self.assertEqual(captured,[('fixture-protected','fixture-token')])
        self.assertEqual(turnstile.ENDPOINT,'https://challenges.cloudflare.com/turnstile/v0/siteverify')

    async def test_rejections_and_no_permissive_scores(self):
        cases=[{'success':False},{'success':'true'},{'success':1},{'action':'register'},
               {'hostname':'attacker.example.test'},{'challenge_ts':'invalid'},
               {'challenge_ts':datetime.fromtimestamp(time.time()-301,timezone.utc).isoformat()},
               {'challenge_ts':datetime.fromtimestamp(time.time()+10,timezone.utc).isoformat()},
               {'error-codes':['timeout-or-duplicate']},{'error-codes':'unexpected'},{'error':'quota'}]
        with patch.dict(os.environ,ENV):
            for values in cases:
                with self.subTest(values=values),self.assertRaises(turnstile.TurnstileError) as denied:
                    await turnstile.verify_turnstile('fixture-token',transport=lambda *args:accepted(**values))
                self.assertEqual(denied.exception.status,403)
            for token in [None,'','token with spaces','x'*2049]:
                with self.subTest(token=type(token)),self.assertRaises(turnstile.TurnstileError) as denied:
                    await turnstile.verify_turnstile(token,transport=lambda *args:self.fail('No transport for invalid token'))
                self.assertEqual(denied.exception.status,403)

    async def test_configuration_and_provider_outage_fail_closed(self):
        for values in [{'TURNSTILE_SECRET_KEY':''},{'TURNSTILE_SITE_KEY':''},{'TURNSTILE_HOSTNAMES':''},
                       {'TURNSTILE_HOSTNAMES':'localhost'},{'TURNSTILE_HOSTNAMES':'app.example.test,localhost'}]:
            with patch.dict(os.environ,{**ENV,**values}),self.assertRaises(turnstile.TurnstileError) as denied:
                await turnstile.verify_turnstile('fixture-token',transport=lambda *args:self.fail('No transport with invalid config'))
            self.assertEqual(denied.exception.status,503)
        def unavailable(*args):raise OSError('private-provider-diagnostic')
        with patch.dict(os.environ,ENV),self.assertRaises(turnstile.TurnstileError) as denied:
            await turnstile.verify_turnstile('fixture-token',transport=unavailable)
        self.assertEqual(denied.exception.status,503)
        self.assertNotIn('private-provider-diagnostic',str(denied.exception))
