const fs = require('fs');
const path = require('path');
const Path = path;
// Vendored from Vetro 0.3.5 (tag v0.3.5; app/service/ byte-identical), MIT
// - see third_party/vetro/LICENSE
const catalog = require('../third_party/vetro/app-catalog.js');
// Usage: node tools/merge.js [registry-dump.txt] [out-inventory.json]
//   defaults: models/qnx1d/registry-dump.txt -> models/qnx1d/qnx1d-inventory.json
// The two manual overrides are applied HERE, deliberately: Vetro's catalog
// classifies com.samsung.tv.iacr and com.samsung.tv.screen-analysis-dbmgr as
// tracking, but this project keeps them OUT of the disable tiers
// (screen-analysis: tcc measured picture-processing breakage; iacr: coupling
// unknown).  Applying them in the merge keeps a regen deterministic instead of
// relying on someone to hand-edit the output afterwards.  test_debloat checks
// both the override values and that a regen has no flips.
const OVERRIDES = {
  'com.samsung.tv.iacr': { area: 'system', role: 'keep' },
  'com.samsung.tv.screen-analysis-dbmgr': { area: 'system', role: 'keep' },
};

const dump = process.argv[2] || Path.resolve(__dirname, '../models/qnx1d/registry-dump.txt');
const rows = fs.readFileSync(dump, 'utf8').split('\n')
  .filter(l => l.includes('|'))
  .map(l => {
    const [pkg, type, removable, preload, system, disable, mainapp] = l.trim().split('|');
    return { pkg, type, removable, preload, system, disable, mainapp: mainapp || '' };
  });

const out = rows.map(r => {
  const d = catalog.describe({ packageId: r.pkg, appId: r.mainapp, origin: r.preload === 'true' ? 'preloaded' : 'installed' });
  const o = OVERRIDES[r.pkg];
  return {
    package: r.pkg, type: r.type, mainApp: r.mainapp,
    removable: r.removable === 'true', preloaded: r.preload === 'true',
    system: r.system === 'true', disabled: r.disable === 'true',
    area: o ? o.area : d.area, role: o ? o.role : d.role, purpose: d.purpose,
    referencedBy: d.referencedBy, source: d.source,
  };
});

const byRole = {};
for (const e of out) (byRole[e.role] = byRole[e.role] || []).push(e);
const summary = {};
for (const [role, list] of Object.entries(byRole)) summary[role] = list.length;
summary.total = out.length;

const outFile = process.argv[3] || Path.resolve(__dirname, '../models/qnx1d/qnx1d-inventory.json');
fs.writeFileSync(outFile,
  JSON.stringify({ generated: '2026-10-27', source: 'live QNX1D /opt/dbspace/.pkgmgr_parser.db (446 packages) classified with Vetro 0.3.5 app-catalog rules (Q80A T-NKM2DEUC manifests)', summary, packages: out }, null, 1));
console.log('summary:', JSON.stringify(summary));
