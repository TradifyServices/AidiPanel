<?php
declare(strict_types=1);

namespace Core {
    final class Auth
    {
        public static function isAdmin(): bool { return true; }
    }
}

namespace {
    define('APP_ROOT', dirname(__DIR__, 2) . '/panel-app/app');
    require APP_ROOT . '/Core/helpers.php';
    $domain = 'owned.example';
    $_csrf_token = 'csrf-test';
    $dockerStatus = [
        'available' => true, 'enabled' => true,
        'containers' => [[
            'id' => str_repeat('a', 64), 'name' => '<script>alert(1)</script>',
            'image' => 'nginx:alpine', 'status' => 'running',
            'ports' => [['host' => 8080, 'container' => 80]],
            'environment' => ['TOKEN' => 'should-not-appear'],
        ]],
    ];
    ob_start();
    require APP_ROOT . '/Views/docker/controls.php';
    $output = ob_get_clean();
    foreach ([
        [str_contains($output, '127.0.0.1:8080'), 'structured port bindings are readable'],
        [str_contains($output, '&lt;script&gt;alert(1)&lt;/script&gt;'), 'container names are HTML-escaped'],
        [!str_contains($output, 'should-not-appear'), 'environment values are never redisplayed'],
        [str_contains($output, '&quot;name&quot;:&quot;app-data&quot;'), 'site form offers managed named volumes'],
        [!str_contains($output, '/home/siteuser/docker-data'), 'site form does not offer host bind sources'],
        [substr_count($output, 'value="csrf-test"') === 6, 'every mutation form includes a CSRF token'],
    ] as [$condition, $label]) {
        if (!$condition) {
            throw new \RuntimeException('FAIL: ' . $label);
        }
        echo 'ok: ' . $label . "\n";
    }
    $domain = '';
    ob_start();
    require APP_ROOT . '/Views/docker/controls.php';
    $rootOutput = ob_get_clean();
    if (!str_contains($rootOutput, '/var/lib/aidipanel/docker-data/app') || str_contains($rootOutput, '&quot;name&quot;:&quot;app-data&quot;')) {
        throw new \RuntimeException('FAIL: administrator form retains managed rootful bind mounts');
    }
    echo "Docker view tests passed\n";
}
