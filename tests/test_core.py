"""Pure local tests: no root privileges, firewall changes or network needed."""
import ssl
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from wavedpi.core import DEFAULTS, allowed_host, find_sni, transform_record


def client_hello(host='gateway.discord.gg'):
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    out, incoming = ssl.MemoryBIO(), ssl.MemoryBIO()
    obj = ctx.wrap_bio(incoming, out, server_hostname=host)
    try:
        obj.do_handshake()
    except ssl.SSLWantReadError:
        pass
    return out.read()


class CoreTests(unittest.TestCase):
    def test_real_client_hello_sni(self):
        record = client_hello()
        self.assertEqual(find_sni(record[5:])[0], 'gateway.discord.gg')

    def test_sni_split_preserves_tls_handshake(self):
        record = client_hello()
        cfg = dict(DEFAULTS)
        out, host, changed = transform_record(record, cfg)
        self.assertTrue(changed)
        self.assertEqual(host, 'gateway.discord.gg')
        first = int.from_bytes(out[3:5], 'big')
        p2 = first + 5
        self.assertEqual(out[p2], 22)
        self.assertEqual(out[1:3], out[p2 + 1:p2 + 3])
        self.assertEqual(out[5:p2] + out[p2 + 5:], record[5:])
        self.assertEqual(int.from_bytes(out[p2 + 3:p2 + 5], 'big'), len(out) - p2 - 5)

    def test_other_sites_untouched(self):
        record = client_hello('example.org')
        self.assertEqual(transform_record(record, DEFAULTS), (record, 'example.org', False))

    def test_domain_not_suffix_attack(self):
        self.assertFalse(allowed_host('evil-discord.com', DEFAULTS))
        self.assertFalse(allowed_host('discord.com.evil.com', DEFAULTS))
        self.assertTrue(allowed_host('media.discordapp.net', DEFAULTS))

    def test_custom_mode(self):
        cfg = {**DEFAULTS, 'mode': 'custom', 'hosts': ['example.org']}
        self.assertTrue(allowed_host('a.example.org', cfg))
        self.assertFalse(allowed_host('a.discord.com', cfg))

    def test_passthrough(self):
        cfg = {**DEFAULTS, 'strategy': 'passthrough', 'mode': 'all'}
        rec = client_hello()
        self.assertEqual(transform_record(rec, cfg)[0], rec)


if __name__ == '__main__':
    unittest.main()
