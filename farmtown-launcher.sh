#!/bin/bash
# FarmTown Multi-Wallet Launcher
# Usage: ./farmtown-launcher.sh [start|stop|status|logs|logs <wallet>]

set -e

LOGDIR="/tmp/farmtown-logs"
mkdir -p "$LOGDIR"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
BOT_SCRIPT="$SCRIPT_DIR/farmtown-bot.py"

# Auto-detect wallets from keypair files
detect_wallets() {
    local wallets=""
    for f in "$HOME"/.farmtown-keypair-*.json; do
        [ -f "$f" ] || continue
        wid=$(basename "$f" | sed 's/.farmtown-keypair-//;s/.json//')
        wallets="$wallets $wid"
    done
    echo "$wallets"
}

WALLETS="${FARMTOWN_WALLETS:-$(detect_wallets)}"

start_wallet() {
    WALLET=$1
    LOGFILE="$LOGDIR/${WALLET}.log"
    PIDFILE="$LOGDIR/${WALLET}.pid"

    if [ -f "$PIDFILE" ] && kill -0 $(cat "$PIDFILE") 2>/dev/null; then
        echo "[$WALLET] already running (PID $(cat $PIDFILE))"
        return
    fi

    if [ ! -f "$HOME/.farmtown-keypair-${WALLET}.json" ]; then
        echo "[$WALLET] keypair not found, skipping"
        return
    fi

    PYTHONUNBUFFERED=1 python3 "$BOT_SCRIPT" "$WALLET" > "$LOGFILE" 2>&1 &
    PID=$!
    echo $PID > "$PIDFILE"
    echo "[$WALLET] started (PID $PID) → $LOGFILE"
}

stop_wallet() {
    WALLET=$1
    PIDFILE="$LOGDIR/${WALLET}.pid"

    if [ -f "$PIDFILE" ]; then
        PID=$(cat "$PIDFILE")
        if kill -0 "$PID" 2>/dev/null; then
            kill "$PID" 2>/dev/null
            echo "[$WALLET] stopped (PID $PID)"
        else
            echo "[$WALLET] was not running (stale PID)"
        fi
        rm -f "$PIDFILE"
    else
        # Try to find by process name
        PID=$(pgrep -f "farmtown-bot.py $WALLET" 2>/dev/null | head -1)
        if [ -n "$PID" ]; then
            kill "$PID" 2>/dev/null
            echo "[$WALLET] stopped (PID $PID)"
        else
            echo "[$WALLET] not running"
        fi
    fi
}

status_wallet() {
    WALLET=$1
    PIDFILE="$LOGDIR/${WALLET}.pid"
    LOGFILE="$LOGDIR/${WALLET}.log"

    if [ -f "$PIDFILE" ] && kill -0 $(cat "$PIDFILE") 2>/dev/null; then
        PID=$(cat "$PIDFILE")
        LAST=$(tail -1 "$LOGFILE" 2>/dev/null | head -c 120)
        echo "[$WALLET] ✅ PID:$PID | $LAST"
    else
        echo "[$WALLET] ❌ not running"
    fi
}

case "${1:-help}" in
    start)
        echo "🌾 Starting FarmTown bots..."
        if [ -n "$2" ]; then
            start_wallet "$2"
        else
            if [ -z "$WALLETS" ]; then
                echo "No wallets found. Create keypair files:"
                echo "  echo '[253, 81, ...]' > ~/.farmtown-keypair-w01.json"
                exit 1
            fi
            for w in $WALLETS; do
                start_wallet "$w"
            done
        fi
        echo ""
        echo "Done! Logs: tail -f $LOGDIR/wXX.log"
        echo "Status: $0 status"
        ;;
    stop)
        echo "Stopping bots..."
        if [ -n "$2" ]; then
            stop_wallet "$2"
        else
            for w in $WALLETS; do
                stop_wallet "$w"
            done
        fi
        ;;
    restart)
        $0 stop
        sleep 2
        $0 start
        ;;
    status)
        echo "🌾 FarmTown Bot Status:"
        echo "========================"
        if [ -n "$2" ]; then
            status_wallet "$2"
        else
            for w in $WALLETS; do
                status_wallet "$w"
            done
        fi
        ;;
    logs)
        if [ -n "$2" ]; then
            tail -f "$LOGDIR/$2.log"
        else
            echo "Available logs:"
            ls -la "$LOGDIR"/*.log 2>/dev/null || echo "No logs found"
            echo ""
            echo "Usage: $0 logs <wallet_id>"
        fi
        ;;
    help|*)
        echo "FarmTown Multi-Wallet Launcher"
        echo ""
        echo "Usage: $0 <command> [wallet_id]"
        echo ""
        echo "Commands:"
        echo "  start [w01]    Start all wallets (or specific one)"
        echo "  stop  [w01]    Stop all wallets (or specific one)"
        echo "  restart        Restart all wallets"
        echo "  status [w01]   Show status of all (or specific) wallets"
        echo "  logs   w01     Tail logs for a specific wallet"
        echo ""
        echo "Wallet setup:"
        echo "  1. Get your Solana wallet bytes (64 bytes JSON array)"
        echo "  2. Save as ~/.farmtown-keypair-w01.json"
        echo "  3. Run: $0 start"
        echo ""
        echo "Environment:"
        echo "  FARMTOWN_WALLETS='w01 w02 w03'  Override wallet list"
        echo "  FARMTOWN_LEVEL_FLOOR=10         Don't burn below this level"
        echo "  FARMTOWN_GOLD_KEEP=100          Keep this much gold on burn"
        ;;
esac
