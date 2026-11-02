#!/usr/bin/env node
// Fixture isolation check (SP-S8A acceptance 2; no-demo-fallback, KIOSK-4).
//
// Fails if anything under src/web/ references the test fixtures: tests/web/fixtures/, any
// `fixtures/` path, or the synthetic feed by name, through import/export, dynamic import(),
// <script src>, fetch, Worker or any other string. A synthetic state generator reachable from
// the visitor UI would be a demo fallback, which the plan forbids.
//
//   node tests/web/check-fixture-isolation.mjs [dir]     (default: <repo>/src/web)
// Exit 0 clean (or dir absent), 1 on a violation, with file:line and a plain message.

import { readdirSync, readFileSync, statSync, existsSync } from 'node:fs';
import { join, resolve, dirname, relative, extname } from 'node:path';
import { fileURLToPath } from 'node:url';

const SCANNED = new Set(['.js', '.mjs', '.cjs', '.html', '.htm', '.css', '.json', '.svg']);
const PATTERNS = [
  { re: /tests\/web/, why: 'references tests/web/' },
  { re: /(^|[\/'"`(\s])fixtures\//, why: 'references a fixtures/ path' },
  { re: /synthetic[-_]?feed/i, why: 'references the synthetic feed' },
  { re: /createSyntheticFeed/, why: 'calls the synthetic feed generator' },
];

function* walk(dir) {
  for (const name of readdirSync(dir)) {
    if (name === 'node_modules') continue;
    const p = join(dir, name);
    const st = statSync(p);
    if (st.isDirectory()) yield* walk(p);
    else if (SCANNED.has(extname(name).toLowerCase())) yield p;
  }
}

export function checkIsolation(dir) {
  const violations = [];
  if (!existsSync(dir)) return { scanned: 0, violations, absent: true };
  let scanned = 0;
  for (const file of walk(dir)) {
    scanned++;
    const lines = readFileSync(file, 'utf8').split('\n');
    lines.forEach((line, i) => {
      for (const { re, why } of PATTERNS) {
        if (re.test(line)) violations.push({ file, line: i + 1, why, text: line.trim().slice(0, 120) });
      }
    });
  }
  return { scanned, violations, absent: false };
}

const here = dirname(fileURLToPath(import.meta.url));
if (process.argv[1] && resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  const dir = resolve(process.argv[2] || join(here, '..', '..', 'src', 'web'));
  const r = checkIsolation(dir);
  if (r.absent) {
    console.log(`fixture isolation: ${dir} does not exist yet; nothing to check (pass)`);
  } else if (r.violations.length) {
    for (const v of r.violations) {
      console.error(`${relative(process.cwd(), v.file)}:${v.line}: ${v.why}. Test fixtures must never be ` +
        `reachable from src/web (no demo fallback). Found: ${v.text}`);
    }
    process.exit(1);
  } else {
    console.log(`fixture isolation: ${r.scanned} files under ${dir}, no fixture references (pass)`);
  }
}
