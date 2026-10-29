import launcher_app.core.favorites as favorites


def test_cf_bookmark_keeps_locator_not_api_metadata(tmp_path, monkeypatch):
    monkeypatch.setattr(favorites, '_path', lambda: str(tmp_path / 'favorites.json'))
    data = {}
    favorites.add_reference(data, favorites.DEFAULT_FOLDER, {
        'source': 'curseforge', 'slug': 'curseforge-123', 'curseforge_id': 123,
        'title': 'A shader', 'description': 'Not persisted', 'downloads': 100,
        'icon_url': 'https://example.com/icon.png', 'files': ['not persisted'],
    }, 'shader')
    favorites.save(data)
    loaded = favorites.load()
    record = loaded[favorites.DEFAULT_FOLDER]['curseforge-123']
    assert set(record) == {'name', 'versions', 'source', 'project_id', 'resource_type', 'url'}
    assert record['url'] == 'https://www.curseforge.com/projects/123'
    assert record['source'] == 'curseforge'
    assert favorites.copy(loaded, favorites.DEFAULT_FOLDER, 'Shaders', 'curseforge-123')
    assert loaded['Shaders']['curseforge-123'] == record
    loaded['Shaders']['curseforge-123']['versions'].append('file-id')
    assert record['versions'] == []


def test_legacy_favorites_keep_saved_versions(tmp_path, monkeypatch):
    import json
    path = tmp_path / 'favorites.json'
    path.write_text(json.dumps({favorites.DEFAULT_FOLDER: {'sodium': {'name': 'Sodium', 'version': 'old'}}}), encoding='utf-8')
    monkeypatch.setattr(favorites, '_path', lambda: str(path))
    data = favorites.load()
    assert data[favorites.DEFAULT_FOLDER]['sodium']['versions'] == ['old']
    favorites.add_reference(data, favorites.DEFAULT_FOLDER, {'slug': 'sodium', 'title': 'Sodium'}, 'mod')
    assert data[favorites.DEFAULT_FOLDER]['sodium']['versions'] == ['old']
