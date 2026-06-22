#!/bin/bash
# Start all 30 FarmTown bots with staggered delay
# Direct connection — staggered start + 8-15s cycle delay prevents rate limiting
PYTHON="/usr/bin/python3"
BOT="/root/farmtown-bot.py"
LOCKFILE="/tmp/farmtown-launcher.lock"
ENVFILE="/root/.farmtown-env"

export NO_PROXY=1

# Load secrets from env file (never commit this!)
if [ -f "$ENVFILE" ]; then
    source "$ENVFILE"
else
    echo "WARNING: $ENVFILE not found — captcha keys won't work"
fi

# Prevent concurrent runs
exec 200>"$LOCKFILE"
flock -n 200 || { echo "Launcher already running — exit"; exit 0; }

echo "=== FarmTown Launcher $(date '+%H:%M') ==="
started=0
skipped=0

for i in $(seq -w 1 30); do
    w="w${i}"
    if pgrep -f "farmtown-bot.py $w" > /dev/null 2>&1; then
        skipped=$((skipped + 1))
        continue
    fi
    nohup $PYTHON -u "$BOT" "$w" >> /tmp/farmtown-${w}.log 2>&1 &
    started=$((started + 1))
    echo "Started $w (PID: $!)"
    sleep 15
done
echo "Done: $started started, $skipped skipped. Total: $(pgrep -cf 'farmtown-bot.py w')"
