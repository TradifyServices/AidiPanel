<?php
declare(strict_types=1);
namespace Controllers;

use Core\Access;
use Core\Auth;
use Core\DB;

class DockerController extends BaseController
{
    public function index(array $params = []): void
    {
        $this->context([]);
        $dockerStatus = ['available' => false, 'enabled' => false, 'containers' => []];
        if (!demo_mode()) {
            $result = run_cli('docker:status');
            $decoded = json_decode((string) ($result['output'] ?? ''), true);
            if (!empty($result['success']) && is_array($decoded)) {
                $dockerStatus = array_replace($dockerStatus, $decoded);
            }
        }
        $this->view('docker/index', compact('dockerStatus'));
    }

    public function enable(array $params = []): never
    {
        $this->manage(array_merge($params, ['operation' => 'enable']));
    }

    public function disable(array $params = []): never
    {
        $this->manage(array_merge($params, ['operation' => 'disable']));
    }

    public function manage(array $params = []): never
    {
        [$domain, $arguments, $redirect] = $this->context($params);
        $operation = (string) ($params['operation'] ?? '');
        if (!in_array($operation, ['create', 'start', 'stop', 'restart', 'remove', 'enable', 'disable'], true)) {
            $this->error('Unsupported container operation.', $redirect);
        }
        if (in_array($operation, ['enable', 'disable'], true) && (!Auth::isAdmin() || $domain === '')) {
            abort(403, 'Administrator access and a site are required.');
        }

        $payload = [];
        if ($operation === 'create') {
            $payload = $this->createSpecification($redirect);
        } elseif (!in_array($operation, ['enable', 'disable'], true)) {
            $payload = ['id' => $this->containerId((string) $this->request->post('id', ''), $redirect)];
        }
        if ($operation === 'remove' && $this->request->post('confirm') !== 'remove') {
            $this->error('Confirm container removal first.', $redirect);
        }
        if ($operation === 'disable' && $this->request->post('confirm') !== 'disable') {
            $this->error('Confirm rootless Docker shutdown first.', $redirect);
        }
        $this->unlockForLongOp();
        $result = run_cli_stdin('docker:' . $operation, $arguments, json_encode((object) $payload, JSON_THROW_ON_ERROR));
        DB::log('docker.' . $operation, 'scope=' . ($domain ?: 'root') . ' actor=' . (string) (Auth::user()['username'] ?? 'system') . ' ' . (!empty($result['success']) ? 'ok' : 'fail'));
        if (empty($result['success'])) {
            $this->error($this->failureMessage($result), $redirect);
        }
        $this->success('Docker operation completed.', $redirect);
    }

    public function logs(array $params = []): void
    {
        [, $arguments, $redirect] = $this->context($params);
        $identifier = $this->containerId((string) $this->request->get('id', ''), $redirect);
        $this->unlockForLongOp();
        $result = run_cli_stdin('docker:logs', $arguments, json_encode(['id' => $identifier], JSON_THROW_ON_ERROR));
        if (empty($result['success'])) {
            $this->error($this->failureMessage($result), $redirect);
        }
        $decoded = json_decode((string) ($result['output'] ?? ''), true);
        $logs = is_string($decoded['logs'] ?? null) ? substr($decoded['logs'], 0, 65536) : '';
        header('Cache-Control: no-store');
        $this->view('docker/logs', ['logs' => $logs, 'backUrl' => $redirect]);
    }

    private function context(array $params): array
    {
        $domain = (string) ($params['domain'] ?? '');
        if ($domain === '') {
            if (!Auth::isAdmin()) {
                abort(403, 'Administrator access required.');
            }
            return ['', [], '/admin/docker'];
        }
        if (!is_valid_domain($domain) || !Access::canManageSite($domain)
            || !$this->db->row('SELECT id FROM sites WHERE domain = ?', [$domain])) {
            abort(404, 'Site not found.');
        }
        return [$domain, ['--domain', $domain], '/sites/' . rawurlencode($domain) . '?tab=containers'];
    }

    private function createSpecification(string $redirect): array
    {
        $structured = [];
        foreach (['environment' => '{}', 'ports' => '[]', 'volumes' => '[]'] as $field => $default) {
            $value = $this->request->post($field, $default);
            if (!is_string($value) || strlen($value) > 32768) {
                $this->error('Invalid JSON field: ' . $field, $redirect);
            }
            try {
                $structured[$field] = json_decode($value, false, 16, JSON_THROW_ON_ERROR);
            } catch (\JsonException) {
                $this->error('Invalid JSON field: ' . $field, $redirect);
            }
            if (($field === 'environment' && !is_object($structured[$field]))
                || ($field !== 'environment' && !is_array($structured[$field]))) {
                $this->error('Unexpected JSON type: ' . $field, $redirect);
            }
        }
        $cpuValue = $this->request->post('cpus', 1);
        if (!is_scalar($cpuValue) || is_bool($cpuValue) || !is_numeric($cpuValue)
            || !is_finite((float) $cpuValue) || (float) $cpuValue <= 0) {
            $this->error('Invalid CPU limit.', $redirect);
        }
        $specification = $structured + ['cpus' => (float) $cpuValue];
        foreach (['memory_mb' => 512, 'pids_limit' => 128] as $field => $default) {
            $value = $this->request->post($field, $default);
            if (is_bool($value) || filter_var($value, FILTER_VALIDATE_INT) === false || (int) $value <= 0) {
                $this->error('Invalid resource limit: ' . $field, $redirect);
            }
            $specification[$field] = (int) $value;
        }
        foreach (['name', 'image'] as $field) {
            $value = $this->request->post($field, '');
            if (!is_string($value) || $value === '' || strlen($value) > 255) {
                $this->error('Invalid container field: ' . $field, $redirect);
            }
            $specification[$field] = $value;
        }
        return $specification;
    }

    private function containerId(string $identifier, string $redirect): string
    {
        if (!preg_match('/\A[a-f0-9]{12,64}\z/D', $identifier)) {
            $this->error('Invalid container ID.', $redirect);
        }
        return $identifier;
    }

    private function failureMessage(array $result): string
    {
        $decoded = json_decode((string) ($result['output'] ?? ''), true);
        return is_string($decoded['error'] ?? null)
            ? substr($decoded['error'], 0, 512)
            : 'Docker operation failed. Check Docker installation and rootless prerequisites.';
    }
}
