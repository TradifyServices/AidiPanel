<?php $pageTitle = t('docker.logs'); ?>
<div class="space-y-4">
  <a class="btn btn-secondary" href="<?= e($backUrl) ?>"><?= e(t('common.back')) ?></a>
  <h1 class="text-xl font-semibold"><?= e($pageTitle) ?></h1>
  <pre class="bg-zinc-900 text-zinc-100 text-xs rounded-lg p-5 overflow-auto max-h-[70vh]"><?= e($logs) ?></pre>
</div>
