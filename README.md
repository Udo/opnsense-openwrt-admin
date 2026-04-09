# opnsense-openwrt-admin

OPNsense plugin scaffold for administering a fleet of OpenWrt routers.

## Current status

- `Makefile` and `pkg-descr` for plugin packaging metadata
- MVC and API controllers under `src/opnsense/mvc/app/controllers/OPNsense/OpenWrtAdmin`
- Persistent model storage under `src/opnsense/mvc/app/models/OPNsense/OpenWrtAdmin`
- Menu registration under `src/opnsense/mvc/app/models/OPNsense/OpenWrtAdmin/Menu`
- A native bootgrid-based router inventory page plus a general settings page under `src/opnsense/mvc/app/views/OPNsense/OpenWrtAdmin`
- A stdlib-only Python broker under `src/opnsense/scripts/OPNsense/OpenWrtAdmin`
- `configd` broker control actions under `src/opnsense/service/conf/actions.d`
- An `rc.d` service script under `src/etc/rc.d`
- A service registration hook under `src/etc/inc/plugins.inc.d`

## Dev install on an OPNsense host

Copy the MVC files from `src/opnsense/mvc/app/` into `/usr/local/opnsense/mvc/app/`.
Copy the broker script from `src/opnsense/scripts/` into `/usr/local/opnsense/scripts/`.
Copy the `configd` actions from `src/opnsense/service/conf/actions.d/` into `/usr/local/opnsense/service/conf/actions.d/`, then restart `configd`.
On current OPNsense builds the menu cache is stored at `/var/lib/php/tmp/opnsense_menu_cache.xml`, so remove that file to rebuild the menu entry.

The initial page is exposed at `/ui/openwrtadmin`.

For this environment, use `scripts/deploy-dev.sh` to copy the current MVC files, broker files, and startup hooks to `uh-firewall`, refresh the menu cache, restart `configd`, and restart the broker.

## Testing

The broker has a stdlib-only unit test suite under `tests/` that avoids real SSH and exercises our config sync logic with temporary state and mocks.

Run it with:

`make test`

or directly:

`python3 -m unittest discover -s tests -p 'test_*.py'`
