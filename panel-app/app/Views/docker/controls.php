<?php
$dockerStatus = is_array($dockerStatus ?? null) ? $dockerStatus : [];
$dockerDomain = (string) ($domain ?? '');
$dockerBase = $dockerDomain === '' ? '/admin/docker' : '/sites/' . rawurlencode($dockerDomain) . '/containers';
$dockerEnabled = !empty($dockerStatus['enabled']);
$dockerAvailable = !empty($dockerStatus['available']);
$dockerContainers = is_array($dockerStatus['containers'] ?? null) ? $dockerStatus['containers'] : [];
$dockerWritable = !demo_mode() && ($dockerDomain !== '' || \Core\Auth::isAdmin());
$dockerMount = $dockerDomain === '' ? ['source' => '/var/lib/aidipanel/docker-data/app'] : ['name' => 'app-data'];
$dockerMountExample = json_encode([$dockerMount + ['target' => '/data', 'readonly' => false]], JSON_UNESCAPED_SLASHES);
?>
<div class="space-y-5">
  <div class="card p-5 space-y-3">
    <h2 class="card-title"><?= e(t($dockerDomain === '' ? 'docker.rootful' : 'docker.rootless')) ?></h2>
    <p class="text-sm text-zinc-500"><?= e(t('docker.boundary')) ?></p>
    <p class="text-sm text-amber-800"><?= e(t('docker.backup_warning')) ?></p>
    <?php if (!$dockerAvailable): ?>
      <p class="text-sm text-zinc-500"><?= e(t('docker.unavailable')) ?></p>
    <?php elseif (!$dockerEnabled): ?>
      <p class="text-sm text-zinc-500"><?= e(t('docker.disabled')) ?></p>
      <?php if ($dockerDomain !== '' && \Core\Auth::isAdmin() && $dockerWritable): ?>
      <form method="POST" action="<?= e($dockerBase) ?>/enable">
        <input type="hidden" name="_csrf_token" value="<?= e($_csrf_token) ?>">
        <button class="btn btn-primary" type="submit"><?= e(t('docker.enable')) ?></button>
      </form>
      <?php endif; ?>
    <?php elseif ($dockerDomain !== '' && \Core\Auth::isAdmin() && $dockerWritable): ?>
      <form method="POST" action="<?= e($dockerBase) ?>/disable" class="flex flex-wrap items-center gap-3">
        <input type="hidden" name="_csrf_token" value="<?= e($_csrf_token) ?>">
        <label class="text-sm"><input type="checkbox" name="confirm" value="disable" required> <?= e(t('docker.disable_confirmation')) ?></label>
        <button class="btn btn-secondary" type="submit"><?= e(t('docker.disable')) ?></button>
      </form>
    <?php endif; ?>
  </div>

  <?php if ($dockerEnabled): ?>
  <div class="card p-5 overflow-x-auto">
    <h2 class="card-title mb-4"><?= e(t('docker.containers')) ?></h2>
    <?php if ($dockerContainers === []): ?>
      <p class="text-sm text-zinc-500"><?= e(t('docker.empty')) ?></p>
    <?php else: ?>
    <table class="w-full text-sm">
      <thead><tr class="text-left border-b border-zinc-200"><th class="p-2"><?= e(t('docker.name')) ?></th><th class="p-2"><?= e(t('docker.image')) ?></th><th class="p-2"><?= e(t('docker.status')) ?></th><th class="p-2"><?= e(t('docker.actions')) ?></th></tr></thead>
      <tbody>
      <?php foreach ($dockerContainers as $container):
          $dockerPorts = [];
          foreach ((array) ($container['ports'] ?? []) as $binding) {
              if (is_array($binding) && isset($binding['host'], $binding['container'])) {
                  $dockerPorts[] = '127.0.0.1:' . (int) $binding['host'] . ' → ' . (int) $binding['container'];
              }
          }
      ?>
      <tr class="border-b border-zinc-100">
        <td class="p-2 font-mono"><?= e((string) ($container['name'] ?? '')) ?></td>
        <td class="p-2 break-all"><?= e((string) ($container['image'] ?? '')) ?></td>
        <td class="p-2"><?= e((string) ($container['status'] ?? $container['state'] ?? '')) ?><br><span class="text-xs text-zinc-500"><?= e(implode(', ', $dockerPorts)) ?></span></td>
        <td class="p-2">
          <a class="btn btn-secondary" href="<?= e($dockerBase) ?>/logs?id=<?= e(rawurlencode((string) ($container['id'] ?? ''))) ?>"><?= e(t('docker.logs')) ?></a>
          <?php if ($dockerWritable): ?>
          <div class="flex flex-wrap gap-2 mt-2">
            <?php foreach (['start', 'stop', 'restart', 'remove'] as $operation): ?>
            <form method="POST" action="<?= e($dockerBase) ?>/<?= e($operation) ?>" class="flex flex-wrap items-center gap-2">
              <input type="hidden" name="_csrf_token" value="<?= e($_csrf_token) ?>">
              <input type="hidden" name="id" value="<?= e((string) ($container['id'] ?? '')) ?>">
              <?php if ($operation === 'remove'): ?><label class="text-xs"><input type="checkbox" name="confirm" value="remove" required> <?= e(t('docker.confirm')) ?></label><?php endif; ?>
              <button type="submit" class="btn btn-secondary"><?= e(t('docker.' . $operation)) ?></button>
            </form>
            <?php endforeach; ?>
          </div>
          <?php endif; ?>
        </td>
      </tr>
      <?php endforeach; ?>
      </tbody>
    </table>
    <?php endif; ?>
  </div>

  <?php if ($dockerWritable): ?>
  <form class="card p-5 space-y-4" method="POST" action="<?= e($dockerBase) ?>/create" autocomplete="off">
    <input type="hidden" name="_csrf_token" value="<?= e($_csrf_token) ?>">
    <h2 class="card-title"><?= e(t('docker.create')) ?></h2>
    <div class="grid grid-cols-1 md:grid-cols-2 gap-4">
      <label class="text-sm"><?= e(t('docker.name')) ?><input class="inp w-full mt-1" name="name" required maxlength="63" pattern="[a-zA-Z0-9][a-zA-Z0-9_.-]*" placeholder="my-app"></label>
      <label class="text-sm"><?= e(t('docker.image')) ?><input class="inp w-full mt-1" name="image" required maxlength="255" placeholder="nginx:alpine"></label>
    </div>
    <div class="grid grid-cols-1 md:grid-cols-3 gap-4">
      <label class="text-sm"><?= e(t('docker.cpus')) ?><input class="inp w-full mt-1" name="cpus" type="number" min="0.1" max="32" step="0.1" value="1" required></label>
      <label class="text-sm"><?= e(t('docker.memory')) ?><input class="inp w-full mt-1" name="memory_mb" type="number" min="16" max="65536" value="512" required></label>
      <label class="text-sm"><?= e(t('docker.pids')) ?><input class="inp w-full mt-1" name="pids_limit" type="number" min="16" max="4096" value="128" required></label>
    </div>
    <label class="block text-sm"><?= e(t('docker.environment')) ?><textarea class="inp w-full mt-1 font-mono" name="environment" rows="3" maxlength="32768" spellcheck="false">{}</textarea></label>
    <label class="block text-sm"><?= e(t('docker.ports')) ?><textarea class="inp w-full mt-1 font-mono" name="ports" rows="2" maxlength="32768" spellcheck="false" placeholder='[{"host":8080,"container":80}]'>[]</textarea></label>
    <label class="block text-sm"><?= e(t($dockerDomain === '' ? 'docker.volumes' : 'docker.named_volumes')) ?><textarea class="inp w-full mt-1 font-mono" name="volumes" rows="2" maxlength="32768" spellcheck="false" placeholder="<?= e($dockerMountExample) ?>">[]</textarea></label>
    <p class="text-xs text-zinc-500"><?= e(t('docker.create_hint')) ?></p>
    <button class="btn btn-primary" type="submit"><?= e(t('docker.create')) ?></button>
  </form>
  <?php endif; ?>
  <?php endif; ?>
</div>
