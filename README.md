# Wave DPI

A lightweight, local TCP/TLS bypass experiment for Linux. **Not a VPN.** The engine works on encrypted ClientHello records without decrypting the session, runs as a dedicated unprivileged user, and provides a Russian arrow-key TUI.

## Install (one command)

This GitHub repository is **private**. Sign in with GitHub CLI (`gh auth login`) and run:

```sh
tmp=$(mktemp -d) && gh repo clone doctorBax/wave "$tmp" -- -q && sudo bash "$tmp/install.sh"
```

Requires Linux with **systemd, iptables, and Python 3**, plus `git` and an authenticated `gh` for the private checkout. The installer can install Python/iptables via apt, dnf, or pacman. Tested only by automated local tests, **not tested on Russian ISPs**. Review `install.sh` and `scripts/wave-dpi-net` before running as root.

```sh
sudo wave-dpi                # arrow-key UI
wave-dpi status
sudo wave-dpi start
sudo wave-dpi stop
sudo wave-dpi restart
sudo wave-dpi mode discord   # discord | custom | all
sudo wave-dpi strategy record-sni # record-sni | record-mid | passthrough
sudo wave-dpi add-host example.org
sudo wave-dpi delete-host example.org
wave-dpi logs
sudo wave-dpi-uninstall      # removes service, binaries, and NAT rule
```

## How it works

- systemd starts a Python proxy on `127.0.0.1:18443` as `wave-dpi`.
- A dedicated IPv4 `iptables` NAT rule redirects locally originated **TCP/443** to the proxy. Connections created by the `wave-dpi` user bypass the rule, avoiding loops.
- The proxy recovers the original destination with Linux `SO_ORIGINAL_DST` and connects directly to that IP.
- The first unencrypted TLS ClientHello is parsed for SNI. For the selected domain set, a single ClientHello is split into **two valid TLS handshake records** without modifying handshake bytes. Other connections are forwarded unchanged.
- `record-sni` splits inside the hostname, `record-mid` splits near the middle of the handshake, and `passthrough` performs no TLS rewriting. The service is restarted when changing settings.
- On stop, crash or restart, the systemd network helper removes the project's NAT rule. Rules are installed only after the proxy is listening.

**Limits:** The project does not support IPv6, UDP/QUIC, Discord voice, DNS-poisoning remediation, IP-block bypass, ECH or every DPI implementation. The firewall rule intercepts **all locally originated IPv4 TCP/443** traffic and forwards non-selected hosts unchanged, which can affect compatibility. No traffic is routed through a remote server. Site availability and success in Russia cannot be guaranteed. Stop the service with `sudo wave-dpi stop` to turn off redirection.

Config: `/etc/wave-dpi/config.json`. Logs: `journalctl -u wave-dpi.service`.

## Tests

```sh
python3 -m unittest discover -s tests -v
python3 -m compileall -q wavedpi launch.py
bash -n install.sh uninstall.sh scripts/wave-dpi-net
```

Tests do not require modifying the firewall. Integration tests on actual Linux iptables systems remain to be done. CI validates Python, syntax and the pure TLS transformations.
