#!/usr/bin/env bash
# Programa el refresco local cada 12 horas en tu máquina.
# - macOS  -> launchd (LaunchAgent), sobrevive reinicios.
# - Linux  -> crontab del usuario.
# Vuelve a ejecutarlo para reinstalar; usa --remove para quitarlo.
#
#   bash scripts/schedule_12h.sh          # instala (08:00 y 20:00)
#   bash scripts/schedule_12h.sh --remove # desinstala
#
set -euo pipefail
cd "$(dirname "$0")/.."
ROOT="$(pwd)"
RUN="$ROOT/scripts/refresh_and_push.sh"
LABEL="com.futboledge.refresh"
HOURS_1=8    # primera pasada
HOURS_2=20   # segunda pasada (12h después)

uname_s="$(uname -s)"

if [ "${1:-}" = "--remove" ]; then
  if [ "$uname_s" = "Darwin" ]; then
    launchctl unload "$HOME/Library/LaunchAgents/$LABEL.plist" 2>/dev/null || true
    rm -f "$HOME/Library/LaunchAgents/$LABEL.plist"
    echo "LaunchAgent eliminado."
  else
    crontab -l 2>/dev/null | grep -v "$RUN" | crontab - || true
    echo "Entrada de cron eliminada."
  fi
  exit 0
fi

if [ "$uname_s" = "Darwin" ]; then
  mkdir -p "$HOME/Library/LaunchAgents"
  PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"
  cat > "$PLIST" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>Label</key><string>$LABEL</string>
  <key>ProgramArguments</key>
  <array><string>/bin/bash</string><string>$RUN</string></array>
  <key>StartCalendarInterval</key>
  <array>
    <dict><key>Hour</key><integer>$HOURS_1</integer><key>Minute</key><integer>0</integer></dict>
    <dict><key>Hour</key><integer>$HOURS_2</integer><key>Minute</key><integer>0</integer></dict>
  </array>
  <key>StandardOutPath</key><string>$ROOT/scripts/refresh.log</string>
  <key>StandardErrorPath</key><string>$ROOT/scripts/refresh.log</string>
  <key>WorkingDirectory</key><string>$ROOT</string>
</dict></plist>
EOF
  launchctl unload "$PLIST" 2>/dev/null || true
  launchctl load "$PLIST"
  echo "Programado con launchd a las $HOURS_1:00 y $HOURS_2:00. Log: scripts/refresh.log"
else
  LINE="0 $HOURS_1,$HOURS_2 * * * cd $ROOT && /bin/bash $RUN >> $ROOT/scripts/refresh.log 2>&1"
  ( crontab -l 2>/dev/null | grep -v "$RUN"; echo "$LINE" ) | crontab -
  echo "Programado con cron a las $HOURS_1:00 y $HOURS_2:00. Log: scripts/refresh.log"
  echo "Comprueba con: crontab -l"
fi
