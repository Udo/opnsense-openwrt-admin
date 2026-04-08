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
    private const TIMEOUT = 2.0;

    private function request(string $method, string $path, ?array $payload = null): array
    {
        $url = self::BASE_URL . $path;
        $headers = ['Content-Type: application/json'];

        if (function_exists('curl_init')) {
            $ch = curl_init($url);
            if ($ch === false) {
                return [
                    'ok' => false,
                    'status' => 0,
                    'body' => null,
                ];
            }

            curl_setopt($ch, CURLOPT_CUSTOMREQUEST, $method);
            curl_setopt($ch, CURLOPT_RETURNTRANSFER, true);
            curl_setopt($ch, CURLOPT_TIMEOUT_MS, (int)(self::TIMEOUT * 1000));
            curl_setopt($ch, CURLOPT_HTTPHEADER, $headers);

            if ($payload !== null) {
                curl_setopt($ch, CURLOPT_POSTFIELDS, json_encode($payload));
            }

            $body = curl_exec($ch);
            $status = (int)curl_getinfo($ch, CURLINFO_RESPONSE_CODE);
            curl_close($ch);

            if (!is_string($body) || $body === false) {
                return [
                    'ok' => false,
                    'status' => $status,
                    'body' => null,
                ];
            }

            $decoded = json_decode($body, true);
            return [
                'ok' => $status >= 200 && $status < 300 && is_array($decoded),
                'status' => $status,
                'body' => is_array($decoded) ? $decoded : null,
            ];
        }

        $options = [
            'http' => [
                'method' => $method,
                'ignore_errors' => true,
                'timeout' => self::TIMEOUT,
                'header' => implode("\r\n", $headers) . "\r\n",
            ],
        ];

        if ($payload !== null) {
            $options['http']['content'] = json_encode($payload);
        }

        $context = stream_context_create($options);
        $body = @file_get_contents($url, false, $context);
        if ($body === false) {
            return [
                'ok' => false,
                'status' => 0,
                'body' => null,
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

    public function pollNow(): array
    {
        return $this->request('POST', '/v1/poll-now');
    }
}
