<?php
declare(strict_types=1);

namespace Core {
    final class Auth
    {
        public static bool $administrator = true;
        public static function isAdmin(): bool { return self::$administrator; }
        public static function user(): array { return ['id' => 1, 'username' => 'admin']; }
    }
    final class DB
    {
        public static array $events = [];
        public static function instance(): self { return new self(); }
        public function row(string $query, array $params = []): array { return ['id' => 1]; }
        public static function log(string $event, string $message): void { self::$events[] = [$event, $message]; }
    }
    final class Access
    {
        public static function canManageSite(string $domain): bool { return $domain === 'owned.example'; }
    }
}

namespace Controllers {
    function abort(int $code, string $message = ''): never
    {
        throw new \RuntimeException($message, $code);
    }

    function run_cli_stdin(string $command, array $args, string $stdin): array
    {
        $GLOBALS['dockerCall'] = [$command, $args, $stdin];
        return ['success' => true, 'output' => '{"success":true}', 'code' => 0];
    }
}

namespace {
    $root = dirname(__DIR__, 2);
    define('APP_ROOT', $root . '/panel-app/app');
    require APP_ROOT . '/Core/helpers.php';
    require APP_ROOT . '/Core/Request.php';
    require APP_ROOT . '/Controllers/BaseController.php';
    $controllerPath = APP_ROOT . '/Controllers/DockerController.php';
    if (!is_file($controllerPath)) {
        throw new \RuntimeException('FAIL: Docker controller is not implemented');
    }
    require $controllerPath;
    require APP_ROOT . '/Controllers/SystemController.php';

    final class CapturedDockerResponse extends \RuntimeException {}
    final class DockerTestController extends \Controllers\DockerController
    {
        protected function unlockForLongOp(): void {}
        protected function success(string $message, string $redirect = ''): never
        {
            throw new CapturedDockerResponse($redirect);
        }
        protected function error(string $message, string $redirect = ''): never
        {
            throw new \RuntimeException($message);
        }
    }

    final class DockerApiTestController extends \Controllers\SystemController
    {
        protected function json(mixed $data, int $code = 200): never
        {
            throw new \RuntimeException(json_encode($data, JSON_THROW_ON_ERROR), $code);
        }
    }

    function checkController(bool $condition, string $label): void
    {
        if (!$condition) {
            throw new \RuntimeException('FAIL: ' . $label);
        }
        echo 'ok: ' . $label . "\n";
    }

    $_POST = [
        'name' => 'app', 'image' => 'nginx:alpine', 'cpus' => '1', 'memory_mb' => '512', 'pids_limit' => '128',
        'environment' => '{"API_TOKEN":"do-not-log-me"}', 'ports' => '[{"host":8080,"container":80}]',
        'volumes' => '[{"name":"app-data","target":"/data","readonly":false}]', 'domain' => 'foreign.example', 'user' => 'root', 'scope' => 'root',
    ];
    $controller = new DockerTestController(new \Core\Request());
    try {
        $controller->manage(['domain' => 'owned.example', 'operation' => 'create']);
    } catch (CapturedDockerResponse $response) {
        checkController($response->getMessage() === '/sites/owned.example?tab=containers', 'redirect stays in the authorized site');
    }
    [$command, $arguments, $stdin] = $GLOBALS['dockerCall'];
    checkController($command === 'docker:create', 'create invokes the fixed command');
    checkController($arguments === ['--domain', 'owned.example'], 'posted domain/user/scope cannot override route identity');
    $specification = json_decode($stdin, true, 64, JSON_THROW_ON_ERROR);
    checkController($specification['environment']['API_TOKEN'] === 'do-not-log-me', 'environment values travel on stdin');
    checkController($specification['volumes'] === [['name' => 'app-data', 'target' => '/data', 'readonly' => false]], 'site managed volume specification travels unchanged on stdin');
    checkController(!isset($specification['user'], $specification['scope']), 'specification excludes identity overrides');
    checkController(!str_contains(json_encode(\Core\DB::$events), 'do-not-log-me'), 'activity log never contains environment values');

    $_POST = ['id' => str_repeat('a', 64), 'domain' => 'foreign.example'];
    try {
        $controller->manage(['domain' => 'owned.example', 'operation' => 'stop']);
    } catch (CapturedDockerResponse $response) {
        checkController($GLOBALS['dockerCall'][0] === 'docker:stop', 'lifecycle operation uses the fixed command');
        checkController(json_decode($GLOBALS['dockerCall'][2], true) === ['id' => str_repeat('a', 64)], 'lifecycle stdin contains only a container ID');
    }
    $_POST = ['environment' => 'not-json'];
    try {
        $controller->manage(['domain' => 'owned.example', 'operation' => 'create']);
        throw new \RuntimeException('FAIL: malformed JSON accepted');
    } catch (\RuntimeException $response) {
        checkController(str_contains($response->getMessage(), 'JSON'), 'malformed structured input is rejected');
    }

    $_POST = ['name' => 'app', 'image' => 'nginx:alpine', 'cpus' => '1e999'];
    try {
        $controller->manage(['domain' => 'owned.example', 'operation' => 'create']);
        throw new \RuntimeException('FAIL: non-finite CPU accepted');
    } catch (\RuntimeException | \JsonException $response) {
        checkController(str_contains($response->getMessage(), 'CPU'), 'non-finite CPU is rejected before JSON transport');
    }

    \Core\Auth::$administrator = false;
    foreach ([['operation' => 'create'], ['domain' => 'owned.example', 'operation' => 'enable'], ['domain' => 'foreign.example', 'operation' => 'stop']] as $parameters) {
        try {
            $controller->manage($parameters);
            throw new \RuntimeException('FAIL: unauthorized operation accepted');
        } catch (\RuntimeException $response) {
            checkController(in_array($response->getCode(), [403, 404], true), 'controller independently denies unauthorized scope/provisioning');
        }
    }
    foreach (['docker:create', 'docker:list', 'docker:enable', 'docker:exec'] as $command) {
        $_POST = ['command' => $command];
        try {
            (new DockerApiTestController(new \Core\Request()))->apiCli();
            throw new \RuntimeException('FAIL: generic API accepted Docker');
        } catch (\RuntimeException $response) {
            checkController($response->getCode() === 403, 'generic CLI API rejects ' . $command);
        }
    }
    echo "Docker controller tests passed\n";
}
