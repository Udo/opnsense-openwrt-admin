<?php

/*
 * Copyright (C) 2026 Udo
 *
 * SPDX-License-Identifier: Apache-2.0
 */

namespace OPNsense\OpenWrtAdmin;

class DashboardController extends \OPNsense\Base\IndexController
{
    private function getDhcpDescriptionsByAddress(): array
    {
        $descriptions = [];
        $configPath = '/conf/config.xml';
        if (!is_file($configPath) || !is_readable($configPath)) {
            return $descriptions;
        }

        libxml_use_internal_errors(true);
        $config = simplexml_load_file($configPath);
        if ($config === false || !isset($config->dhcpd)) {
            return $descriptions;
        }

        foreach ($config->dhcpd->children() as $interfaceNode) {
            foreach ($interfaceNode->staticmap as $staticmap) {
                $address = trim((string)$staticmap->ipaddr);
                $description = trim((string)$staticmap->descr);
                if ($address !== '' && $description !== '' && !isset($descriptions[strtolower($address)])) {
                    $descriptions[strtolower($address)] = $description;
                }
            }
        }

        return $descriptions;
    }

    public function indexAction()
    {
        $dhcpDescriptionsByAddress = $this->getDhcpDescriptionsByAddress();
        $this->view->dhcpDescriptionsByAddressJson = json_encode($dhcpDescriptionsByAddress) ?: '{}';
        $this->view->pick('OPNsense/OpenWrtAdmin/dashboard');
    }
}
