const fs = require('fs');
const path = require('path');
const catalog = require('C:/Users/Raghav/Documents/projects/samsungtv/vetro/app/service/app-catalog.js');

const rows = fs.readFileSync('C:/Users/Raghav/AppData/Local/Temp/qnx_pkginfo.txt', 'utf8').split('\n')
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

fs.writeFileSync('C:/Users/Raghav/Documents/projects/samsung_tv_root/docs/debloat/qnx1d-inventory.json',
  JSON.stringify({ generated: '2026-10-27', source: 'live QNX1D /opt/dbspace/.pkgmgr_parser.db (446 packages) classified with Vetro 0.2.3 app-catalog rules (Q80A T-NKM2DEUC manifests)', summary, packages: out }, null, 1));
console.log('summary:', JSON.stringify(summary));
