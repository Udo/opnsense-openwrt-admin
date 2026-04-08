<?php

/*
 * Copyright (C) 2026 Udo
 *
 * SPDX-License-Identifier: Apache-2.0
 */

namespace OPNsense\OpenWrtAdmin\Api;

use OPNsense\Base\ApiMutableModelControllerBase;
use OPNsense\OpenWrtAdmin\BrokerClient;
use OPNsense\OpenWrtAdmin\SshKeyStore;

class SettingsController extends ApiMutableModelControllerBase
{
    protected static $internalModelName = 'openwrtadmin';
    protected static $internalModelClass = 'OPNsense\OpenWrtAdmin\OpenWrtAdmin';

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

    public function searchRouterAction()
    {
        $result = $this->searchBase('routers.router', null, 'address');
        $runtimeRowsByUuid = [];
        $runtimeRowsByAddress = [];
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

                if ($runtimeRow !== null) {
                    $row['status'] = $this->formatGridStatus($runtimeRow['status_text'] ?? $row['status'] ?? '');
                    $row['version'] = $this->formatGridVersion($runtimeRow['version'] ?? $row['version'] ?? '');
                }
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
        return $this->addBase('router', 'routers.router');
    }

    public function setRouterAction($uuid)
    {
        return $this->setBase('router', 'routers.router', $uuid);
    }

    public function delRouterAction($uuid)
    {
        return $this->delBase('routers.router', $uuid);
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
