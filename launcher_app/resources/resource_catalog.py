"""Search independent resource platforms with independent pagination cursors."""
from concurrent.futures import ThreadPoolExecutor
from launcher_app.core.task_context import submit


def search_page(source, project_type, query, order, tags='', offsets=None, exhausted=None, limit=30,
                game_version=None, loader=None):
    import launcher_app.resources.curseforge as curseforge
    import launcher_app.resources.modrinth as modrinth
    offsets = dict(offsets or {})
    exhausted = dict(exhausted or {})
    sources = ['modrinth', 'curseforge'] if source == 'all' else [source]
    errors, pages = {}, {}
    if 'curseforge' in sources and not exhausted.get('curseforge') and not curseforge.configured():
        errors['curseforge'] = 'CurseForge 尚未配置 API Key，请到设置中填写。'
        exhausted['curseforge'] = True
    def fetch(platform):
        offset = offsets.get(platform, 0)
        if platform == 'curseforge':
            return curseforge.search_mods(query, game_version, order, offset=offset,
                                         limit=limit, project_type=project_type, loader=loader)
        hits = modrinth.search_mods_cn(query, game_version, loader, limit=limit,
                                      project_type=project_type, order_by=order,
                                      tags=tags, offset=offset)
        return [dict(hit, source='modrinth') for hit in hits]
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = {platform: submit(pool, fetch, platform) for platform in sources
                   if not exhausted.get(platform)}
        for platform, future in futures.items():
            try:
                hits = future.result()
                pages[platform] = hits
                offsets[platform] = offsets.get(platform, 0) + len(hits)
                exhausted[platform] = len(hits) < limit
            except Exception as error:
                errors[platform] = f'{type(error).__name__}: {error}'
                exhausted[platform] = True
    # Alternate sources for relevance/updated; each retains its own ranking.
    hits = []
    for index in range(max((len(page) for page in pages.values()), default=0)):
        for platform in sources:
            page = pages.get(platform, [])
            if index < len(page):
                hits.append(page[index])
    if order == 'downloads':
        hits.sort(key=lambda hit: hit.get('downloads') or 0, reverse=True)
    return {'hits': hits, 'offsets': offsets, 'exhausted': exhausted,
            'errors': errors, 'no_more': all(exhausted.get(platform, False) for platform in sources)}
