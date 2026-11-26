# Wave DPI

Local **experimental** DPI-bypass with an arrow-key terminal interface, for Linux and Windows. No third-party VPN server and no TLS decryption.

> **Important:** This repository must be **public** for the commands below to work without authentication. While it is private, GitHub returns 404/403 for anonymous downloads. There is no way to anonymously pull a private repository through a GitHub URL.

## Install without login (after making repository public)

### Linux

```bash
curl -fsSL https://raw.githubusercontent.com/doctorBax/wave/main/bootstrap.sh | sudo bash
```

Requires systemd and IPv4 iptables. Installer can install Python 3 and iptables on common distributions. No `gh` or `git` required. The installer creates a dedicated unprivileged `wave-dpi` account and systemd service.

Run: `sudo wave-dpi`. Disable: `sudo wave-dpi stop`. Remove: `sudo wave-dpi-uninstall`.

### Windows 10/11

Open **PowerShell** and run (regular user, no administrator privileges):

```powershell
irm https://raw.githubusercontent.com/doctorBax/wave/main/install.ps1 | iex
```

Installer downloads the repository archive and installs under `%LOCALAPPDATA%\WaveDPI`; uses installed Python if available, otherwise downloads an official embedded Python runtime. Open a new terminal to run `wave-dpi`. Uninstall with:

```powershell
& "$env:LOCALAPPDATA\WaveDPI\uninstall.ps1"
```

Windows uses a loopback **HTTP CONNECT system proxy** on `127.0.0.1:18888`. The proxy handles HTTPS TLS record splitting for configured hosts, standard HTTP proxy requests for other websites, and direct DNS-over-HTTPS for selected targets when possible. The old proxy configuration is backed up and restored on stop. If another proxy is already enabled, Wave DPI refuses to replace it automatically. The CLI has optional startup-at-logon control (`wave-dpi startup`). It does **not** affect applications that ignore Windows system proxy settings, and does not handle UDP, IPv6, or Discord voice. Windows build is **unit-tested only**, not yet live-tested on Windows or Russian ISP networks.

## CLI

The graphical terminal menu supports **↑/↓, Enter, Q/Esc**. It has start/stop/restart, mode, TLS strategy, domain list, logs; Windows also has auto-start toggle.

```text
wave-dpi status
wave-dpi start
wave-dpi stop
wave-dpi restart
wave-dpi mode discord         # discord | custom | all
wave-dpi strategy record-sni  # record-sni | record-mid | passthrough
wave-dpi add-host example.org
wave-dpi delete-host example.org
wave-dpi logs
```

On Linux, write commands and interactive menu require `sudo`. Windows is per-user and needs no administrator permissions. Do not set `mode all` unless needed; it modifies TLS ClientHello records for every TCP/443 connection on Linux and every HTTPS request using the proxy on Windows.

## How it works

- **Linux:** systemd starts local TCP proxy on `127.0.0.1:18443` as `wave-dpi`; an iptables IPv4 NAT rule redirects locally originated TCP/443. The proxy recovers the original destination with `SO_ORIGINAL_DST`, uses valid TLS record fragmentation, and forwards other connections unchanged. A dedicated uid avoids looping its own traffic.
- **Windows:** Windows system HTTP proxy is pointed to a loopback local Python proxy while Wave DPI is running; TCP HTTPS CONNECT connections are forwarded directly and only selected ClientHello handshakes are split into two valid TLS records. Plain HTTP proxy requests are also forwarded. Original proxy settings are restored when stopped normally.

**Limitations:** Not a VPN. No remote endpoint, TLS decryption, IP-block avoidance, UDP, Discord voice or guaranteed bypass. Windows is system-proxy-dependent; Linux applies to locally generated IPv4 TCP/443 traffic only. Other clients may be affected. IPv6 traffic may bypass this tool, and external DNS restrictions may interfere. Changes to system networking always carry a compatibility risk. Review installer scripts before running them.

## Tests

```bash
python3 -m unittest discover -s tests -v
python3 -m compileall -q wavedpi launch.py
bash -n bootstrap.sh install.sh uninstall.sh scripts/wave-dpi-net
```

GitHub CI runs Python unit tests on Ubuntu and Windows and checks shell/PowerShell syntax. Real-network behavior on Windows and Russian ISPs is **unverified**.
