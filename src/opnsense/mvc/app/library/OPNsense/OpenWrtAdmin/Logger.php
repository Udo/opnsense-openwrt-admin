<?php

/*
 * Copyright (C) 2026 Udo
 *
 * SPDX-License-Identifier: BSD-2-Clause
 */

namespace OPNsense\OpenWrtAdmin;

class Logger
{
    private const IDENT = 'openwrtadmin';

    /** Whether openlog() has already been called for this process. */
    private static bool $opened = false;

    public static function info(string $event, array $context = []): void
    {
        self::write(LOG_INFO, $event, $context);
    }

    public static function warning(string $event, array $context = []): void
    {
        self::write(LOG_WARNING, $event, $context);
    }

    public static function error(string $event, array $context = []): void
    {
        self::write(LOG_ERR, $event, $context);
    }

    private static function write(int $priority, string $event, array $context): void
    {
        $payload = ['event' => $event];
        if (!empty($context)) {
            $payload['context'] = $context;
        }

        $message = json_encode($payload, JSON_UNESCAPED_SLASHES | JSON_UNESCAPED_UNICODE);
        if (!is_string($message) || $message === '') {
            $message = sprintf('{"event":"%s"}', addslashes($event));
        }

        if (!self::$opened) {
            openlog(self::IDENT, LOG_PID, LOG_USER);
            self::$opened = true;
        }

        syslog($priority, $message);
    }
}
