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
    "${PYTHON_BIN}" -c "import json, urllib.request; print(urllib.request.urlopen(urllib.request.Request('${API_URL}/v1/poll-now', method='POST'), timeout=2).read().decode())"
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
        sleep 1
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
