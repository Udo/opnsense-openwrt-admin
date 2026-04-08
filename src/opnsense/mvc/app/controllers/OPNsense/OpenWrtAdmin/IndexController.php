<?php

/*
 * Copyright (C) 2026 Udo
 *
 * SPDX-License-Identifier: Apache-2.0
 */

namespace OPNsense\OpenWrtAdmin;

class IndexController extends \OPNsense\Base\IndexController
{
    public function indexAction()
    {
        $this->view->formDialogRouter = $this->getForm('dialogRouter');
        $this->view->formGridRouter = $this->getFormGrid('dialogRouter');
        $this->view->pick('OPNsense/OpenWrtAdmin/index');
    }
}
