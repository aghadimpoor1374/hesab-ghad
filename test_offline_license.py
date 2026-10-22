import base64
import importlib.util
import json
from pathlib import Path
import unittest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives import serialization

base = Path(__file__).parent
source = base / 'windows-installer-kit/source/offline_license.py'
if not source.exists():
    source = base / 'source/offline_license.py'
spec = importlib.util.spec_from_file_location('offline_license', source)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def enc(data):
    return base64.urlsafe_b64encode(data).decode().rstrip('=')


class OfflineTests(unittest.TestCase):
    def setUp(self):
        self.key = Ed25519PrivateKey.generate()
        self.public = enc(self.key.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw))

    def code(self, identifier='first', days=20):
        payload = enc(json.dumps(dict(id=identifier, days=days)).encode())
        return 'HG1.' + payload + '.' + enc(self.key.sign(payload.encode()))

    def test_activation_and_expiry(self):
        code = self.code()
        state = module.activate(code, self.public, timestamp=1000)
        self.assertEqual(state['expires'], 1000 + 20 * 86400)
        self.assertEqual(module.activate(code, self.public, state, 1500)['expires'], state['expires'])
        with self.assertRaises(ValueError):
            module.activate(code, self.public, state, state['expires'])

    def test_renewal_preserves_time_and_prevents_reuse(self):
        first, second = self.code(), self.code('second', 365)
        state = module.activate(first, self.public, timestamp=1000)
        renewed = module.activate(second, self.public, state, timestamp=2000)
        self.assertEqual(renewed['expires'], state['expires'] + 365 * 86400)
        with self.assertRaises(ValueError):
            module.activate(first, self.public, renewed, timestamp=3000)

    def test_expired_can_renew(self):
        state = module.activate(self.code(), self.public, timestamp=1000)
        now = state['expires'] + 500
        renewed = module.activate(self.code('new'), self.public, state, timestamp=now)
        self.assertEqual(renewed['expires'], now + 20 * 86400)

    def test_clock_rollback(self):
        state = module.activate(self.code(), self.public, timestamp=1000)
        with self.assertRaises(ValueError):
            module.activate(self.code('new'), self.public, state, timestamp=1)

    def test_forgery(self):
        code = self.code()
        prefix, payload, signature = code.split('.')
        fake = enc(json.dumps(dict(id='first', days=365)).encode())
        with self.assertRaises(ValueError):
            module.verify('.'.join((prefix, fake, signature)), self.public)


if __name__ == '__main__':
    unittest.main()
