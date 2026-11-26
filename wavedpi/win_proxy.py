"""Loopback HTTP/HTTPS proxy for Windows clients that honor system proxy settings.

TLS is never decrypted: only the plaintext ClientHello handshake is optionally
split into two TLS records. No WinDivert driver, hosts-file edits or remote VPN.
"""
from __future__ import annotations

import json
import logging
import signal
import socket
import threading
import urllib.parse
import urllib.request
from pathlib import Path

from .core import MAX_RECORD, allowed_host, pipe, recv_exact, transform_record

LOG = logging.getLogger('wave-dpi')
MAX_HEADER = 16384
HEALTH_PATH = b'GET /__wave_dpi_health HTTP/1.1'
PROXY_HOST = '127.0.0.1'
PROXY_PORT = 18888


def resolve_ips(host: str, cfg: dict) -> list[str]:
    """Use direct DoH for selected domains, then fall back to OS resolver."""
    ip_addrs: list[str] = []
    if allowed_host(host, cfg):
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        for resolver in ('https://cloudflare-dns.com/dns-query', 'https://dns.google/resolve'):
            try:
                url = resolver + '?' + urllib.parse.urlencode({'name': host, 'type': 'A'})
                request = urllib.request.Request(url, headers={'Accept': 'application/dns-json'})
                with opener.open(request, timeout=3) as response:
                    data = json.loads(response.read(100000))
                for answer in data.get('Answer', ()):
                    if answer.get('type') == 1:
                        ip_addrs.append(str(answer['data']))
                if ip_addrs:
                    break
            except (OSError, ValueError, KeyError):
                LOG.debug('DoH lookup failed for %s using %s', host, resolver)
    if not ip_addrs:
        ip_addrs = [item[4][0] for item in socket.getaddrinfo(host, None, socket.AF_INET, socket.SOCK_STREAM)]
    return list(dict.fromkeys(ip_addrs))


def connect_upstream(host: str, port: int, cfg: dict) -> socket.socket:
    last_error = None
    for ip in resolve_ips(host, cfg):
        try:
            return socket.create_connection((ip, port), timeout=8)
        except OSError as exc:
            last_error = exc
    raise last_error or OSError('No upstream addresses')


def read_headers(client: socket.socket) -> tuple[bytes, bytes]:
    buf = bytearray()
    while b'\r\n\r\n' not in buf and len(buf) < MAX_HEADER:
        data = client.recv(min(2048, MAX_HEADER - len(buf)))
        if not data:
            break
        buf.extend(data)
    head, sep, trailing = bytes(buf).partition(b'\r\n\r\n')
    if not sep:
        raise ValueError('Malformed proxy HTTP request')
    return head + sep, trailing


def parse_request(header: bytes) -> tuple[str, str, int, bytes]:
    """Return (HTTP method, destination host, port, rewritten header)."""
    first, _, remainder = header.partition(b'\r\n')
    tokens = first.decode('latin-1').split(' ')
    if len(tokens) != 3:
        raise ValueError('Malformed request line')
    method, target, version = tokens
    if method.upper() == 'CONNECT':
        host, sep, port = target.rpartition(':')
        if not sep:
            host, port = target, '443'
        port_num = int(port)
        if not host or not 1 <= port_num <= 65535:
            raise ValueError('Invalid CONNECT destination')
        return 'CONNECT', host.strip('[]'), port_num, b''
    parsed = urllib.parse.urlsplit(target)
    if parsed.scheme not in ('http', 'https') or not parsed.hostname:
        raise ValueError('Unsupported HTTP proxy request')
    if parsed.scheme == 'https':
        raise ValueError('HTTPS requires CONNECT')
    path = urllib.parse.urlunsplit(('', '', parsed.path or '/', parsed.query, ''))
    # Proxy-Connection is hop-by-hop; don't forward it to origin servers.
    headers = [row for row in remainder.split(b'\r\n') if not row.lower().startswith(b'proxy-connection:')]
    replacement = f'{method} {path} {version}\r\n'.encode('latin-1') + b'\r\n'.join(headers)
    return method.upper(), parsed.hostname, parsed.port or 80, replacement


def handle_client(client: socket.socket, cfg: dict) -> None:
    upstream = None
    try:
        client.settimeout(10)
        header, trailing = read_headers(client)
        if header.startswith(HEALTH_PATH + b'\r\n'):
            body = b'WaveDPI/1\n'
            client.sendall(b'HTTP/1.1 200 OK\r\nContent-Type: text/plain\r\n' +
                           f'Content-Length: {len(body)}\r\n\r\n'.encode('ascii') + body)
            return
        method, host, port, rewritten = parse_request(header)
        upstream = connect_upstream(host, port, cfg)
        if method == 'CONNECT':
            client.sendall(b'HTTP/1.1 200 Connection Established\r\n\r\n')
            first = bytearray(trailing)
            while len(first) < 5:
                fragment = client.recv(5 - len(first))
                if not fragment:
                    break
                first.extend(fragment)
            if len(first) >= 5 and first[0] == 22:
                tls_length = int.from_bytes(first[3:5], 'big')
                if 0 < tls_length <= MAX_RECORD:
                    while len(first) < tls_length + 5:
                        chunk = client.recv(tls_length + 5 - len(first))
                        if not chunk:
                            break
                        first.extend(chunk)
                    complete = bytes(first[:tls_length + 5])
                    if len(complete) == tls_length + 5:
                        updated, sni, changed = transform_record(complete, cfg)
                        upstream.sendall(updated)
                        if changed:
                            LOG.info('Split TLS ClientHello for %s', sni)
                        first = first[tls_length + 5:]
            if first:
                upstream.sendall(first)
        else:
            upstream.sendall(rewritten + trailing)
        client.settimeout(None)
        upstream.settimeout(None)
        reverse = threading.Thread(target=pipe, args=(upstream, client), daemon=True)
        reverse.start()
        pipe(client, upstream)
        reverse.join(timeout=2)
    except (OSError, ValueError, TimeoutError) as error:
        LOG.debug('Proxy connection error: %s', error)
        try:
            if upstream is None:
                client.sendall(b'HTTP/1.1 502 Bad Gateway\r\nContent-Length: 0\r\n\r\n')
        except OSError:
            pass
    finally:
        client.close()
        if upstream:
            upstream.close()


def serve_windows(cfg: dict, port: int = PROXY_PORT) -> None:
    running = threading.Event()
    running.set()
    def shutdown(_signal, _frame):
        running.clear()
    signal.signal(signal.SIGTERM, shutdown)
    signal.signal(signal.SIGINT, shutdown)
    logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        listener.bind((PROXY_HOST, port))
        listener.listen(128)
        listener.settimeout(.5)
        LOG.info('Windows proxy listening on %s:%s', PROXY_HOST, port)
        while running.is_set():
            try:
                client, _ = listener.accept()
            except socket.timeout:
                continue
            except OSError:
                break
            threading.Thread(target=handle_client, args=(client, cfg), daemon=True).start()
