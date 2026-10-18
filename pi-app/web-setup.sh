#!/bin/bash
# Turn on the file page, so any browser on the same Wi-Fi can open http://console.local
set -e
cd "$(dirname "$0")"
mkdir -p "$HOME/console-data/projects" "$HOME/console-data/samples" "$HOME/console-data/exports"
sudo cp console-web.service /etc/systemd/system/console-web.service
sudo systemctl daemon-reload
sudo systemctl enable --now console-web.service
sudo systemctl restart console-web.service
echo "Done. Open http://$(hostname).local in a browser on the same Wi-Fi."
