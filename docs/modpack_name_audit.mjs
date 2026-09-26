// Generate a sortable review sheet from the saved Modrinth pack inventory.
import fs from 'node:fs';
const inventory = JSON.parse(fs.readFileSync(new URL('./modpack_mod_inventory.json', import.meta.url)));
const extensions = JSON.parse(fs.readFileSync(new URL('../mod_cn_ext.json', import.meta.url))).entries;
const curated = fs.readFileSync(new URL('../mod_cn.py', import.meta.url), 'utf8');
const curatedNames = new Map([...curated.matchAll(/^    "([^"]+)": "([^"]*)",?$/gm)]
  .map(match => [match[1], match[2]]));
const occurrences = new Map();
for (const pack of inventory.packs) {
  for (const id of pack.mod_project_ids) {
    const list = occurrences.get(id) ?? [];
    list.push(pack.slug);
    occurrences.set(id, list);
  }
}
const quote = value => `"${String(value ?? '').replaceAll('"', '""')}"`;
const lines = [['slug', 'english_title', 'chinese_name', 'review_state', 'pack_count', 'packs', 'modrinth_url']
  .map(quote).join(',')];
const rows = [...occurrences].map(([id, packs]) => ({ ...inventory.projects[id], packs }))
  .filter(row => row.slug).sort((a, b) => b.packs.length - a.packs.length || a.slug.localeCompare(b.slug));
for (const row of rows) {
  const state = curatedNames.has(row.slug) ? 'curated' : extensions[row.slug] ? 'extended' : 'unreviewed';
  const chinese = state === 'curated' ? curatedNames.get(row.slug)
    : state === 'extended' ? extensions[row.slug].name : '';
  lines.push([row.slug, row.title, chinese, state, row.packs.length, row.packs.join(';'), row.url]
    .map(quote).join(','));
}
fs.writeFileSync(new URL('./modpack_mod_name_audit.csv', import.meta.url), '\ufeff' + lines.join('\r\n') + '\r\n');
console.log(`Wrote ${rows.length} Mod rows; ${rows.filter(row => !curatedNames.has(row.slug) && !extensions[row.slug]).length} still unreviewed`);
