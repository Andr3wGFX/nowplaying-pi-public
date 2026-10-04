#!/usr/bin/env bash
# Install the display as a boot service.   bash ~/np/install_service.sh
# Safe to re-run: it rewrites the unit file and restarts the service.
set -e

USER_NAME="$(whoami)"
SERVICE=/etc/systemd/system/nowplaying.service

if [ ! -x "$HOME/np/bin/python" ]; then
  echo "Can't find $HOME/np/bin/python -- is the venv there?"; exit 1
fi
if [ ! -f "$HOME/np/nowplaying.py" ]; then
  echo "Can't find $HOME/np/nowplaying.py -- the repo should be cloned to ~/np"; exit 1
fi
if [ -f "$HOME/nowplaying.py" ]; then
  echo "Note: an old copy exists at ~/nowplaying.py. The service now runs"
  echo "      ~/np/nowplaying.py (the repo copy). Delete the old one when happy:"
  echo "      rm ~/nowplaying.py"
fi

echo "Installing service for user '$USER_NAME'..."
sudo sed -e "s|^User=.*|User=$USER_NAME|" \
         -e "s|^Group=.*|Group=$USER_NAME|" \
         -e "s|/home/YOUR_USER|$HOME|g" \
         "$HOME/np/nowplaying.service" | sudo tee "$SERVICE" >/dev/null

sudo systemctl daemon-reload
sudo systemctl enable nowplaying.service
sudo systemctl restart nowplaying.service
sleep 3
sudo systemctl --no-pager status nowplaying.service || true

echo
echo "Useful from now on:"
echo "  sudo systemctl stop nowplaying      # stop it (do this before running by hand)"
echo "  sudo systemctl start nowplaying"
echo "  sudo systemctl restart nowplaying   # after a git pull"
echo "  sudo systemctl disable nowplaying   # stop it starting at boot"
echo "  journalctl -u nowplaying -f         # watch its output live"
