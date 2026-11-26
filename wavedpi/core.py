"""Wave DPI TCP/TLS interception engine (IPv4 only)."""
from __future__ import annotations

import json
import logging
import signal
import socket
import struct
import threading
from pathlib import Path

CONFIG_FILE = Path('/etc/wave-dpi/config.json')
LOG = logging.getLogger('wave-dpi')
DEFAULTS = {'port': 18443, 'strategy': 'record-sni', 'mode': 'discord', 'hosts': [], 'handshake_timeout': 6}
DISCORD = ('discord.com', 'discord.gg', 'discordapp.com', 'discordapp.net',
           'discord.media', 'discordcdn.com', 'discordstatus.com')
SO_ORIGINAL_DST = 80  # Linux netfilter, IPv4
MAX_RECORD = 32768


def load_config(path=CONFIG_FILE):
    data = dict(DEFAULTS)
    try:
        user = json.loads(Path(path).read_text(encoding='utf-8'))
        if isinstance(user, dict):
            data.update({key: user[key] for key in DEFAULTS if key in user})
    except FileNotFoundError:
        pass
    if data['strategy'] not in ('record-sni', 'record-mid', 'passthrough'):
        raise ValueError('Invalid TLS strategy')
    if data['mode'] not in ('discord', 'custom', 'all'):
        raise ValueError('Invalid host mode')
    if not isinstance(data['hosts'], list) or not all(isinstance(x, str) for x in data['hosts']):
        raise ValueError('Invalid hosts')
    if not isinstance(data['port'], int) or not 1024 <= data['port'] <= 65535:
        raise ValueError('Invalid listen port')
    return data


def allowed_host(hostname: str | None, cfg: dict) -> bool:
    if not hostname or cfg['strategy'] == 'passthrough':
        return False
    if cfg['mode'] == 'all':
        return True
    domains = DISCORD if cfg['mode'] == 'discord' else cfg['hosts']
    name = hostname.rstrip('.').lower()
    return any(name == domain.lower() or name.endswith('.' + domain.lower()) for domain in domains)


def find_sni(payload: bytes) -> tuple[str | None, int | None]:
    """Parse a single unencrypted TLS ClientHello; offset is within payload."""
    if len(payload) < 42 or payload[0] != 1:
        return None, None
    handshake_len = int.from_bytes(payload[1:4], 'big')
    if handshake_len + 4 > len(payload):
        return None, None
    end = handshake_len + 4
    pos = 4 + 2 + 32
    try:
        sid = payload[pos]
        pos += 1 + sid
        suites = int.from_bytes(payload[pos:pos + 2], 'big')
        pos += 2 + suites
        methods = payload[pos]
        pos += 1 + methods
        extlen = int.from_bytes(payload[pos:pos + 2], 'big')
        pos += 2
        ext_end = pos + extlen
        if ext_end > end:
            return None, None
        while pos + 4 <= ext_end:
            etype = int.from_bytes(payload[pos:pos + 2], 'big')
            elen = int.from_bytes(payload[pos + 2:pos + 4], 'big')
            pos += 4
            if pos + elen > ext_end:
                return None, None
            if etype == 0 and elen >= 5:
                sniend = pos + elen
                q = pos + 2
                while q + 3 <= sniend:
                    name_type = payload[q]
                    name_len = int.from_bytes(payload[q + 1:q + 3], 'big')
                    q += 3
                    if q + name_len > sniend:
                        return None, None
                    if name_type == 0:
                        hostname = payload[q:q + name_len].decode('ascii').lower()
                        return hostname, q
                    q += name_len
            pos += elen
    except (IndexError, UnicodeDecodeError, ValueError):
        return None, None
    return None, None


def transform_record(record: bytes, cfg: dict) -> tuple[bytes, str | None, bool]:
    if len(record) < 5 or record[0] != 22:
        return record, None, False
    size = int.from_bytes(record[3:5], 'big')
    if len(record) != size + 5:
        return record, None, False
    payload = record[5:]
    hostname, off = find_sni(payload)
    if not allowed_host(hostname, cfg):
        return record, hostname, False
    if cfg['strategy'] == 'record-sni' and off is not None:
        split = off + max(1, len(hostname) // 2)
    else:
        split = len(payload) // 2
    if not 0 < split < len(payload):
        return record, hostname, False
    # The TLS handshake spans two valid TLS records. Payload bytes are unchanged.
    version = record[1:3]
    a, b = payload[:split], payload[split:]
    return (b'\x16' + version + len(a).to_bytes(2, 'big') + a +
            b'\x16' + version + len(b).to_bytes(2, 'big') + b), hostname, True


def original_destination(client):
    raw = client.getsockopt(socket.SOL_IP, SO_ORIGINAL_DST, 16)
    return socket.inet_ntoa(raw[4:8]), struct.unpack('!H', raw[2:4])[0]


def recv_exact(conn, count):
    buffer = bytearray()
    while len(buffer) < count:
        part = conn.recv(count - len(buffer))
        if not part:
            break
        buffer.extend(part)
    return bytes(buffer)


def pipe(source, target):
    try:
        while True:
            data = source.recv(65536)
            if not data:
                break
            target.sendall(data)
    except (OSError, TimeoutError):
        pass
    finally:
        try:
            target.shutdown(socket.SHUT_WR)
        except OSError:
            pass


def session(client, config):
    upstream = None
    try:
        client.settimeout(float(config['handshake_timeout']))
        destination = original_destination(client)
        upstream = socket.create_connection(destination, timeout=10)
        # Read just the first record; do not buffer or rewrite application data.
        header = recv_exact(client, 5)
        if len(header) != 5 or header[0] != 22:
            upstream.sendall(header)
        else:
            length = int.from_bytes(header[3:5], 'big')
            if length <= 0 or length > MAX_RECORD:
                upstream.sendall(header)
            else:
                original = header + recv_exact(client, length)
                output, hostname, changed = transform_record(original, config)
                upstream.sendall(output)
                if changed:
                    LOG.info('TLS record split: %s -> %s', hostname, destination[0])
        client.settimeout(None)
        upstream.settimeout(None)
        incoming = threading.Thread(target=pipe, args=(upstream, client), daemon=True)
        incoming.start()
        pipe(client, upstream)
        incoming.join(timeout=3)
    except (OSError, ValueError) as error:
        LOG.debug('connection error: %s', error)
    finally:
        try:
            client.close()
        except OSError:
            pass
        if upstream:
            try:
                upstream.close()
            except OSError:
                pass


def serve():
    logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')
    config = load_config()
    active = threading.Event()
    active.set()
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        listener.bind(('127.0.0.1', config['port']))
        listener.listen(256)
        listener.settimeout(0.8)
        def shutdown(_signum, _frame):
            active.clear()
        signal.signal(signal.SIGTERM, shutdown)
        signal.signal(signal.SIGINT, shutdown)
        LOG.info('Wave DPI started: 127.0.0.1:%s, mode=%s, strategy=%s',
                 config['port'], config['mode'], config['strategy'])
        while active.is_set():
            try:
                client, _address = listener.accept()
            except socket.timeout:
                continue
            except OSError:
                break
            threading.Thread(target=session, args=(client, config), daemon=True).start()
    LOG.info('Wave DPI stopped')
