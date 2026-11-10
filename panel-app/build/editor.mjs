import { basicSetup, EditorView } from 'codemirror';
import { EditorState } from '@codemirror/state';
import { indentUnit, StreamLanguage } from '@codemirror/language';
import { indentWithTab } from '@codemirror/commands';
import { keymap } from '@codemirror/view';
import { oneDark } from '@codemirror/theme-one-dark';
import { php } from '@codemirror/lang-php';
import { javascript } from '@codemirror/lang-javascript';
import { html } from '@codemirror/lang-html';
import { css } from '@codemirror/lang-css';
import { json } from '@codemirror/lang-json';
import { xml } from '@codemirror/lang-xml';
import { markdown } from '@codemirror/lang-markdown';
import { python } from '@codemirror/lang-python';
import { sql } from '@codemirror/lang-sql';
import { c, cpp, java, csharp } from '@codemirror/legacy-modes/mode/clike';
import { sCSS, less } from '@codemirror/legacy-modes/mode/css';
import { yaml } from '@codemirror/legacy-modes/mode/yaml';
import { shell } from '@codemirror/legacy-modes/mode/shell';
import { nginx } from '@codemirror/legacy-modes/mode/nginx';
import { dockerFile } from '@codemirror/legacy-modes/mode/dockerfile';
import { properties } from '@codemirror/legacy-modes/mode/properties';

function languageFor(filename) {
  const lower = filename.toLowerCase();
  const extension = lower.includes('.') ? lower.split('.').pop() : lower;
  if (lower === '.env' || lower.startsWith('.env.') || ['.gitconfig', '.editorconfig', '.npmrc'].includes(lower)) {
    return ['properties', StreamLanguage.define(properties)];
  }
  if (/^\.(profile|bashrc|bash_profile|bash_logout|zshrc|zprofile|zshenv|kshrc)$/.test(lower)) {
    return ['shell', StreamLanguage.define(shell)];
  }
  if (/^(php\d*|phtml)$/.test(extension)) return ['php', php()];
  if (['js', 'mjs', 'cjs', 'jsx', 'ts', 'tsx'].includes(extension)) {
    return ['javascript', javascript({ typescript: ['ts', 'tsx'].includes(extension), jsx: ['jsx', 'tsx'].includes(extension) })];
  }
  if (extension === 'json') return ['javascript', json()];
  if (extension === 'css') return ['css', css()];
  if (['scss', 'sass', 'less'].includes(extension)) return ['css', StreamLanguage.define(extension === 'less' ? less : sCSS)];
  if (['html', 'htm', 'vue', 'twig', 'blade'].includes(extension)) return ['htmlmixed', html()];
  if (['xml', 'svg', 'xsl', 'rss'].includes(extension)) return ['xml', xml()];
  if (['md', 'markdown'].includes(extension)) return ['markdown', markdown()];
  if (extension === 'py') return ['python', python()];
  if (extension === 'sql') return ['sql', sql()];
  const legacy = {
    yml: ['yaml', yaml], yaml: ['yaml', yaml], sh: ['shell', shell], bash: ['shell', shell], zsh: ['shell', shell],
    c: ['clike', c], h: ['clike', c], cpp: ['clike', cpp], cc: ['clike', cpp], hpp: ['clike', cpp],
    java: ['clike', java], cs: ['clike', csharp], conf: ['nginx', nginx], nginx: ['nginx', nginx],
    ini: ['properties', properties], toml: ['properties', properties], env: ['properties', properties],
    dockerfile: ['dockerfile', dockerFile],
  }[extension];
  return legacy ? [legacy[0], StreamLanguage.define(legacy[1])] : ['text', []];
}

export function create(parent, { value, filename, onChange = () => {} }) {
  const [modeName, language] = languageFor(filename);
  const view = new EditorView({
    parent,
    state: EditorState.create({
      doc: value,
      extensions: [basicSetup, language, oneDark, indentUnit.of('  '), EditorState.tabSize.of(2),
        keymap.of([indentWithTab]), EditorView.updateListener.of(update => { if (update.docChanged) onChange(); }),
        EditorView.theme({
          '&': { height: '100%', fontSize: '13px' },
          '.cm-scroller': { overflow: 'auto', fontFamily: "'JetBrains Mono', ui-monospace, monospace" },
        }),
      ],
    }),
  });
  view.focus();
  return { view, modeName, getValue: () => view.state.doc.toString(), destroy: () => view.destroy() };
}
