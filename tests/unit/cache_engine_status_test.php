<?php
declare(strict_types=1);
require __DIR__ . '/../../panel-app/app/Core/helpers.php';
$configPath = tempnam(sys_get_temp_dir(), 'aidipanel-cache-');
try {
    foreach ([
        ['INSTALL_REDIS=true', 'redis', 'redis-server'],
        ['INSTALL_REDIS=false', 'none', null],
        ["CACHE_ENGINE=valkey\nINSTALL_REDIS=true", 'valkey', 'valkey-server'],
        ['CACHE_ENGINE=none', 'none', null],
        ['CACHE_ENGINE=invalid', 'none', null],
        ["CACHE_ENGINE=valkey\n[malformed", 'none', null],
        ['', 'redis', 'redis-server'],
    ] as [$configuration, $expectedEngine, $expectedService]) {
        file_put_contents($configPath, $configuration);
        if (cache_engine($configPath) !== $expectedEngine || cache_service($configPath) !== $expectedService) {
            throw new RuntimeException('Incorrect persisted cache engine/service: ' . $configuration);
        }
    }
    echo "cache engine PHP status contract passed\n";
} finally {
    unlink($configPath);
}
