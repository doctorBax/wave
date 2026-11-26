"""Portable unit tests for Windows proxy request parsing; no Windows registry needed."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from wavedpi.win_proxy import parse_request


class WindowsProxyTests(unittest.TestCase):
    def test_connect(self):
        method, host, port, forwarded = parse_request(
            b'CONNECT gateway.discord.gg:443 HTTP/1.1\r\nHost: gateway.discord.gg:443\r\n\r\n')
        self.assertEqual((method, host, port, forwarded), ('CONNECT', 'gateway.discord.gg', 443, b''))

    def test_plain_http_forwarding(self):
        header = b'GET http://example.org/a?q=1 HTTP/1.1\r\nHost: example.org\r\nProxy-Connection: keep-alive\r\n\r\n'
        method, host, port, forwarded = parse_request(header)
        self.assertEqual((method, host, port), ('GET', 'example.org', 80))
        self.assertIn(b'GET /a?q=1 HTTP/1.1\r\n', forwarded)
        self.assertNotIn(b'Proxy-Connection', forwarded)

    def test_reject_non_connect_https(self):
        with self.assertRaises(ValueError):
            parse_request(b'GET https://example.org/ HTTP/1.1\r\nHost: example.org\r\n\r\n')


if __name__ == '__main__':
    unittest.main()
