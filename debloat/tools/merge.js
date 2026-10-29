const fs = require('fs');
const path = require('path');
const Path = path;
// Vendored from Vetro 0.2.3+ (MIT) - see third_party/vetro/ and THIRD_PARTY_NOTICES.md
const catalog = require('../third_party/vetro/app-catalog.js');
// Usage: node tools/merge.js [registry-dump.txt] [out-inventory.json]
//   defaults: models/qnx1d/registry-dump.txt -> models/qnx1d/qnx1d-inventory.json
// MANUAL OVERRIDES to know when regenerating: com.samsung.tv.iacr and
// com.samsung.tv.screen-analysis-dbmgr classify as tracking under the current
// catalog, but this project keeps them OUT of the disable tiers
// (screen-analysis: tcc measured picture-processing breakage; iacr: coupling
// unknown) - that decision is encoded in the tier lists, not here.

const dump = process.argv[2] || Path.resolve(__dirname, '../models/qnx1d/registry-dump.txt');
const rows = fs.readFileSync(dump, 'utf8').split('\n')
  .filter(l => l.includes('|'))
  .map(l => {
    const [pkg, type, removable, preload, system, disable, mainapp] = l.trim().split('|');
    return { pkg, type, removable, preload, system, disable, mainapp: mainapp || '' };
  });

const out = rows.map(r => {
  const d = catalog.describe({ packageId: r.pkg, appId: r.mainapp, origin: r.preload === 'true' ? 'preloaded' : 'installed' });
  return {
    package: r.pkg, type: r.type, mainApp: r.mainapp,
    removable: r.removable === 'true', preloaded: r.preload === 'true',
    system: r.system === 'true', disabled: r.disable === 'true',
    area: d.area, role: d.role, purpose: d.purpose,
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
  JSON.stringify({ generated: '2026-10-27', source: 'live QNX1D /opt/dbspace/.pkgmgr_parser.db (446 packages) classified with Vetro 0.2.3 app-catalog rules (Q80A T-NKM2DEUC manifests)', summary, packages: out }, null, 1));
console.log('summary:', JSON.stringify(summary));
