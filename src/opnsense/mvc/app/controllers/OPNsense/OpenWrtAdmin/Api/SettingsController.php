<?php

/*
 * Copyright (C) 2026 Udo
 *
 * SPDX-License-Identifier: Apache-2.0
 */

namespace OPNsense\OpenWrtAdmin\Api;

use OPNsense\Base\ApiMutableModelControllerBase;
use OPNsense\OpenWrtAdmin\SshKeyStore;

class SettingsController extends ApiMutableModelControllerBase
{
    protected static $internalModelName = 'openwrtadmin';
    protected static $internalModelClass = 'OPNsense\OpenWrtAdmin\OpenWrtAdmin';

    public function searchRouterAction()
    {
        return $this->searchBase('routers.router', null, 'address');
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
