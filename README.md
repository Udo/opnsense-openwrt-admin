# opnsense-openwrt-admin

OPNsense plugin scaffold for administering a fleet of OpenWrt routers.

## Current status

The repository now contains the first minimal OPNsense plugin structure:

- `Makefile` and `pkg-descr` for plugin packaging metadata
- MVC and API controllers under `src/opnsense/mvc/app/controllers/OPNsense/OpenWrtAdmin`
- Persistent model storage under `src/opnsense/mvc/app/models/OPNsense/OpenWrtAdmin`
- Menu registration under `src/opnsense/mvc/app/models/OPNsense/OpenWrtAdmin/Menu`
- A native bootgrid-based router inventory page plus a general settings page under `src/opnsense/mvc/app/views/OPNsense/OpenWrtAdmin`

## Dev install on an OPNsense host

Copy the MVC files from `src/opnsense/mvc/app/` into `/usr/local/opnsense/mvc/app/`, then remove `/tmp/opnsense_menu_cache.xml` so the new menu entry is rebuilt.

The initial page is exposed at `/ui/openwrtadmin`.

For this environment, use `scripts/deploy-dev.sh` to copy the current MVC files to `uh-firewall` and refresh the menu cache automatically.
