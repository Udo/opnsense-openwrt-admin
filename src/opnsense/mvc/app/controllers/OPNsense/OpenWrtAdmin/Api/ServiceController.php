<?php

/*
 * Copyright (C) 2026 Udo
 *
 * SPDX-License-Identifier: BSD-2-Clause
 */

namespace OPNsense\OpenWrtAdmin\Api;

use OPNsense\Base\ApiControllerBase;
use OPNsense\Core\Backend;
use OPNsense\OpenWrtAdmin\BrokerClient;
use OPNsense\OpenWrtAdmin\DhcpHelper;
use OPNsense\OpenWrtAdmin\Logger;

class ServiceController extends ApiControllerBase
{
    private ?array $dhcpHints = null;

    private function brokerFailure(array $result, string $defaultMessage, bool $includeBackups = false): array
    {
        if (!empty($result['timed_out'])) {
            $message = 'The broker request timed out before it returned a result.';
        } elseif (!empty($result['error'])) {
            $message = $defaultMessage . ' ' . trim((string)$result['error']);
        } else {
            $message = $defaultMessage;
            if (!empty($result['status'])) {
                $message .= ' HTTP status: ' . (int)$result['status'] . '.';
            }
        }

        $response = ['status' => 'error', 'message' => $message];
        if ($includeBackups) {
            $response['backups'] = [];
        }
        return $response;
    }

    private function parseDhcpLeaseHints(): array
    {
        $maps = [
            'by_mac' => [],
            'by_address' => [],
        ];
        $leasePath = '/var/dhcpd/var/db/dhcpd.leases';
        if (!is_file($leasePath) || !is_readable($leasePath)) {
            return $maps;
        }

        $contents = @file_get_contents($leasePath);
        if (!is_string($contents) || $contents === '') {
            return $maps;
        }

        if (!preg_match_all('/lease\s+([^\s]+)\s+\{(.*?)\n\}/s', $contents, $matches, PREG_SET_ORDER)) {
            return $maps;
        }

        foreach ($matches as $match) {
            $ipAddress = trim((string)$match[1]);
            $body = (string)$match[2];
            if (stripos($body, 'binding state active;') === false) {
                continue;
            }

            if (!preg_match('/hardware ethernet\s+([0-9a-f:]{17});/i', $body, $macMatch)) {
                continue;
            }

            $hostname = '';
            if (preg_match('/client-hostname\s+"([^"]+)";/i', $body, $hostnameMatch)) {
                $hostname = trim((string)$hostnameMatch[1]);
            }

            $entry = [
                'hostname' => $hostname,
                'description' => '',
                'ip_address' => $ipAddress,
            ];

            $mac = strtolower(trim((string)$macMatch[1]));
            if ($mac !== '') {
                $maps['by_mac'][$mac] = $entry;
            }
            if ($ipAddress !== '') {
                $maps['by_address'][strtolower($ipAddress)] = $entry;
            }
        }

        return $maps;
    }

    private function getDhcpHints(): array
    {
        if ($this->dhcpHints !== null) {
            return $this->dhcpHints;
        }

        // Start from active DHCP leases, then layer in static-map data from config.xml.
        // Lease-derived values take priority for hostname; config-derived values take priority
        // for description.  The first value seen for each field wins within each source.
        $maps = $this->parseDhcpLeaseHints();

        foreach (DhcpHelper::staticMapsByMac() as $mac => $entry) {
            if ($mac !== '') {
                $existing = $maps['by_mac'][$mac] ?? ['hostname' => '', 'description' => '', 'ip_address' => ''];
                $maps['by_mac'][$mac] = [
                    'hostname'    => $existing['hostname']    !== '' ? $existing['hostname']    : $entry['hostname'],
                    'description' => $entry['description']    !== '' ? $entry['description']    : $existing['description'],
                    'ip_address'  => $existing['ip_address']  !== '' ? $existing['ip_address']  : $entry['ip_address'],
                ];
            }

            $address = strtolower($entry['ip_address']);
            if ($address !== '') {
                $existing = $maps['by_address'][$address] ?? [
                    'hostname' => '', 'description' => '', 'ip_address' => $entry['ip_address'],
                ];
                $maps['by_address'][$address] = [
                    'hostname'    => $existing['hostname']    !== '' ? $existing['hostname']    : $entry['hostname'],
                    'description' => $entry['description']    !== '' ? $entry['description']    : $existing['description'],
                    'ip_address'  => $entry['ip_address'],
                ];
            }
        }

        $this->dhcpHints = $maps;
        return $maps;
    }

    public function startAction()
    {
        $status = trim((new Backend())->configdRun('openwrtadmin start'));
        Logger::info('ui.service.start', ['status' => $status]);
        return ['status' => $status];
    }

    public function stopAction()
    {
        $status = trim((new Backend())->configdRun('openwrtadmin stop'));
        Logger::info('ui.service.stop', ['status' => $status]);
        return ['status' => $status];
    }

    public function restartAction()
    {
        $status = trim((new Backend())->configdRun('openwrtadmin restart'));
        Logger::info('ui.service.restart', ['status' => $status]);
        return ['status' => $status];
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
        $result = (new BrokerClient())->pollNow();
        Logger::info('ui.poll_now', [
            'ok' => $result['ok'] ?? false,
            'status' => $result['status'] ?? 0,
            'timed_out' => $result['timed_out'] ?? false,
            'error' => $result['error'] ?? null,
        ]);
        return $result['body'] ?? ['status' => 'error'];
    }

    public function routersAction()
    {
        return (new BrokerClient())->routers()['body'] ?? ['status' => 'error', 'routers' => []];
    }

    public function clientsAction()
    {
        $result = (new BrokerClient())->clients();
        if (empty($result['body']) || !is_array($result['body'])) {
            return $this->brokerFailure($result, 'Broker request failed.');
        }

        $dhcpMaps = $this->getDhcpHints();
        $clientsByMac = [];

        foreach (($result['body']['clients'] ?? []) as $row) {
            if (!is_array($row)) {
                continue;
            }

            $mac = strtolower(trim((string)($row['client_mac'] ?? '')));
            if ($mac === '') {
                continue;
            }

            $ipAddress = trim((string)($row['ip_address'] ?? ''));
            $dhcpHint = $dhcpMaps['by_mac'][$mac] ?? null;
            if ($dhcpHint === null && $ipAddress !== '') {
                $dhcpHint = $dhcpMaps['by_address'][strtolower($ipAddress)] ?? null;
            }

            if (!isset($clientsByMac[$mac])) {
                $hostnameGuess = trim((string)($dhcpHint['hostname'] ?? ''));
                if ($hostnameGuess === '') {
                    $hostnameGuess = trim((string)($dhcpHint['description'] ?? ''));
                }

                $clientsByMac[$mac] = [
                    'mac' => $mac,
                    'hostname' => $hostnameGuess,
                    'description_guess' => trim((string)($dhcpHint['description'] ?? '')),
                    'ip_address' => $ipAddress !== '' ? $ipAddress : trim((string)($dhcpHint['ip_address'] ?? '')),
                    'associations' => [],
                ];
            } elseif ($clientsByMac[$mac]['ip_address'] === '' && $ipAddress !== '') {
                $clientsByMac[$mac]['ip_address'] = $ipAddress;
            }

            $apHostname = trim((string)($row['detected_hostname'] ?? ''));
            if ($apHostname === '') {
                $apHostname = trim((string)($row['configured_hostname'] ?? ''));
            }
            if ($apHostname === '') {
                $apHostname = trim((string)($row['router_address'] ?? ''));
            }

            $clientsByMac[$mac]['associations'][] = [
                'router_uuid' => trim((string)($row['router_uuid'] ?? '')),
                'ap_hostname' => $apHostname,
                'ap_address' => trim((string)($row['router_address'] ?? '')),
                'network_name' => trim((string)($row['network_name'] ?? '')),
                'radio_name' => trim((string)($row['radio_name'] ?? '')),
                'signal_dbm' => isset($row['signal_dbm']) ? (int)$row['signal_dbm'] : null,
                'rx_bytes' => isset($row['rx_bytes']) ? (int)$row['rx_bytes'] : null,
                'tx_bytes' => isset($row['tx_bytes']) ? (int)$row['tx_bytes'] : null,
                'rx_bps' => isset($row['rx_bps']) ? (int)$row['rx_bps'] : null,
                'tx_bps' => isset($row['tx_bps']) ? (int)$row['tx_bps'] : null,
                'connected_seconds' => isset($row['connected_seconds']) ? (int)$row['connected_seconds'] : null,
            ];
        }

        foreach ($clientsByMac as &$client) {
            usort($client['associations'], static function (array $left, array $right): int {
                $leftSignal = $left['signal_dbm'] ?? -999;
                $rightSignal = $right['signal_dbm'] ?? -999;
                if ($leftSignal !== $rightSignal) {
                    return $rightSignal <=> $leftSignal;
                }

                return strcmp((string)$left['ap_hostname'], (string)$right['ap_hostname']);
            });
        }
        unset($client);

        $clients = array_values($clientsByMac);
        usort($clients, static function (array $left, array $right): int {
            $leftKey = strtolower(trim((string)($left['hostname'] ?: $left['mac'])));
            $rightKey = strtolower(trim((string)($right['hostname'] ?: $right['mac'])));
            return $leftKey <=> $rightKey;
        });

        return [
            'status' => 'ok',
            'clients' => $clients,
        ];
    }

    public function statsAction()
    {
        $routers = $this->request->getPost('routers');
        if (!is_array($routers)) {
            $routers = $this->request->getQuery('routers');
        }
        if (!is_array($routers)) {
            $routers = $routers !== null ? [$routers] : [];
        }

        $networks = $this->request->getPost('networks');
        if (!is_array($networks)) {
            $networks = $this->request->getQuery('networks');
        }
        if (!is_array($networks)) {
            $networks = $networks !== null ? [$networks] : [];
        }

        $filters = [
            'start_at' => trim((string)($this->request->getPost('start_at') ?? $this->request->getQuery('start_at') ?? '')),
            'end_at' => trim((string)($this->request->getPost('end_at') ?? $this->request->getQuery('end_at') ?? '')),
            'routers' => array_values(array_filter(array_map('strval', $routers), static function (string $value): bool {
                return trim($value) !== '';
            })),
            'networks' => array_values(array_filter(array_map('strval', $networks), static function (string $value): bool {
                return trim($value) !== '';
            })),
        ];

        $result = (new BrokerClient())->stats($filters);
        if (!empty($result['body']) && is_array($result['body'])) {
            return $result['body'];
        }

        Logger::warning('ui.stats.broker_failure', [
            'http_status' => $result['status'] ?? 0,
            'timed_out' => $result['timed_out'] ?? false,
            'error' => $result['error'] ?? null,
        ]);
        return $this->brokerFailure($result, 'Broker request failed.');
    }

    private const ALLOWED_BULK_ACTIONS = ['reboot', 'radios_on', 'radios_off', 'sync_configs', 'apply_roaming_baseline', 'sys_update'];

    public function bulkActionAction()
    {
        if (!$this->request->isPost()) {
            return ['status' => 'error', 'message' => 'POST required.'];
        }

        $action = trim((string)$this->request->getPost('action'));
        $routers = $this->request->getPost('routers');
        if (!is_array($routers)) {
            $routers = $routers !== null ? [$routers] : [];
        }

        if ($action === '') {
            return ['status' => 'error', 'message' => 'No action selected.'];
        }

        if (!in_array($action, self::ALLOWED_BULK_ACTIONS, true)) {
            return ['status' => 'error', 'message' => 'Unknown action.'];
        }

        $routerIds = array_values(array_filter(array_map('strval', $routers)));
        Logger::info('ui.bulk_action.request', [
            'action' => $action,
            'router_count' => count($routerIds),
            'router_ids' => $routerIds,
        ]);
        $client = new BrokerClient();
        if ($action === 'sync_configs') {
            $result = $client->syncConfigs($routerIds);
        } else {
            $result = $client->routerActions($action, $routerIds);
        }

        if (!empty($result['body']) && is_array($result['body'])) {
            Logger::info('ui.bulk_action.result', [
                'action' => $action,
                'status' => $result['body']['status'] ?? null,
                'successful' => $result['body']['successful'] ?? null,
                'failed' => $result['body']['failed'] ?? null,
                'changed' => $result['body']['changed'] ?? null,
            ]);
            return $result['body'];
        }

        Logger::error('ui.bulk_action.broker_failure', [
            'action' => $action,
            'http_status' => $result['status'] ?? 0,
            'timed_out' => $result['timed_out'] ?? false,
            'error' => $result['error'] ?? null,
        ]);
        return $this->brokerFailure($result, 'Broker request failed.');
    }

    public function configBackupsAction()
    {
        $routerUuid = trim((string)$this->request->get('router_uuid'));
        $configType = trim((string)$this->request->get('config_type'));
        if ($routerUuid === '' || $configType === '') {
            return ['status' => 'error', 'message' => 'No router selected.', 'backups' => []];
        }

        $result = (new BrokerClient())->configBackups($routerUuid, $configType);
        if (!empty($result['body']) && is_array($result['body'])) {
            return $result['body'];
        }

        Logger::warning('ui.config_backups.broker_failure', [
            'router_uuid' => $routerUuid,
            'config_type' => $configType,
            'http_status' => $result['status'] ?? 0,
            'timed_out' => $result['timed_out'] ?? false,
            'error' => $result['error'] ?? null,
        ]);
        return $this->brokerFailure($result, 'Broker request failed.', true);
    }

    public function restoreConfigBackupAction()
    {
        $routerUuid = trim((string)$this->request->getPost('router_uuid'));
        $configType = trim((string)$this->request->getPost('config_type'));
        $contentHash = trim((string)$this->request->getPost('content_hash'));
        if ($routerUuid === '' || $configType === '' || $contentHash === '') {
            return ['status' => 'error', 'message' => 'Router, config type and backup are required.'];
        }

        Logger::info('ui.config_restore.request', [
            'router_uuid' => $routerUuid,
            'config_type' => $configType,
            'content_hash' => $contentHash,
        ]);
        $result = (new BrokerClient())->restoreConfigBackup($routerUuid, $configType, $contentHash);
        if (!empty($result['body']) && is_array($result['body'])) {
            Logger::info('ui.config_restore.result', [
                'router_uuid' => $routerUuid,
                'config_type' => $configType,
                'status' => $result['body']['status'] ?? null,
                'message' => $result['body']['message'] ?? null,
                'restored' => $result['body']['restored'] ?? null,
            ]);
            return $result['body'];
        }

        Logger::error('ui.config_restore.broker_failure', [
            'router_uuid' => $routerUuid,
            'config_type' => $configType,
            'http_status' => $result['status'] ?? 0,
            'timed_out' => $result['timed_out'] ?? false,
            'error' => $result['error'] ?? null,
        ]);
        return $this->brokerFailure($result, 'Broker request failed.');
    }

}
