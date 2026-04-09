<?php

/*
 * Copyright (C) 2026 Udo
 *
 * SPDX-License-Identifier: BSD-2-Clause
 */

namespace OPNsense\OpenWrtAdmin;

class ClientStatsController extends \OPNsense\Base\IndexController
{
    public function indexAction()
    {
        $this->view->pick('OPNsense/OpenWrtAdmin/clientstats');
    }
}
