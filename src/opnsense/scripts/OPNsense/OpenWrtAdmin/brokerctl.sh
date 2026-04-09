#!/bin/sh

set -eu

PYTHON_BIN="/usr/local/bin/python3"
BROKER_SCRIPT="/usr/local/opnsense/scripts/OPNsense/OpenWrtAdmin/broker.py"
PIDFILE="/var/run/openwrt-admind.pid"
LOGFILE="/var/log/openwrt-admind.log"
API_URL="http://127.0.0.1:9783"

is_running() {
    [ -f "${PIDFILE}" ] && kill -0 "$(cat "${PIDFILE}")" 2>/dev/null
}

start_broker() {
    if is_running; then
        echo "already running"
        return 0
    fi

    mkdir -p /var/db/openwrt-admin /var/db/openwrt-admin/keys
    touch "${LOGFILE}"
    /usr/sbin/daemon -f -p "${PIDFILE}" -o "${LOGFILE}" "${PYTHON_BIN}" "${BROKER_SCRIPT}"
    echo "started"
}

stop_broker() {
    if ! is_running; then
        echo "not running"
        return 0
    fi

    kill "$(cat "${PIDFILE}")"

    # Wait up to 5 seconds for the process to exit before removing the PID file.
    i=0
    while [ "${i}" -lt 50 ] && is_running; do
        sleep 0.1
        i=$((i + 1))
    done

    rm -f "${PIDFILE}"
    echo "stopped"
}

status_broker() {
    if is_running; then
        echo "running"
    else
        echo "stopped"
    fi
}

poll_now() {
    curl -sf -X POST "${API_URL}/v1/poll-now" || echo '{"status":"error","message":"Broker not reachable"}'
}

case "${1:-}" in
    start)
        start_broker
        ;;
    stop)
        stop_broker
        ;;
    restart)
        stop_broker || true
        start_broker
        ;;
    status)
        status_broker
        ;;
    poll-now)
        poll_now
        ;;
    *)
        echo "usage: $0 {start|stop|restart|status|poll-now}" >&2
        exit 1
        ;;
esac
