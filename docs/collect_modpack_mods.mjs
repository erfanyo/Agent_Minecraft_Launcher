// Refresh the factual Modrinth pack inventory; translation review is separate.
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { execFileSync } from 'node:child_process';

const root = 'https://api.modrinth.com/v2';
const categories = ['optimization', 'technology', 'magic', 'adventure', 'combat', 'decoration', 'kitchen-sink'];
const headers = { 'User-Agent': 'AMCL/0.0.1 (mod-name research)' };
async function json(url) {
  const response = await fetch(url, { headers });
  if (!response.ok) throw new Error(`${response.status} ${url}`);
  return response.json();
}
const packs = new Map();
for (const category of categories) {
  const facets = JSON.stringify([['project_type:modpack'], [`categories:${category}`]]);
  const result = await json(`${root}/search?${new URLSearchParams({ facets, index: 'downloads', limit: '3' })}`);
  for (const hit of result.hits) {
    const existing = packs.get(hit.project_id);
    if (existing) existing.directions.push(category);
    else packs.set(hit.project_id, { id: hit.project_id, slug: hit.slug, title: hit.title,
      downloads: hit.downloads, directions: [category] });
  }
}
const temp = fs.mkdtempSync(path.join(os.tmpdir(), 'amcl-modpack-'));
const projectPacks = [];
const ids = new Set();
try {
  for (const pack of packs.values()) {
    try {
      const versions = await json(`${root}/project/${pack.id}/version`);
      const version = versions.find(v => v.version_type === 'release' && v.files?.some(f => f.filename.endsWith('.mrpack')))
        ?? versions.find(v => v.files?.some(f => f.filename.endsWith('.mrpack')));
      const file = version?.files?.find(f => f.filename.endsWith('.mrpack'));
      if (!file) continue;
      const response = await fetch(file.url, { headers });
      if (!response.ok) throw new Error(`archive ${response.status}`);
      const archive = path.join(temp, `${pack.id}.mrpack`);
      fs.writeFileSync(archive, Buffer.from(await response.arrayBuffer()));
      const index = JSON.parse(execFileSync('tar', ['-xOf', archive, 'modrinth.index.json'],
        { maxBuffer: 32 * 1024 * 1024 }).toString('utf8'));
      const modIds = [...new Set((index.files ?? []).filter(f => f.path?.startsWith('mods/'))
        .flatMap(f => (f.downloads ?? []).map(url => /\/data\/([^/]+)\/versions\//.exec(url)?.[1])
          .filter(Boolean)))];
      modIds.forEach(id => ids.add(id));
      projectPacks.push({ ...pack, version_id: version.id, version_number: version.version_number,
        mc_versions: version.game_versions, mod_project_ids: modIds,
        mod_file_count: (index.files ?? []).filter(f => f.path?.startsWith('mods/')).length });
      console.log(`${pack.slug}: ${modIds.length} identified mods`);
    } catch (error) { console.error(`${pack.slug}: ${error.message}`); }
  }
} finally { fs.rmSync(temp, { recursive: true, force: true }); }
const projects = {};
const allIds = [...ids];
for (let i = 0; i < allIds.length; i += 100) {
  const batch = allIds.slice(i, i + 100);
  for (const item of await json(`${root}/projects?ids=${encodeURIComponent(JSON.stringify(batch))}`)) {
    projects[item.id] = { slug: item.slug, title: item.title, url: `https://modrinth.com/mod/${item.slug}` };
  }
}
const inventory = { collected_at: new Date().toISOString(), source: 'Modrinth v2 search/project/version and .mrpack index',
  directions: categories, packs: projectPacks, projects };
fs.writeFileSync(new URL('./modpack_mod_inventory.json', import.meta.url), JSON.stringify(inventory, null, 2) + '\n');
console.log(`Saved ${projectPacks.length} packs and ${Object.keys(projects).length} unique mods`);
