#!/usr/bin/env bash
set -euo pipefail
[[ $EUID -eq 0 ]] || { echo 'Запуск: sudo bash install.sh' >&2; exit 1; }
[[ "$(uname -s)" == Linux ]] || { echo 'Поддерживается только Linux' >&2; exit 1; }
command -v systemctl >/dev/null || { echo 'Нужен systemd' >&2; exit 1; }
SOURCE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
for file in "$SOURCE/launch.py" "$SOURCE/wavedpi/core.py" "$SOURCE/wavedpi/cli.py" "$SOURCE/scripts/wave-dpi-net"; do
  [[ -f "$file" ]] || { echo "Нет файла: $file" >&2; exit 1; }
done
if ! command -v python3 >/dev/null || ! command -v iptables >/dev/null; then
  if command -v apt-get >/dev/null; then
    apt-get update && DEBIAN_FRONTEND=noninteractive apt-get install -y python3 iptables
  elif command -v dnf >/dev/null; then
    dnf install -y python3 iptables
  elif command -v pacman >/dev/null; then
    pacman -Sy --noconfirm python iptables
  else
    echo 'Установи Python 3 и iptables, затем повтори' >&2; exit 1
  fi
fi
if ! id wave-dpi >/dev/null 2>&1; then
  useradd --system --no-create-home --shell "$(command -v nologin || echo /bin/false)" wave-dpi
fi
# Stop old installation first to remove any old NAT rule.
systemctl stop wave-dpi.service 2>/dev/null || true
install -d -m 755 /opt/wave-dpi/wavedpi /etc/wave-dpi /usr/local/libexec
install -m 644 "$SOURCE/wavedpi/"*.py /opt/wave-dpi/wavedpi/
install -m 755 "$SOURCE/launch.py" /opt/wave-dpi/launch.py
install -m 755 "$SOURCE/scripts/wave-dpi-net" /usr/local/libexec/wave-dpi-net
install -m 755 "$SOURCE/uninstall.sh" /usr/local/bin/wave-dpi-uninstall
cat >/usr/local/bin/wave-dpi <<'WRAPPER'
#!/bin/sh
exec /usr/bin/python3 /opt/wave-dpi/launch.py "$@"
WRAPPER
chmod 755 /usr/local/bin/wave-dpi
if [[ ! -e /etc/wave-dpi/config.json ]]; then
  cat >/etc/wave-dpi/config.json <<'JSON'
{
  "port": 18443,
  "mode": "discord",
  "strategy": "record-sni",
  "hosts": [],
  "handshake_timeout": 6
}
JSON
fi
chmod 644 /etc/wave-dpi/config.json
install -m 644 "$SOURCE/systemd/wave-dpi.service" /etc/systemd/system/wave-dpi.service
systemctl daemon-reload
systemctl enable --now wave-dpi.service
printf '\nWave DPI установлен.\nОткрыть меню: sudo wave-dpi\nСтатус: wave-dpi status\nУдалить: sudo wave-dpi-uninstall\n'
