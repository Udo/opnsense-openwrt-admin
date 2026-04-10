<?php

/*
 * Copyright (C) 2026 Udo
 *
 * SPDX-License-Identifier: BSD-2-Clause
 */

namespace OPNsense\OpenWrtAdmin;

/**
 * Shared helpers for reading DHCP configuration data from OPNsense's config.xml.
 */
class DhcpHelper
{
    private const CONFIG_PATH = '/conf/config.xml';

    /**
     * Returns a map of lowercased IP address => description string, sourced from
     * DHCP static-map entries in config.xml.  Entries without both an address and
     * a description are skipped.  The first entry seen for a given address wins.
     *
     * @return array<string, string>
     */
    public static function descriptionsByAddress(): array
    {
        $descriptions = [];
        $config = self::loadDhcpConfig();
        if ($config === null) {
            return $descriptions;
        }

        foreach ($config->dhcpd->children() as $interfaceNode) {
            foreach ($interfaceNode->staticmap as $staticmap) {
                $address = trim((string)$staticmap->ipaddr);
                $description = trim((string)$staticmap->descr);
                if ($address !== '' && $description !== '') {
                    $key = strtolower($address);
                    if (!isset($descriptions[$key])) {
                        $descriptions[$key] = $description;
                    }
                }
            }
        }

        return $descriptions;
    }

    /**
     * Returns a map of lowercased MAC address => static-map metadata array.
     * Each entry contains 'hostname', 'description', and 'ip_address' keys.
     * This is used when a full static-map record is needed, not just the description.
     *
     * @return array<string, array{hostname: string, description: string, ip_address: string}>
     */
    public static function staticMapsByMac(): array
    {
        $maps = [];
        $config = self::loadDhcpConfig();
        if ($config === null) {
            return $maps;
        }

        foreach ($config->dhcpd->children() as $interfaceNode) {
            foreach ($interfaceNode->staticmap as $staticmap) {
                $mac = strtolower(trim((string)$staticmap->mac));
                if ($mac === '') {
                    continue;
                }
                if (!isset($maps[$mac])) {
                    $maps[$mac] = [
                        'hostname'    => trim((string)$staticmap->hostname),
                        'description' => trim((string)$staticmap->descr),
                        'ip_address'  => trim((string)$staticmap->ipaddr),
                    ];
                }
            }
        }

        return $maps;
    }

    /**
     * Loads and returns the <dhcpd> portion of config.xml as a SimpleXML object,
     * or null if the file is unavailable or does not contain a <dhcpd> node.
     */
    private static function loadDhcpConfig(): ?\SimpleXMLElement
    {
        if (!is_file(self::CONFIG_PATH) || !is_readable(self::CONFIG_PATH)) {
            return null;
        }

        libxml_use_internal_errors(true);
        $config = simplexml_load_file(self::CONFIG_PATH);
        if ($config === false || !isset($config->dhcpd)) {
            return null;
        }

        return $config;
    }
}
