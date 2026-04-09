<?php

/*
 * Copyright (C) 2026 Udo
 *
 * SPDX-License-Identifier: Apache-2.0
 */

namespace OPNsense\OpenWrtAdmin;

class BrokerClient
{
    private const BASE_URL = 'http://127.0.0.1:9783';
    private const DEFAULT_TIMEOUT = 2.0;
    private const ACTION_TIMEOUT = 15.0;
    private const SYNC_TIMEOUT = 45.0;

    private function request(string $method, string $path, ?array $payload = null, ?float $timeout = null): array
    {
        $url = self::BASE_URL . $path;
        $headers = ['Content-Type: application/json'];
        $timeout = $timeout ?? self::DEFAULT_TIMEOUT;

        if (function_exists('curl_init')) {
            $ch = curl_init($url);
            if ($ch === false) {
                return [
                    'ok' => false,
                    'status' => 0,
                    'body' => null,
                    'timed_out' => false,
                    'error' => 'Unable to initialize cURL.',
                ];
            }

            curl_setopt($ch, CURLOPT_CUSTOMREQUEST, $method);
            curl_setopt($ch, CURLOPT_RETURNTRANSFER, true);
            curl_setopt($ch, CURLOPT_TIMEOUT_MS, (int)($timeout * 1000));
            curl_setopt($ch, CURLOPT_HTTPHEADER, $headers);

            if ($payload !== null) {
                curl_setopt($ch, CURLOPT_POSTFIELDS, json_encode($payload));
            }

            $body = curl_exec($ch);
            $status = (int)curl_getinfo($ch, CURLINFO_RESPONSE_CODE);
            $curlError = curl_error($ch);
            $curlErrno = curl_errno($ch);
            curl_close($ch);

            if (!is_string($body) || $body === false) {
                return [
                    'ok' => false,
                    'status' => $status,
                    'body' => null,
                    'timed_out' => $curlErrno === CURLE_OPERATION_TIMEDOUT,
                    'error' => $curlError !== '' ? $curlError : null,
                ];
            }

            $decoded = json_decode($body, true);
            return [
                'ok' => $status >= 200 && $status < 300 && is_array($decoded),
                'status' => $status,
                'body' => is_array($decoded) ? $decoded : null,
                'timed_out' => false,
                'error' => null,
            ];
        }

        $options = [
                'http' => [
                    'method' => $method,
                    'ignore_errors' => true,
                    'timeout' => $timeout,
                    'header' => implode("\r\n", $headers) . "\r\n",
                ],
            ];

        if ($payload !== null) {
            $options['http']['content'] = json_encode($payload);
        }

        $context = stream_context_create($options);
        $lastError = null;
        set_error_handler(static function (int $errno, string $errstr) use (&$lastError) {
            $lastError = $errstr;
            return true;
        });
        $body = @file_get_contents($url, false, $context);
        restore_error_handler();
        if ($body === false) {
            $timedOut = $lastError !== null && stripos($lastError, 'timed out') !== false;
            return [
                'ok' => false,
                'status' => 0,
                'body' => null,
                'timed_out' => $timedOut,
                'error' => $lastError,
            ];
        }

        $status = 0;
        if (!empty($http_response_header[0]) && preg_match('#\s(\d{3})\s#', $http_response_header[0], $matches)) {
            $status = (int)$matches[1];
        }

        $decoded = json_decode($body, true);
        return [
            'ok' => $status >= 200 && $status < 300 && is_array($decoded),
            'status' => $status,
            'body' => is_array($decoded) ? $decoded : null,
            'timed_out' => false,
            'error' => null,
        ];
    }

    public function status(): array
    {
        return $this->request('GET', '/v1/status');
    }

    public function routers(): array
    {
        return $this->request('GET', '/v1/routers');
    }

    public function clients(): array
    {
        return $this->request('GET', '/v1/clients');
    }

    public function pollNow(): array
    {
        return $this->request('POST', '/v1/poll-now');
    }

    public function routerActions(string $action, array $routers): array
    {
        return $this->request('POST', '/v1/router-actions', [
            'action' => $action,
            'routers' => array_values($routers),
        ], self::ACTION_TIMEOUT);
    }

    public function syncConfigs(array $routers): array
    {
        return $this->request('POST', '/v1/config-sync', [
            'routers' => array_values($routers),
        ], self::SYNC_TIMEOUT);
    }

    public function configBackups(string $routerUuid, string $configType): array
    {
        return $this->request(
            'GET',
            '/v1/config-backups?router_uuid=' . rawurlencode($routerUuid) . '&config_type=' . rawurlencode($configType)
        );
    }

    public function restoreConfigBackup(string $routerUuid, string $configType, string $contentHash): array
    {
        return $this->request('POST', '/v1/config-restore', [
            'router_uuid' => $routerUuid,
            'config_type' => $configType,
            'content_hash' => $contentHash,
        ], self::SYNC_TIMEOUT);
    }

    public function syncWifi(array $routers): array
    {
        return $this->syncConfigs($routers);
    }

    public function wifiBackups(string $routerUuid): array
    {
        return $this->configBackups($routerUuid, 'wifi');
    }

    public function restoreWifiBackup(string $routerUuid, string $contentHash): array
    {
        return $this->restoreConfigBackup($routerUuid, 'wifi', $contentHash);
    }
}
