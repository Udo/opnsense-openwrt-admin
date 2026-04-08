<?php

/*
 * Copyright (C) 2026 Udo
 *
 * SPDX-License-Identifier: Apache-2.0
 */

namespace OPNsense\OpenWrtAdmin\Api;

use OPNsense\Base\ApiMutableModelControllerBase;
use OPNsense\Core\Config;
use OPNsense\OpenWrtAdmin\OpenWrtAdmin;
use OPNsense\OpenWrtAdmin\SshKeyStore;

class GeneralController extends ApiMutableModelControllerBase
{
    protected static $internalModelName = 'openwrtadmin';
    protected static $internalModelClass = 'OPNsense\OpenWrtAdmin\OpenWrtAdmin';

    public function getAction()
    {
        return ['settings' => $this->getModel()->settings->getNodes()];
    }

    public function setAction()
    {
        $result = ['result' => 'failed'];
        if ($this->request->isPost() && $this->request->hasPost('settings')) {
            Config::getInstance()->lock();
            $mdl = $this->getModel();
            $mdl->settings->setNodes($this->request->getPost('settings'));
            $result = $this->validate($mdl->settings, 'settings');
            if (empty($result['result'])) {
                return $this->save(false, true);
            }
        }
        return $result;
    }

    public function generateManagedKeypairAction()
    {
        if (!$this->request->isPost()) {
            return ['result' => 'failed', 'message' => 'POST required'];
        }

        Config::getInstance()->lock();
        $mdl = $this->getModel();

        $postedSettings = $this->request->getPost('settings');
        if (is_array($postedSettings)) {
            $mdl->settings->setNodes($postedSettings);
        }

        $comment = trim((string)$mdl->settings->managed_key_comment);
        if ($comment === '') {
            $comment = 'openwrt-admin@OPNsense';
            $mdl->settings->managed_key_comment = $comment;
        }

        $base = tempnam('/tmp', 'openwrtadmin_key_');
        if ($base === false) {
            return ['result' => 'failed', 'message' => 'Unable to allocate temporary key path.'];
        }
        @unlink($base);

        $cmd = sprintf(
            'ssh-keygen -q -t ed25519 -N %s -C %s -f %s 2>/dev/null',
            escapeshellarg(''),
            escapeshellarg($comment),
            escapeshellarg($base)
        );

        exec($cmd, $output, $returnCode);
        if ($returnCode !== 0 || !is_file($base) || !is_file($base . '.pub')) {
            @unlink($base);
            @unlink($base . '.pub');
            return ['result' => 'failed', 'message' => 'Failed to generate SSH keypair.'];
        }

        $privateKey = trim((string)file_get_contents($base));
        $publicKey = trim((string)file_get_contents($base . '.pub'));
        @unlink($base);
        @unlink($base . '.pub');

        $mdl->settings->managed_private_key = $privateKey;
        $mdl->settings->managed_public_key = $publicKey;

        $result = $this->validate($mdl->settings, 'settings');
        if (!empty($result['result'])) {
            return $result;
        }

        $saveResult = $this->save(false, true);
        $saveResult['ssh_key_ref'] = SshKeyStore::MANAGED_KEY_REF;
        $saveResult['public_key'] = $publicKey;
        return $saveResult;
    }
}
