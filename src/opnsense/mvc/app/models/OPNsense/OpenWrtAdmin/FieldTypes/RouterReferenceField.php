<?php

/*
 * Copyright (C) 2026 Udo
 *
 * SPDX-License-Identifier: BSD-2-Clause
 */

namespace OPNsense\OpenWrtAdmin\FieldTypes;

use OPNsense\Base\FieldTypes\BaseListField;
use OPNsense\OpenWrtAdmin\RouterStore;

class RouterReferenceField extends BaseListField
{
    protected function actionPostLoadingEvent()
    {
        $this->internalOptionList = RouterStore::list();
    }

    protected function defaultValidationMessage()
    {
        return gettext('Please select a valid router.');
    }
}
