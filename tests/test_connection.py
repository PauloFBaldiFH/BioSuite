import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from urllib.error import URLError

from biosuite.connection import BrokerClient
from biosuite.operations import OperationError


class Opener:
    def __init__(self, *responses):
        self.responses = list(responses)
        self.requests = []
    def open(self, request, timeout):
        self.requests.append(request)
        value = self.responses.pop(0)
        if isinstance(value, Exception):
            raise value
        return io.BytesIO(json.dumps(value).encode())


class ConnectionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name) / 'client'
        self.client = BrokerClient('http://localhost:8000', self.root)

    def test_original_koha_broker_is_not_assumed_compatible(self):
        self.client.opener = Opener({'services': ['koha', 'tainacan']})
        with self.assertRaisesRegex(OperationError, 'adaptação Galaxy'):
            self.client.start('Test Lab', 'lab@example.org', 'test-lab', 8081)
        self.assertFalse(self.client.key.exists())

    def test_enrollment_keeps_secret_fields_private_and_does_not_repeat(self):
        self.client.opener = Opener({'application': 'galaxy', 'origin_port_configurable': True},
                                   {'device_code': 'private-device-code', 'status': 'approved', 'user_code': 'ABCD-EFGH'},
                                   {'library_id': 'abc-123', 'hostnames': {'galaxy': 'bio-lab.example.org'}},
                                   {'id': 'abc-123', 'status': 'active', 'hostnames': {'galaxy': 'bio-lab.example.org'}})
        public = self.client.start('Test Lab', 'lab@example.org', 'test-lab', 8081)
        self.assertNotIn('private-device-code', json.dumps(public))
        payload = json.loads(self.client.opener.requests[1].data)
        self.assertEqual(payload['origin_port'], 8081)
        self.assertEqual(payload['services'], ['galaxy'])
        self.client.enroll()
        self.client.enroll()
        self.assertEqual(self.client.public_state()['status'], 'active')
        methods = [r.method for r in self.client.opener.requests]
        self.assertEqual(methods.count('POST'), 2)
        self.assertEqual(self.client.key.stat().st_mode & 0o777, 0o600)
        self.assertEqual(self.client.file.stat().st_mode & 0o777, 0o600)

    def test_lost_enrollment_response_is_not_replayed(self):
        self.client.identity()
        self.client.save({'broker': self.client.url, 'device_code': 'device', 'status': 'approved'})
        self.client.opener = Opener(URLError('network unavailable'))
        with self.assertRaises(OperationError):
            self.client.enroll()
        with self.assertRaisesRegex(OperationError, 'matrícula já foi enviada'):
            self.client.enroll()
        self.assertEqual(len(self.client.opener.requests), 1)

    def test_activate_uses_private_file_and_systemd_credentials_not_token_argument(self):
        self.client.identity()
        self.client.save({'broker': self.client.url, 'library_id': 'abc-123', 'status': 'active'})
        self.client.opener = Opener({'tunnel_token': 'FAKE-PRIVATE-TUNNEL-TOKEN'})
        units = Path(self.tmp.name) / 'units'
        units.mkdir()
        with patch('biosuite.connection.require_root'), patch('biosuite.connection.shutil.which', return_value='/usr/bin/cloudflared'), \
             patch('biosuite.connection.SERVICE_DIR', units), \
             patch('biosuite.connection.capture', side_effect=['--token-file', '', '', '', 'active']) as capture:
            result = self.client.activate()
        text = (units / 'biosuite-cloudflared.service').read_text()
        self.assertIn('LoadCredential=tunnel-token:', text)
        self.assertIn('%d/tunnel-token', text)
        self.assertNotIn('FAKE-PRIVATE-TUNNEL-TOKEN', text)
        self.assertNotIn('FAKE-PRIVATE-TUNNEL-TOKEN', repr(capture.call_args_list))
        self.assertNotIn('FAKE-PRIVATE-TUNNEL-TOKEN', repr(result))
        self.assertEqual((self.root / 'tunnel.token').stat().st_mode & 0o777, 0o600)

    def test_recovery_round_trip_preserves_key_without_overwriting_identity(self):
        public = self.client.identity()
        self.client.save({'broker': self.client.url, 'library_id': 'abc-123', 'status': 'active'})
        export = Path(self.tmp.name) / 'recovery.json'
        message = self.client.export_recovery(export)
        self.assertNotIn('PRIVATE KEY', message)
        self.assertEqual(export.stat().st_mode & 0o777, 0o600)
        restored = BrokerClient(self.client.url, Path(self.tmp.name) / 'restored')
        restored.opener = Opener({'id': 'abc-123', 'status': 'active'})
        restored.import_recovery(export)
        self.assertEqual(restored.identity(), public)
        with self.assertRaisesRegex(OperationError, 'não será sobrescrita'):
            restored.import_recovery(export)

    def test_only_confirmed_expired_or_denied_request_can_be_reset(self):
        self.client.identity()
        public = self.client.identity()
        self.client.save({'broker': self.client.url, 'device_code': 'device', 'status': 'pending'})
        self.client.opener = Opener({'status': 'pending'}, {'status': 'expired'})
        with self.assertRaisesRegex(OperationError, 'ainda não'):
            self.client.reset_pending()
        self.client.reset_pending()
        self.assertFalse(self.client.state())
        self.assertEqual(self.client.identity(), public)
        self.client.save({'broker': self.client.url, 'device_code': 'device', 'enrollment_sent': True})
        with self.assertRaisesRegex(OperationError, 'exige recuperação'):
            self.client.reset_pending()
