import assert from 'node:assert/strict';
import { execFileSync, spawnSync } from 'node:child_process';
import { createRequire } from 'node:module';
import { copyFileSync, mkdirSync, mkdtempSync, readFileSync, rmSync, symlinkSync, writeFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { test } from 'node:test';

const panelRoot = fileURLToPath(new URL('../../panel-app/', import.meta.url));
const require = createRequire(`${panelRoot}/package.json`);
const { JSDOM } = require('jsdom');

function editorWindow() {
  const browser = new JSDOM('<!doctype html><html><head></head><body><div id="editor"></div></body></html>', {
    runScripts: 'outside-only', pretendToBeVisual: true, url: 'https://panel.example.test',
  });
  browser.window.Range.prototype.getClientRects = () => [];
  browser.window.Range.prototype.getBoundingClientRect = () => ({ left: 0, right: 0, top: 0, bottom: 0 });
  assert.doesNotThrow(() => browser.window.eval(readFileSync(`${panelRoot}/public/assets/vendor/codemirror.js`, 'utf8')),
    'the self-hosted editor bundle must initialize with all mode dependencies');
  return browser;
}

test('the self-hosted editor preserves text, highlighting, history, search, indentation and disposal', () => {
  const browser = editorWindow();
  try {
    const { window } = browser;
    assert.equal(typeof window.AidiEditor?.create, 'function', 'the vendored editor must expose its CodeMirror 6 integration');
    let changes = 0;
    const editor = window.AidiEditor.create(window.document.getElementById('editor'), {
      value: '<?php\necho "Hello ✓";\n', filename: 'index.php', onChange: () => { changes += 1; },
    });
    assert.equal(changes, 0, 'opening a file must not mark it dirty');
    assert.equal(editor.getValue(), '<?php\necho "Hello ✓";\n');
    assert.equal(editor.modeName, 'php');
    assert.ok(window.document.querySelector('.cm-lineNumbers'));
    assert.ok(window.document.querySelector('.cm-content span'), 'PHP tokens must receive highlighting');
    editor.view.dispatch({ changes: { from: 0, insert: ' ' } });
    assert.equal(changes, 1);
    assert.equal(editor.getValue(), ' <?php\necho "Hello ✓";\n');
    editor.view.contentDOM.dispatchEvent(new window.KeyboardEvent('keydown', { key: 'z', ctrlKey: true, bubbles: true }));
    assert.equal(editor.getValue(), '<?php\necho "Hello ✓";\n');
    editor.view.dispatch({ selection: { anchor: 0 } });
    editor.view.contentDOM.dispatchEvent(new window.KeyboardEvent('keydown', { key: 'Tab', bubbles: true }));
    assert.ok(editor.getValue().startsWith('  <?php'), 'Tab must indent by two spaces');
    editor.view.contentDOM.dispatchEvent(new window.KeyboardEvent('keydown', { key: 'f', ctrlKey: true, bubbles: true }));
    assert.ok(window.document.querySelector('.cm-search input'), 'the editor must offer local search');
    editor.destroy();
    assert.equal(window.document.querySelector('.cm-editor'), null);
  } finally {
    browser.window.close();
  }
});

test('the editor retains bundled languages and filename detection without network requests', () => {
  const browser = editorWindow();
  try {
    assert.equal(typeof browser.window.AidiEditor?.create, 'function');
    const fixtures = [
      ['main.tsx', 'javascript', 'const element = <div/>;'],
      ['page.html', 'htmlmixed', '<div>Hello</div>'], ['theme.scss', 'css', '$color: red;'],
      ['data.json', 'javascript', '{"value": true}'], ['image.svg', 'xml', '<svg/>'],
      ['README.md', 'markdown', '# Heading'], ['config.yaml', 'yaml', 'name: panel'],
      ['query.sql', 'sql', 'SELECT * FROM sites;'], ['script.sh', 'shell', 'echo hello'],
      ['main.py', 'python', 'def hello():\n  return True'], ['main.cpp', 'clike', 'int main() {}'],
      ['Main.java', 'clike', 'class Main {}'], ['main.cs', 'clike', 'class Main {}'],
      ['default.conf', 'nginx', 'server { listen 80; }'], ['Dockerfile', 'dockerfile', 'FROM alpine'],
      ['.env.production', 'properties', 'APP_ENV=production'], ['.bashrc', 'shell', 'export PATH=/bin'],
      ['.editorconfig', 'properties', 'root = true'], ['unknown.data', 'text', 'hello'],
    ];
    for (const [filename, modeName, value] of fixtures) {
      const editor = browser.window.AidiEditor.create(browser.window.document.getElementById('editor'), { filename, value });
      assert.equal(editor.modeName, modeName, filename);
      assert.equal(editor.getValue(), value, filename);
      if (modeName !== 'text') assert.ok(browser.window.document.querySelector('.cm-content span'), filename);
      editor.destroy();
    }
    assert.equal(browser.window.document.querySelectorAll('script[src], link[href]').length, 0);
  } finally {
    browser.window.close();
  }
});

test('the migrated file manager saves the current editor text with its original conflict hash', async () => {
  const browser = editorWindow();
  try {
    const html = execFileSync('php', ['-r', `
      define('PUBLIC_ROOT', $argv[1] . '/public');
      define('PANEL_VERSION', 'test');
      function e($value) { return htmlspecialchars((string) $value, ENT_QUOTES); }
      function t($value) { return $value; }
      function icon(...$arguments) { return '<svg></svg>'; }
      $site = ['site_user' => 'example']; $domain = 'example.test';
      include $argv[1] . '/app/Views/sites/files.php';
    `, panelRoot], { encoding: 'utf8' });
    const document = new JSDOM(html).window.document;
    const source = [...document.querySelectorAll('script')].map(script => script.textContent).join('\n');
    browser.window.eval(source);
    const manager = browser.window.fileManager('example.test');
    manager.$refs = { cmHost: browser.window.document.getElementById('editor') };
    manager.$nextTick = callback => callback();
    manager.load = async () => {};
    const requests = [];
    browser.window.AidiToast = () => {};
    browser.window.api = async (path, method, payload) => {
      requests.push({ path, method, payload });
      return method === 'POST' ? { error: 'conflict' } : { success: true, data: { content: 'original', sha256: 'original-hash' } };
    };
    await manager.openEditor({ name: 'index.php' });
    assert.equal(manager.editor.dirty, false);
    const content = browser.window.document.querySelector('.cm-content');
    assert.ok(content, 'the file manager must create the migrated editor');
    const { EditorView } = require('@codemirror/view');
    const view = EditorView.findFromDOM(content);
    view.dispatch({ changes: { from: 0, to: view.state.doc.length, insert: 'changed ✓' } });
    assert.equal(manager.editor.dirty, true);
    manager.tryClose();
    assert.equal(manager.editor.confirmClose, true);
    await manager.saveEditor();
    assert.equal(requests[1].path, '/sites/example.test/files/save');
    assert.equal(requests[1].payload.content, 'changed ✓');
    assert.equal(requests[1].payload.expect_sha256, 'original-hash');
    assert.equal(manager.editor.open, true, 'a conflicting save must retain unsaved edits');
    browser.window.api = async () => ({ success: true });
    await manager.saveEditor();
    assert.equal(manager.editor.open, false);
    assert.equal(browser.window.document.querySelector('.cm-editor'), null);
  } finally {
    browser.window.close();
  }
});

test('the vendored QR API still renders an enrollment URI without remote image URLs', () => {
  const browser = new JSDOM('', { runScripts: 'outside-only' });
  try {
    browser.window.eval(readFileSync(`${panelRoot}/public/assets/vendor/qrcode.min.js`, 'utf8'));
    const code = browser.window.qrcode(0, 'M');
    code.addData('otpauth://totp/AidiPanel:test?secret=JBSWY3DPEHPK3PXP&issuer=AidiPanel');
    code.make();
    const result = new JSDOM(code.createImgTag(5, 8)).window.document.querySelector('img');
    assert.ok(result.src.startsWith('data:image/gif;base64,'));
    assert.ok(Number(result.width) > 100);
  } finally {
    browser.window.close();
  }
});

test('the generated Tailwind stylesheet preserves the panel theme and small-radius utilities', () => {
  const stylesheet = readFileSync(`${panelRoot}/public/assets/tailwind.css`, 'utf8');
  const browser = new JSDOM(`<style>${stylesheet}</style><button class="text-ink rounded-sm w-full">Panel</button>`);
  try {
    const style = browser.window.getComputedStyle(browser.window.document.querySelector('button'));
    assert.equal(style.color, 'rgb(50, 44, 122)');
    assert.equal(style.width, '100%');
    assert.equal(style.borderRadius, '2px');
    assert.match(style.fontFamily, /Plus Jakarta Sans/);
  } finally {
    browser.window.close();
  }
});

test('the asset build refuses an ApexCharts license change before distributing its bundle', () => {
  const fixture = mkdtempSync(`${panelRoot}/.frontend-licensing-test-`);
  try {
    for (const directory of ['build', 'node_modules/apexcharts/dist', 'public/assets/vendor']) {
      mkdirSync(`${fixture}/${directory}`, { recursive: true });
    }
    copyFileSync(`${panelRoot}/build/vendor-assets.mjs`, `${fixture}/build/vendor-assets.mjs`);
    symlinkSync(`${panelRoot}/node_modules/@fontsource`, `${fixture}/node_modules/@fontsource`, 'dir');
    writeFileSync(`${fixture}/node_modules/apexcharts/package.json`, JSON.stringify({
      name: 'apexcharts', version: '8.8.1', license: 'SEE LICENSE IN LICENSE.md',
    }));
    writeFileSync(`${fixture}/node_modules/apexcharts/dist/apexcharts.min.js`, 'commercial-license-fixture');
    const bundlePath = `${fixture}/public/assets/vendor/apexcharts.min.js`;
    writeFileSync(bundlePath, 'approved-chart-bundle');
    const result = spawnSync(process.execPath, ['build/vendor-assets.mjs'], { cwd: fixture, encoding: 'utf8' });
    assert.notEqual(result.status, 0);
    assert.match(result.stderr, /ApexCharts upgrades require an explicit redistribution-license review/);
    assert.equal(readFileSync(bundlePath, 'utf8'), 'approved-chart-bundle');
  } finally {
    rmSync(fixture, { recursive: true, force: true });
  }
});

test('the distributed notices include the chart bundle dependencies as well as the editor and fonts', () => {
  const notices = readFileSync(`${panelRoot}/public/assets/vendor/THIRD-PARTY-LICENSES.txt`, 'utf8');
  for (const packageName of ['@svgdotjs/svg.js', '@svgdotjs/svg.filter.js', '@yr/monotone-cubic-spline',
    '@codemirror/state', '@fontsource/plus-jakarta-sans', 'alpinejs', 'qrcode-generator']) {
    assert.ok(notices.includes(packageName + ' '), `missing shipped license for ${packageName}`);
  }
});
