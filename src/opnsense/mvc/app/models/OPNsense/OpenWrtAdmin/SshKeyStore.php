<?php

/*
 * Copyright (C) 2026 Udo
 *
 * SPDX-License-Identifier: Apache-2.0
 */

namespace OPNsense\OpenWrtAdmin;

use OPNsense\Core\Config;

class SshKeyStore
{
    private const DEFAULT_ROOT_KEY = '/root/.ssh/id_ed25519.pub';
    public const MANAGED_KEY_REF = 'managed:openwrt-admin';

    private static function keyFiles(): array
    {
        $patterns = [
            '/root/.ssh/*.pub',
            '/home/*/.ssh/*.pub',
        ];

        $results = [];
        foreach ($patterns as $pattern) {
            foreach (glob($pattern) ?: [] as $file) {
                $real = realpath($file);
                if ($real !== false && is_file($real) && is_readable($real)) {
                    $results[$real] = $real;
                }
            }
        }

        ksort($results, SORT_NATURAL | SORT_FLAG_CASE);
        return array_values($results);
    }

    private static function ownerLabel(string $path): string
    {
        if (strpos($path, '/root/') === 0) {
            return 'root';
        }

        if (preg_match('#^/home/([^/]+)/#', $path, $matches)) {
            return $matches[1];
        }

        return 'system';
    }

    private static function parsePublicKey(string $path): ?array
    {
        $content = @trim((string)file_get_contents($path));
        if ($content === '') {
            return null;
        }

        $parts = preg_split('/\s+/', $content, 3);
        if (count($parts) < 2) {
            return null;
        }

        $type = $parts[0];
        $comment = $parts[2] ?? '';
        $label = sprintf('%s: %s', self::ownerLabel($path), basename($path));
        if ($comment !== '') {
            $label .= sprintf(' (%s)', $comment);
        } else {
            $label .= sprintf(' (%s)', $type);
        }

        return [
            'ref' => 'system:' . $path,
            'label' => $label,
            'public_key' => $content,
        ];
    }

    private static function managedKey(): ?array
    {
        $config = Config::getInstance()->object();
        $settings = $config->OPNsense->OpenWrtAdmin->settings ?? null;
        if ($settings === null) {
            return null;
        }

        $publicKey = trim((string)$settings->managed_public_key);
        if ($publicKey === '') {
            return null;
        }

        $comment = trim((string)$settings->managed_key_comment);
        $label = 'OpenWrt Admin managed key';
        if ($comment !== '') {
            $label .= sprintf(' (%s)', $comment);
        }

        return [
            'ref' => self::MANAGED_KEY_REF,
            'label' => $label,
            'public_key' => $publicKey,
            'private_key' => trim((string)$settings->managed_private_key),
        ];
    }

    public static function list(): array
    {
        $items = [];
        if (($managed = self::managedKey()) !== null) {
            $items[$managed['ref']] = $managed['label'];
        }

        foreach (self::keyFiles() as $path) {
            $parsed = self::parsePublicKey($path);
            if ($parsed !== null) {
                $items[$parsed['ref']] = $parsed['label'];
            }
        }

        return $items;
    }

    public static function defaultRef(): string
    {
        $all = self::list();
        $defaultSystemRef = 'system:' . self::DEFAULT_ROOT_KEY;
        if (isset($all[$defaultSystemRef])) {
            return $defaultSystemRef;
        }

        $keys = array_keys($all);
        return $keys[0] ?? '';
    }

    public static function fetch(string $ref): ?array
    {
        if ($ref === self::MANAGED_KEY_REF) {
            return self::managedKey();
        }

        if (strpos($ref, 'system:') !== 0) {
            return null;
        }

        $path = substr($ref, 7);
        $allowed = array_flip(self::keyFiles());
        $real = realpath($path);
        if ($real === false || !isset($allowed[$real])) {
            return null;
        }

        return self::parsePublicKey($real);
    }
}
