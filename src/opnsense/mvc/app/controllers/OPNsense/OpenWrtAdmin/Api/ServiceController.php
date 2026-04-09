<?php

/*
 * Copyright (C) 2026 Udo
 *
 * SPDX-License-Identifier: Apache-2.0
 */

namespace OPNsense\OpenWrtAdmin\Api;

use OPNsense\Base\ApiControllerBase;
use OPNsense\Core\Backend;
use OPNsense\OpenWrtAdmin\BrokerClient;

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

        $maps = $this->parseDhcpLeaseHints();
        $configPath = '/conf/config.xml';
        if (!is_file($configPath) || !is_readable($configPath)) {
            $this->dhcpHints = $maps;
            return $maps;
        }

        libxml_use_internal_errors(true);
        $config = simplexml_load_file($configPath);
        if ($config === false || !isset($config->dhcpd)) {
            $this->dhcpHints = $maps;
            return $maps;
        }

        foreach ($config->dhcpd->children() as $interfaceNode) {
            foreach ($interfaceNode->staticmap as $staticmap) {
                $entry = [
                    'hostname' => trim((string)$staticmap->hostname),
                    'description' => trim((string)$staticmap->descr),
                    'ip_address' => trim((string)$staticmap->ipaddr),
                ];
                $mac = strtolower(trim((string)$staticmap->mac));
                if ($mac !== '') {
                    $existing = $maps['by_mac'][$mac] ?? [
                        'hostname' => '',
                        'description' => '',
                        'ip_address' => '',
                    ];
                    $maps['by_mac'][$mac] = [
                        'hostname' => $existing['hostname'] !== '' ? $existing['hostname'] : $entry['hostname'],
                        'description' => $entry['description'] !== '' ? $entry['description'] : $existing['description'],
                        'ip_address' => $existing['ip_address'] !== '' ? $existing['ip_address'] : $entry['ip_address'],
                    ];
                }

                $address = strtolower($entry['ip_address']);
                if ($address !== '') {
                    $existing = $maps['by_address'][$address] ?? [
                        'hostname' => '',
                        'description' => '',
                        'ip_address' => $entry['ip_address'],
                    ];
                    $maps['by_address'][$address] = [
                        'hostname' => $existing['hostname'] !== '' ? $existing['hostname'] : $entry['hostname'],
                        'description' => $entry['description'] !== '' ? $entry['description'] : $existing['description'],
                        'ip_address' => $entry['ip_address'],
                    ];
                }
            }
        }

        $this->dhcpHints = $maps;
        return $maps;
    }

    public function startAction()
    {
        return ['status' => trim((new Backend())->configdRun('openwrtadmin start'))];
    }

    public function stopAction()
    {
        return ['status' => trim((new Backend())->configdRun('openwrtadmin stop'))];
    }

    public function restartAction()
    {
        return ['status' => trim((new Backend())->configdRun('openwrtadmin restart'))];
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
        return (new BrokerClient())->pollNow()['body'] ?? ['status' => 'error'];
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

    public function bulkActionAction()
    {
        $action = trim((string)$this->request->getPost('action'));
        $routers = $this->request->getPost('routers');
        if (!is_array($routers)) {
            $routers = $routers !== null ? [$routers] : [];
        }

        if ($action === '') {
            return ['status' => 'error', 'message' => 'No action selected.'];
        }

        $routerIds = array_values(array_filter(array_map('strval', $routers)));
        $client = new BrokerClient();
        if ($action === 'sync_configs' || $action === 'sync_wifi') {
            $result = $client->syncConfigs($routerIds);
        } else {
            $result = $client->routerActions($action, $routerIds);
        }

        if (!empty($result['body']) && is_array($result['body'])) {
            return $result['body'];
        }

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

        $result = (new BrokerClient())->restoreConfigBackup($routerUuid, $configType, $contentHash);
        if (!empty($result['body']) && is_array($result['body'])) {
            return $result['body'];
        }

        return $this->brokerFailure($result, 'Broker request failed.');
    }

    public function wifiBackupsAction()
    {
        $routerUuid = trim((string)$this->request->get('router_uuid'));
        if ($routerUuid === '') {
            return ['status' => 'error', 'message' => 'No router selected.', 'backups' => []];
        }

        return (new BrokerClient())->configBackups($routerUuid, 'wifi')['body']
            ?? ['status' => 'error', 'message' => 'Broker request failed.', 'backups' => []];
    }

    public function restoreWifiBackupAction()
    {
        $routerUuid = trim((string)$this->request->getPost('router_uuid'));
        $contentHash = trim((string)$this->request->getPost('content_hash'));
        if ($routerUuid === '' || $contentHash === '') {
            return ['status' => 'error', 'message' => 'Router and backup are required.'];
        }

        return (new BrokerClient())->restoreConfigBackup($routerUuid, 'wifi', $contentHash)['body']
            ?? ['status' => 'error', 'message' => 'Broker request failed.'];
    }
}
