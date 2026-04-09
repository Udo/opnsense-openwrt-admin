#!/usr/bin/env bash

set -euo pipefail

usage() {
    cat <<'EOF'
Usage: scripts/deploy-dev.sh <target-host>

Developer convenience deploy for a live OPNsense firewall.

Arguments:
  <target-host>    SSH host alias or hostname of the target OPNsense system

Environment:
  MOUNT_BASE       Base directory for SSHFS mounts (default: /root/mount_ssh)

Behavior:
  - If ${MOUNT_BASE}/<target-host> looks like an OPNsense root filesystem,
    files are copied through that mounted path.
  - Otherwise the script falls back to staging files locally and copying them
    over SSH/SCP.
EOF
}

if [[ "${1:-}" == "-h" || "${1:-}" == "--help" ]]; then
    usage
    exit 0
fi

if [[ $# -lt 1 ]]; then
    usage >&2
    exit 1
fi

TARGET_HOST="$1"
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
MOUNT_BASE="${MOUNT_BASE:-/root/mount_ssh}"
MOUNT_ROOT="${MOUNT_BASE}/${TARGET_HOST}"

if [[ -d "${MOUNT_ROOT}/usr/local/opnsense/mvc/app" ]]; then
    rm -rf "${MOUNT_ROOT}/usr/local/opnsense/mvc/app/controllers/OPNsense/OpenWrtAdmin" \
        "${MOUNT_ROOT}/usr/local/opnsense/mvc/app/library/OPNsense/OpenWrtAdmin" \
        "${MOUNT_ROOT}/usr/local/opnsense/mvc/app/models/OPNsense/OpenWrtAdmin" \
        "${MOUNT_ROOT}/usr/local/opnsense/mvc/app/views/OPNsense/OpenWrtAdmin" \
        "${MOUNT_ROOT}/usr/local/opnsense/scripts/OPNsense/OpenWrtAdmin" \
        "${MOUNT_ROOT}/usr/local/opnsense/service/templates/OPNsense/Syslog/local/openwrtadmin.conf" \
        "${MOUNT_ROOT}/usr/local/etc/rc.syshook.d/start/90-openwrt-admin" \
        "${MOUNT_ROOT}/usr/local/etc/rc.syshook.d/stop/90-openwrt-admin"

    mkdir -p "${MOUNT_ROOT}/usr/local/opnsense/mvc/app/controllers/OPNsense" \
        "${MOUNT_ROOT}/usr/local/opnsense/mvc/app/library/OPNsense" \
        "${MOUNT_ROOT}/usr/local/opnsense/mvc/app/models/OPNsense" \
        "${MOUNT_ROOT}/usr/local/opnsense/mvc/app/views/OPNsense" \
        "${MOUNT_ROOT}/usr/local/opnsense/scripts/OPNsense" \
        "${MOUNT_ROOT}/usr/local/opnsense/service/conf/actions.d" \
        "${MOUNT_ROOT}/usr/local/opnsense/service/templates/OPNsense/Syslog/local" \
        "${MOUNT_ROOT}/usr/local/etc/inc/plugins.inc.d" \
        "${MOUNT_ROOT}/usr/local/etc/rc.d" \
        "${MOUNT_ROOT}/usr/local/etc/rc.syshook.d/start" \
        "${MOUNT_ROOT}/usr/local/etc/rc.syshook.d/stop"

    cp -R "${REPO_ROOT}/src/opnsense/mvc/app/controllers/OPNsense/OpenWrtAdmin" \
        "${MOUNT_ROOT}/usr/local/opnsense/mvc/app/controllers/OPNsense/"
    cp -R "${REPO_ROOT}/src/opnsense/mvc/app/library/OPNsense/OpenWrtAdmin" \
        "${MOUNT_ROOT}/usr/local/opnsense/mvc/app/library/OPNsense/"
    cp -R "${REPO_ROOT}/src/opnsense/mvc/app/models/OPNsense/OpenWrtAdmin" \
        "${MOUNT_ROOT}/usr/local/opnsense/mvc/app/models/OPNsense/"
    cp -R "${REPO_ROOT}/src/opnsense/mvc/app/views/OPNsense/OpenWrtAdmin" \
        "${MOUNT_ROOT}/usr/local/opnsense/mvc/app/views/OPNsense/"
    cp -R "${REPO_ROOT}/src/opnsense/scripts/OPNsense/OpenWrtAdmin" \
        "${MOUNT_ROOT}/usr/local/opnsense/scripts/OPNsense/"
    cp "${REPO_ROOT}/src/opnsense/service/conf/actions.d/actions_openwrtadmin.conf" \
        "${MOUNT_ROOT}/usr/local/opnsense/service/conf/actions.d/"
    cp "${REPO_ROOT}/src/opnsense/service/templates/OPNsense/Syslog/local/openwrtadmin.conf" \
        "${MOUNT_ROOT}/usr/local/opnsense/service/templates/OPNsense/Syslog/local/"
    cp "${REPO_ROOT}/src/etc/inc/plugins.inc.d/openwrtadmin.inc" \
        "${MOUNT_ROOT}/usr/local/etc/inc/plugins.inc.d/"
    cp "${REPO_ROOT}/src/etc/rc.d/openwrtadmin" \
        "${MOUNT_ROOT}/usr/local/etc/rc.d/"
    cp "${REPO_ROOT}/src/etc/rc.syshook.d/start/90-openwrt-admin" \
        "${MOUNT_ROOT}/usr/local/etc/rc.syshook.d/start/"
    cp "${REPO_ROOT}/src/etc/rc.syshook.d/stop/90-openwrt-admin" \
        "${MOUNT_ROOT}/usr/local/etc/rc.syshook.d/stop/"
else
    STAGE_DIR="$(mktemp -d /tmp/openwrt-admin-deploy.XXXXXX)"

    mkdir -p "${STAGE_DIR}/app/controllers/OPNsense" \
        "${STAGE_DIR}/app/library/OPNsense" \
        "${STAGE_DIR}/app/models/OPNsense" \
        "${STAGE_DIR}/app/views/OPNsense" \
        "${STAGE_DIR}/scripts/OPNsense" \
        "${STAGE_DIR}/service/conf/actions.d" \
        "${STAGE_DIR}/service/templates/OPNsense/Syslog/local" \
        "${STAGE_DIR}/etc/inc/plugins.inc.d" \
        "${STAGE_DIR}/etc/rc.d" \
        "${STAGE_DIR}/etc/rc.syshook.d/start" \
        "${STAGE_DIR}/etc/rc.syshook.d/stop"

    cp -R "${REPO_ROOT}/src/opnsense/mvc/app/controllers/OPNsense/OpenWrtAdmin" \
        "${STAGE_DIR}/app/controllers/OPNsense/"
    cp -R "${REPO_ROOT}/src/opnsense/mvc/app/library/OPNsense/OpenWrtAdmin" \
        "${STAGE_DIR}/app/library/OPNsense/"
    cp -R "${REPO_ROOT}/src/opnsense/mvc/app/models/OPNsense/OpenWrtAdmin" \
        "${STAGE_DIR}/app/models/OPNsense/"
    cp -R "${REPO_ROOT}/src/opnsense/mvc/app/views/OPNsense/OpenWrtAdmin" \
        "${STAGE_DIR}/app/views/OPNsense/"
    cp -R "${REPO_ROOT}/src/opnsense/scripts/OPNsense/OpenWrtAdmin" \
        "${STAGE_DIR}/scripts/OPNsense/"
    cp "${REPO_ROOT}/src/opnsense/service/conf/actions.d/actions_openwrtadmin.conf" \
        "${STAGE_DIR}/service/conf/actions.d/"
    cp "${REPO_ROOT}/src/opnsense/service/templates/OPNsense/Syslog/local/openwrtadmin.conf" \
        "${STAGE_DIR}/service/templates/OPNsense/Syslog/local/"
    cp "${REPO_ROOT}/src/etc/inc/plugins.inc.d/openwrtadmin.inc" \
        "${STAGE_DIR}/etc/inc/plugins.inc.d/"
    cp "${REPO_ROOT}/src/etc/rc.d/openwrtadmin" \
        "${STAGE_DIR}/etc/rc.d/"
    cp "${REPO_ROOT}/src/etc/rc.syshook.d/start/90-openwrt-admin" \
        "${STAGE_DIR}/etc/rc.syshook.d/start/"
    cp "${REPO_ROOT}/src/etc/rc.syshook.d/stop/90-openwrt-admin" \
        "${STAGE_DIR}/etc/rc.syshook.d/stop/"

    trap 'rm -rf "${STAGE_DIR}"' EXIT

    ssh "${TARGET_HOST}" "rm -rf /tmp/openwrt-admin-deploy && mkdir -p /tmp/openwrt-admin-deploy"
    scp -r "${STAGE_DIR}/." "${TARGET_HOST}:/tmp/openwrt-admin-deploy/"

    ssh "${TARGET_HOST}" /bin/sh -c \
        "'rm -rf /usr/local/opnsense/mvc/app/controllers/OPNsense/OpenWrtAdmin /usr/local/opnsense/mvc/app/library/OPNsense/OpenWrtAdmin /usr/local/opnsense/mvc/app/models/OPNsense/OpenWrtAdmin /usr/local/opnsense/mvc/app/views/OPNsense/OpenWrtAdmin /usr/local/opnsense/scripts/OPNsense/OpenWrtAdmin && \
          cp -R /tmp/openwrt-admin-deploy/app/controllers/OPNsense/OpenWrtAdmin /usr/local/opnsense/mvc/app/controllers/OPNsense/ && \
          cp -R /tmp/openwrt-admin-deploy/app/library/OPNsense/OpenWrtAdmin /usr/local/opnsense/mvc/app/library/OPNsense/ && \
          cp -R /tmp/openwrt-admin-deploy/app/models/OPNsense/OpenWrtAdmin /usr/local/opnsense/mvc/app/models/OPNsense/ && \
          cp -R /tmp/openwrt-admin-deploy/app/views/OPNsense/OpenWrtAdmin /usr/local/opnsense/mvc/app/views/OPNsense/ && \
         cp -R /tmp/openwrt-admin-deploy/scripts/OPNsense/OpenWrtAdmin /usr/local/opnsense/scripts/OPNsense/ && \
         cp /tmp/openwrt-admin-deploy/service/conf/actions.d/actions_openwrtadmin.conf /usr/local/opnsense/service/conf/actions.d/ && \
         cp /tmp/openwrt-admin-deploy/service/templates/OPNsense/Syslog/local/openwrtadmin.conf /usr/local/opnsense/service/templates/OPNsense/Syslog/local/ && \
         cp /tmp/openwrt-admin-deploy/etc/inc/plugins.inc.d/openwrtadmin.inc /usr/local/etc/inc/plugins.inc.d/ && \
         cp /tmp/openwrt-admin-deploy/etc/rc.d/openwrtadmin /usr/local/etc/rc.d/ && \
         cp /tmp/openwrt-admin-deploy/etc/rc.syshook.d/start/90-openwrt-admin /usr/local/etc/rc.syshook.d/start/ && \
         cp /tmp/openwrt-admin-deploy/etc/rc.syshook.d/stop/90-openwrt-admin /usr/local/etc/rc.syshook.d/stop/'"
fi

ssh "${TARGET_HOST}" /bin/sh -c \
    "'chmod +x /usr/local/opnsense/scripts/OPNsense/OpenWrtAdmin/brokerctl.sh /usr/local/etc/rc.d/openwrtadmin /usr/local/etc/rc.syshook.d/start/90-openwrt-admin /usr/local/etc/rc.syshook.d/stop/90-openwrt-admin && \
      rm -f /var/lib/php/tmp/opnsense_menu_cache.xml && \
      rm -rf /tmp/OpenWrtAdmin && \
      php -l /usr/local/opnsense/mvc/app/controllers/OPNsense/OpenWrtAdmin/IndexController.php && \
      php -l /usr/local/opnsense/mvc/app/library/OPNsense/OpenWrtAdmin/BrokerClient.php && \
      php -l /usr/local/etc/inc/plugins.inc.d/openwrtadmin.inc && \
      sh -n /usr/local/etc/rc.d/openwrtadmin && \
      /usr/local/bin/python3 -m py_compile /usr/local/opnsense/scripts/OPNsense/OpenWrtAdmin/broker.py && \
      (/usr/sbin/service php_fpm onerestart >/dev/null 2>&1 || true) && \
      (configctl template reload OPNsense/Syslog >/dev/null 2>&1 || true) && \
      (service syslog-ng onerestart >/dev/null 2>&1 || true) && \
      (service configd restart >/dev/null 2>&1 || true) && \
      (/usr/local/etc/rc.d/openwrtadmin onerestart >/dev/null 2>&1 || /usr/local/etc/rc.d/openwrtadmin onestart >/dev/null 2>&1 || true)'"

echo "Deployed OpenWrt Admin MVC files to ${TARGET_HOST}"
