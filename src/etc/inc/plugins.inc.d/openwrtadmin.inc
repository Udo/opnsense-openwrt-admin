<?php

/*
 * Copyright (C) 2026 Udo
 *
 * SPDX-License-Identifier: Apache-2.0
 */

function openwrtadmin_services()
{
    return array(
        array(
            'description' => gettext('OpenWrt Admin Broker'),
            'configd' => array(
                'restart' => array('openwrtadmin restart'),
                'start' => array('openwrtadmin start'),
                'stop' => array('openwrtadmin stop'),
                'status' => array('openwrtadmin status'),
            ),
            'name' => 'openwrtadmin',
            'pidfile' => '/var/run/openwrt-admind.pid'
        )
    );
}
