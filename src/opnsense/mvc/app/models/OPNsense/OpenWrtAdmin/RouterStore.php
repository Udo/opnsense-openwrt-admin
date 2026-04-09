<?php

/*
 * Copyright (C) 2026 Udo
 *
 * SPDX-License-Identifier: BSD-2-Clause
 */

namespace OPNsense\OpenWrtAdmin;

use OPNsense\Core\Config;

class RouterStore
{
    public static function list(): array
    {
        $items = ['' => gettext('None')];
        $config = Config::getInstance()->object();
        $routers = $config->OPNsense->OpenWrtAdmin->routers ?? null;
        if ($routers === null) {
            return $items;
        }

        foreach ($routers->router ?? [] as $router) {
            $uuid = trim((string)($router['uuid'] ?? ''));
            if ($uuid === '') {
                continue;
            }

            $hostname = trim((string)$router->hostname);
            $address = trim((string)$router->address);
            $label = $hostname !== '' ? $hostname : $address;
            if ($hostname !== '' && $address !== '') {
                $label .= sprintf(' (%s)', $address);
            }
            $items[$uuid] = $label !== '' ? $label : $uuid;
        }

        return $items;
    }
}
