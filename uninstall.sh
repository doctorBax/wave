#!/usr/bin/env bash
set -euo pipefail
[[ $EUID -eq 0 ]] || { echo 'Запуск: sudo bash uninstall.sh' >&2; exit 1; }
systemctl disable --now wave-dpi.service 2>/dev/null || true
# Clean up even after a crashed or missing service.
if [[ -x /usr/local/libexec/wave-dpi-net ]]; then
  /usr/local/libexec/wave-dpi-net off 2>/dev/null || true
fi
rm -f /etc/systemd/system/wave-dpi.service /usr/local/bin/wave-dpi /usr/local/bin/wave-dpi-uninstall /usr/local/libexec/wave-dpi-net
rm -rf /opt/wave-dpi
systemctl daemon-reload
printf 'Wave DPI удалён. Настройки оставлены в /etc/wave-dpi.\n'
