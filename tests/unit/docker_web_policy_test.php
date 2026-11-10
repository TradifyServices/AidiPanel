<?php
declare(strict_types=1);

namespace Core {
    final class Auth
    {
        public static string $currentRole = 'client';
        public static function isAdmin(): bool { return self::$currentRole === 'admin'; }
        public static function isManager(): bool { return self::$currentRole === 'manager'; }
        public static function role(): string { return self::$currentRole; }
        public static function user(): array { return ['id' => 7, 'username' => 'client']; }
    }

    final class DB
    {
        public static function instance(): self { return new self(); }
        public function rows(string $query, array $params = []): array { return [['site_id' => 10]]; }
        public function row(string $query, array $params = []): array
        {
            return ['id' => ($params[0] ?? '') === 'owned.example' ? 10 : 11];
        }
    }
}

namespace {
    $root = dirname(__DIR__, 2);
    define('APP_ROOT', $root . '/panel-app/app');
    require APP_ROOT . '/Core/helpers.php';
    require APP_ROOT . '/Core/Access.php';
    require APP_ROOT . '/Core/Request.php';
    require APP_ROOT . '/Core/RoutePolicy.php';
    require APP_ROOT . '/Core/Router.php';

    function checkDockerPolicy(bool $condition, string $label): void
    {
        if (!$condition) {
            throw new \RuntimeException('FAIL: ' . $label);
        }
        echo 'ok: ' . $label . "\n";
    }

    checkDockerPolicy(\Core\RoutePolicy::scope('GET', '/admin/docker') === \Core\RoutePolicy::ADMIN, 'rootful Docker is administrator-only');
    foreach (['enable', 'disable'] as $operation) {
        checkDockerPolicy(\Core\RoutePolicy::scope('POST', '/sites/{domain}/containers/' . $operation) === \Core\RoutePolicy::ADMIN, 'rootless provisioning requires administrator: ' . $operation);
    }
    checkDockerPolicy(\Core\RoutePolicy::scope('POST', '/sites/{domain}/containers/{operation}') === \Core\RoutePolicy::SITE_PATH_DOMAIN, 'container actions require site assignment');
    foreach (['/admin/docker/logs', '/sites/{domain}/containers/logs'] as $route) {
        checkDockerPolicy(\Core\RoutePolicy::blockedInDemo('GET', $route), 'demo cannot read container logs');
    }

    checkDockerPolicy(\Core\Access::canManageSite('owned.example'), 'assigned client can manage its site');
    checkDockerPolicy(!\Core\Access::canManageSite('foreign.example'), 'client cannot manage another site');
    checkDockerPolicy(!\Core\Access::canAccessAdminArea(), 'client cannot access rootful management');
    \Core\Auth::$currentRole = 'manager';
    checkDockerPolicy(!\Core\Access::canAccessAdminArea(), 'manager cannot access rootful management');
    \Core\Auth::$currentRole = 'admin';
    checkDockerPolicy(\Core\Access::canAccessAdminArea(), 'admin can access rootful management');

    foreach (['status', 'list', 'create', 'start', 'stop', 'restart', 'remove', 'logs'] as $operation) {
        checkDockerPolicy(is_web_cli_invocation_allowed('docker:' . $operation, []), 'rootful fixed command allowed: ' . $operation);
        checkDockerPolicy(is_web_cli_invocation_allowed('docker:' . $operation, ['--domain', 'owned.example']), 'site fixed command allowed: ' . $operation);
        checkDockerPolicy(!is_web_cli_invocation_allowed('docker:' . $operation, ['--user', 'root']), 'cannot supply a user: ' . $operation);
        checkDockerPolicy(!is_web_cli_invocation_allowed('docker:' . $operation, ['--domain', 'owned.example', '--host', 'unix:///var/run/docker.sock']), 'cannot override daemon: ' . $operation);
    }
    checkDockerPolicy(!is_web_cli_invocation_allowed('docker:enable', []), 'cannot enable rootful through provisioning command');
    checkDockerPolicy(is_web_cli_invocation_allowed('docker:enable', ['--domain', 'owned.example']), 'site provisioning has an exact domain');
    checkDockerPolicy(!is_web_cli_invocation_allowed('docker:disable', ['--domain', '../foreign']), 'invalid provisioning domain rejected');
    checkDockerPolicy(!is_web_cli_invocation_allowed('docker:exec', []), 'interactive exec is not allowed');
    echo "Docker web policy tests passed\n";
}
