<?php

/*
 * Copyright (C) 2026 Udo
 *
 * SPDX-License-Identifier: Apache-2.0
 */

namespace OPNsense\OpenWrtAdmin\Api;

use OPNsense\Base\ApiControllerBase;
use OPNsense\Core\Backend;
use OPNsense\OpenWrtAdmin\BrokerClient;

class ServiceController extends ApiControllerBase
{
    public function startAction()
    {
        return ['status' => trim((new Backend())->configdRun('openwrtadmin start'))];
    }

    public function stopAction()
    {
        return ['status' => trim((new Backend())->configdRun('openwrtadmin stop'))];
    }

    public function restartAction()
    {
        return ['status' => trim((new Backend())->configdRun('openwrtadmin restart'))];
    }

    public function statusAction()
    {
        $result = trim((new Backend())->configdRun('openwrtadmin status'));
        $broker = (new BrokerClient())->status();
        return [
            'service' => $result,
            'broker' => $broker,
        ];
    }

    public function pollNowAction()
    {
        return (new BrokerClient())->pollNow()['body'] ?? ['status' => 'error'];
    }

    public function routersAction()
    {
        return (new BrokerClient())->routers()['body'] ?? ['status' => 'error', 'routers' => []];
    }
}
