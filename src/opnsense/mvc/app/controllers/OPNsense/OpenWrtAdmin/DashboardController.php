<?php

/*
 * Copyright (C) 2026 Udo
 *
 * SPDX-License-Identifier: BSD-2-Clause
 */

namespace OPNsense\OpenWrtAdmin;

class DashboardController extends \OPNsense\Base\IndexController
{
    public function indexAction(): void
    {
        $this->view->dhcpDescriptionsByAddress = DhcpHelper::descriptionsByAddress();
        $this->view->pick('OPNsense/OpenWrtAdmin/dashboard');
    }
}
