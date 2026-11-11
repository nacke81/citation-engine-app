'use strict';
// Real temp dir for the vault helpers (t_d7a907d5). Under git-bash $TMPDIR is POSIX ("/tmp"); node on Windows reads that as C:\tmp, which does not exist (ENOENT).
// realTmpDir() trusts env.TMPDIR only when it is an existing directory as node sees it; otherwise os.tmpdir().
// resolvePayloadPath() maps a POSIX-looking path that does not exist for node ("/tmp/x.json", "/c/Users/..") to the real temp dir / drive path.
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');

function isDir(p) { try { return fs.statSync(p).isDirectory(); } catch { return false; } }

function realTmpDir(env = process.env) {
  const t = env.TMPDIR;
  if (t && !/^\/(?![A-Za-z]\/)/.test(t) && isDir(t)) return t;   // a Windows-style path that exists
  if (t && /^\/[A-Za-z]\//.test(t)) { const d = t[1].toUpperCase() + ':' + t.slice(2); if (isDir(d)) return d; }   // /c/Users/... -> C:/Users/...
  return os.tmpdir();
}

function resolvePayloadPath(p, env = process.env) {
  if (!p || fs.existsSync(p)) return p;
  const m = /^\/([A-Za-z])\/(.*)$/.exec(p);
  if (m) { const q = m[1].toUpperCase() + ':/' + m[2]; if (fs.existsSync(q)) return q; }
  const t = /^\/(?:tmp|var\/tmp)\/(.+)$/.exec(p);
  if (t) { const q = path.join(realTmpDir(env), t[1]); if (fs.existsSync(q)) return q; }
  return p;   // let the caller's ENOENT name the original path
}

module.exports = { realTmpDir, resolvePayloadPath };
