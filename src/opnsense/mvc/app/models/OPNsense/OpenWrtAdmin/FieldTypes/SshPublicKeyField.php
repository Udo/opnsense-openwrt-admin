<?php

/*
 * Copyright (C) 2026 Udo
 *
 * SPDX-License-Identifier: BSD-2-Clause
 */

namespace OPNsense\OpenWrtAdmin\FieldTypes;

use OPNsense\Base\FieldTypes\BaseListField;
use OPNsense\OpenWrtAdmin\SshKeyStore;

class SshPublicKeyField extends BaseListField
{
    protected function actionPostLoadingEvent()
    {
        $this->internalOptionList = SshKeyStore::list();
    }

    protected function defaultValidationMessage()
    {
        return gettext('Please select a valid SSH public key.');
    }
}
