<?php

/*
 * Copyright (C) 2026 Udo
 *
 * SPDX-License-Identifier: BSD-2-Clause
 */

namespace OPNsense\OpenWrtAdmin\Api;

use OPNsense\Base\ApiMutableModelControllerBase;
use OPNsense\OpenWrtAdmin\BrokerClient;
use OPNsense\OpenWrtAdmin\DhcpHelper;
use OPNsense\OpenWrtAdmin\Logger;
use OPNsense\OpenWrtAdmin\SshKeyStore;

class SettingsController extends ApiMutableModelControllerBase
{
    protected static $internalModelName = 'openwrtadmin';
    protected static $internalModelClass = 'OPNsense\OpenWrtAdmin\OpenWrtAdmin';
    private const CONFIG_SOURCES = [
        'wifi' => [
            'field' => 'sync_wifi_config_from',
            'hash' => 'wifi_content_hash',
        ],
        'system' => [
            'field' => 'sync_system_config_from',
            'hash' => 'system_content_hash',
        ],
        'firewall' => [
            'field' => 'sync_firewall_config_from',
            'hash' => 'firewall_content_hash',
        ],
        'dhcp' => [
            'field' => 'sync_dhcp_config_from',
            'hash' => 'dhcp_content_hash',
        ],
        'rpcd' => [
            'field' => 'sync_rpcd_config_from',
            'hash' => 'rpcd_content_hash',
        ],
    ];
    private function formatGridStatus(?string $status): string
    {
        $status = trim((string)$status);
        if ($status === '') {
            return 'Unknown';
        }

        if (stripos($status, 'Healthy') === 0) {
            return 'ok';
        }
        if (stripos($status, 'Warning') === 0) {
            return 'warning';
        }
        if (stripos($status, 'Critical') === 0) {
            return 'critical';
        }

        return $status;
    }

    private function formatGridVersion(?string $version): string
    {
        $version = trim((string)$version);
        if ($version === '') {
            return 'N/A';
        }

        return preg_replace('/^OpenWrt\s+/i', '', $version) ?? $version;
    }

    private function formatGridHardware(?string $hardware): string
    {
        $hardware = trim((string)$hardware);
        return $hardware === '' ? 'Unknown' : $hardware;
    }

    private function configSourceMeta(array $row, array $rowsByUuid, ?array $runtimeRow, array $runtimeRowsByUuid): array
    {
        $parts = [];
        $allInSync = true;
        $hasSource = false;

        foreach (self::CONFIG_SOURCES as $prefix => $meta) {
            $sourceUuid = trim((string)($row[$meta['field']] ?? ''));
            if ($sourceUuid === '' || empty($rowsByUuid[$sourceUuid])) {
                continue;
            }

            $hasSource = true;
            $source = $rowsByUuid[$sourceUuid];
            $hostname = trim((string)($source['hostname'] ?? ''));
            $address = trim((string)($source['address'] ?? ''));
            $sourceLabel = $hostname !== '' ? $hostname : $address;
            if ($sourceLabel !== '') {
                $parts[] = sprintf('%s: %s', $prefix, $sourceLabel);
            }

            $sourceRuntime = $runtimeRowsByUuid[$sourceUuid] ?? null;
            $targetHash = trim((string)($runtimeRow[$meta['hash']] ?? ''));
            $sourceHash = trim((string)($sourceRuntime[$meta['hash']] ?? ''));
            if ($targetHash === '' || $sourceHash === '' || $targetHash !== $sourceHash) {
                $allInSync = false;
            }
        }

        return [
            'label' => implode(' | ', $parts),
            'in_sync' => $hasSource && $allInSync,
        ];
    }

    public function searchRouterAction()
    {
        $result = $this->searchBase('routers.router', null, 'address');
        $runtimeRowsByUuid = [];
        $runtimeRowsByAddress = [];
        $rowsByUuid = [];
        $dhcpDescriptionsByAddress = DhcpHelper::descriptionsByAddress();
        $runtime = (new BrokerClient())->routers();
        if (!empty($runtime['ok']) && !empty($runtime['body']['routers']) && is_array($runtime['body']['routers'])) {
            foreach ($runtime['body']['routers'] as $row) {
                if (!empty($row['router_uuid'])) {
                    $runtimeRowsByUuid[$row['router_uuid']] = $row;
                }
                if (!empty($row['address'])) {
                    $runtimeRowsByAddress[strtolower((string)$row['address'])] = $row;
                }
            }
        }

        if (!empty($result['rows']) && is_array($result['rows'])) {
            foreach ($result['rows'] as $row) {
                $uuid = $row['uuid'] ?? $row['rowid'] ?? null;
                if ($uuid !== null) {
                    $rowsByUuid[$uuid] = $row;
                }
            }
            foreach ($result['rows'] as &$row) {
                $runtimeRow = null;
                $uuid = $row['uuid'] ?? $row['rowid'] ?? null;
                if ($uuid !== null && isset($runtimeRowsByUuid[$uuid])) {
                    $runtimeRow = $runtimeRowsByUuid[$uuid];
                } elseif (!empty($row['address'])) {
                    $addressKey = strtolower((string)$row['address']);
                    if (isset($runtimeRowsByAddress[$addressKey])) {
                        $runtimeRow = $runtimeRowsByAddress[$addressKey];
                    }
                }

                if (empty(trim((string)($row['description'] ?? ''))) && !empty($row['address'])) {
                    $addressKey = strtolower((string)$row['address']);
                    if (!empty($dhcpDescriptionsByAddress[$addressKey])) {
                        $row['description'] = $dhcpDescriptionsByAddress[$addressKey];
                    }
                }

                if ($runtimeRow !== null) {
                    $row['status'] = $this->formatGridStatus($runtimeRow['status_text'] ?? $row['status'] ?? '');
                    $row['version'] = $this->formatGridVersion($runtimeRow['version'] ?? $row['version'] ?? '');
                    $row['hardware'] = $this->formatGridHardware($runtimeRow['hardware_model'] ?? $row['hardware'] ?? '');
                }

                $configSource = $this->configSourceMeta($row, $rowsByUuid, $runtimeRow, $runtimeRowsByUuid);
                $row['sync_status'] = $configSource['in_sync'] && $configSource['label'] !== ''
                    ? '✓ ' . $configSource['label']
                    : $configSource['label'];
                $row['sync_in_sync'] = $configSource['in_sync'] ? '1' : '0';
            }
            unset($row);
        }

        return $result;
    }

    public function getRouterAction($uuid = null)
    {
        return $this->getBase('router', 'routers.router', $uuid);
    }

    public function addRouterAction()
    {
        $result = $this->addBase('router', 'routers.router');
        Logger::info('ui.router.add', [
            'result' => $result['result'] ?? null,
            'uuid' => $result['uuid'] ?? null,
        ]);
        return $result;
    }

    public function setRouterAction($uuid)
    {
        $result = $this->setBase('router', 'routers.router', $uuid);
        Logger::info('ui.router.save', [
            'uuid' => (string)$uuid,
            'result' => $result['result'] ?? null,
        ]);
        return $result;
    }

    public function delRouterAction($uuid)
    {
        $result = $this->delBase('routers.router', $uuid);
        Logger::info('ui.router.delete', [
            'uuid' => (string)$uuid,
            'result' => $result['result'] ?? null,
        ]);
        return $result;
    }

    public function getSshPublicKeyAction()
    {
        $ref = (string)$this->request->get('ref');
        $key = SshKeyStore::fetch($ref);
        if ($key === null) {
            return [
                'status' => 'error',
                'message' => 'SSH public key not found.',
            ];
        }

        return [
            'status' => 'ok',
            'ref' => $key['ref'],
            'label' => $key['label'],
            'public_key' => $key['public_key'],
        ];
    }
}
