import pytest
from PySide6.QtCore import Qt

from launcher_app.ui.resource_center import ResourceBrowser

pytestmark = pytest.mark.ui


def test_refresh_retains_list_reports_failure_and_ignores_old_response(qtbot, monkeypatch):
    browser = ResourceBrowser('mod', 'Mod', 'mods', lambda *args: None, lambda *args: None)
    qtbot.addWidget(browser)
    hit = {'source': 'modrinth', 'slug': 'old', 'title': 'Existing resource'}
    browser._fill_results([hit])
    callbacks = []
    monkeypatch.setattr(browser, '_async', lambda key, work, done, **kwargs: callbacks.append(done))
    browser.do_search()
    assert browser.result_list.item(0).data(Qt.ItemDataRole.UserRole) == hit
    assert not browser.result_list.isEnabled()
    assert not browser.dl_btn.isEnabled()
    assert '正在更新' in browser.search_status.text()
    browser.do_search()
    result = {'hits': [], 'offsets': {}, 'exhausted': {}, 'errors': {}, 'no_more': True}
    callbacks[0](result)
    assert browser._search_pending
    callbacks[1](None)
    assert '更新失败' in browser.search_status.text()
    assert not browser.search_retry.isHidden()
    assert browser.result_list.item(0).data(Qt.ItemDataRole.UserRole) == hit
    browser.do_search()
    callbacks[2](result)
    assert browser.result_list.isEnabled()
    assert '没有匹配' in browser.search_status.text()
    assert browser.search_progress.isHidden()


def test_refresh_restores_selected_resource_when_still_compatible(qtbot, monkeypatch):
    browser = ResourceBrowser('mod', 'Mod', 'mods', lambda *args: None, lambda *args: None)
    qtbot.addWidget(browser)
    monkeypatch.setattr(browser, '_async', lambda *args, **kwargs: None)
    hit = {'source': 'modrinth', 'slug': 'same', 'title': 'Same resource'}
    browser._fill_results([hit])
    browser.result_list.setCurrentRow(0)
    callbacks = []
    monkeypatch.setattr(browser, '_async', lambda key, work, done, **kwargs: callbacks.append(done))
    browser.do_search()
    callbacks[0]({'hits': [hit], 'offsets': {}, 'exhausted': {}, 'errors': {}, 'no_more': True})
    assert browser._current == hit
    assert browser.result_list.currentRow() == 0
    assert '已更新' in browser.search_status.text()


@pytest.mark.parametrize('kind', ['mod', 'shader', 'resourcepack', 'datapack', 'modpack'])
def test_target_drives_only_version_sensitive_resource_filters(qtbot, monkeypatch, kind):
    from unittest.mock import Mock
    browser = ResourceBrowser(kind, kind, 'mods', lambda *args: None, lambda *args: None,
                              is_modpack=kind == 'modpack')
    qtbot.addWidget(browser)
    inst = {'id': 'fabric-target', 'base': '1.21.1', 'loader': 'fabric'}
    browser._target_getter = lambda: (inst, None)
    browser._search_params = ('existing',)
    search = Mock()
    monkeypatch.setattr(browser, 'do_search', search)
    browser._sync_target_ui()
    assert browser.selected_inst == inst
    if kind == 'mod':
        assert browser._current_gv() == '1.21.1'
        assert browser.loader_combo.currentData() == 'fabric'
        search.assert_called_once()
        browser._fill_versions([{'label': 'wrong', 'game_versions': ['1.20.1'], 'loaders': ['forge']}])
        assert browser.ver_combo.currentData() is None
        assert not browser.dl_btn.isEnabled()
    else:
        assert browser._current_gv() is None
        assert browser.loader_combo.currentData() is None
        search.assert_not_called()


@pytest.mark.parametrize('kind,folder', [('mod', 'mods'), ('modpack', 'downloads'),
                                       ('shader', 'shaderpacks'), ('datapack', 'datapacks'),
                                       ('resourcepack', 'resourcepacks')])
def test_all_categories_offer_platform_filter_without_changing_loaders(qtbot, kind, folder, monkeypatch):
    browser = ResourceBrowser(kind, kind, folder, lambda *args: None, lambda *args: None,
                              is_modpack=kind == 'modpack')
    qtbot.addWidget(browser)
    assert [browser.source_combo.itemData(i) for i in range(browser.source_combo.count())] == ['all', 'modrinth', 'curseforge']
    loader_values = [browser.loader_combo.itemData(i) for i in range(browser.loader_combo.count())]
    assert 'fabric' in loader_values and 'forge' in loader_values
    assert 'curseforge' not in loader_values
    browser.source_combo.setCurrentIndex(2)
    assert browser.loader_combo.isEnabled() == (kind in ('mod', 'modpack'))


def test_merged_results_keep_file_source_and_platform_pagination(qtbot):
    browser = ResourceBrowser('shader', 'shader', 'shaderpacks', lambda *args: None, lambda *args: None)
    qtbot.addWidget(browser)
    def hit(platform):
        return {'source': platform, 'slug': platform, 'title': platform, 'description': ''}
    browser._apply_search_page({'hits': [hit('modrinth'), hit('curseforge')],
        'offsets': {'modrinth': 30, 'curseforge': 2},
        'exhausted': {'modrinth': False, 'curseforge': True}, 'errors': {}, 'no_more': False})
    assert not browser._no_more
    assert browser._source_offsets == {'modrinth': 30, 'curseforge': 2}
    assert [browser.result_list.item(i).data(Qt.ItemDataRole.UserRole)['source'] for i in range(2)] == ['modrinth', 'curseforge']


def test_search_filters_use_exact_versions_and_reach_search_api(qtbot, monkeypatch):
    from unittest.mock import Mock
    browser = ResourceBrowser('mod', 'Mod', 'mods', lambda *args: None, lambda *args: None)
    qtbot.addWidget(browser)
    browser.populate_game_versions({'versions': [
        {'id': '1.21.1', 'type': 'release'}, {'id': '1.20.1', 'type': 'release'}]})
    assert [browser.gv_combo.itemData(i) for i in range(browser.gv_combo.count())] == ['', '1.21.1', '1.20.1']
    assert not any('推荐' in browser.gv_combo.itemText(i) for i in range(browser.gv_combo.count()))
    browser.gv_combo.select_version('1.20.1')
    browser.loader_combo.setCurrentIndex(browser.loader_combo.findData('forge'))
    response = {'hits': [], 'offsets': {}, 'exhausted': {}, 'errors': {}, 'no_more': True}
    fetch = Mock(return_value=response)
    monkeypatch.setattr('launcher_app.resources.resource_catalog.search_page', fetch)
    monkeypatch.setattr(browser, '_async', lambda key, work, done, **kwargs: done(work()))
    browser.do_search()
    assert fetch.call_args.kwargs['game_version'] == '1.20.1'
    assert fetch.call_args.kwargs['loader'] == 'forge'
    assert browser.gv_combo.parentWidget() is not browser.download_section
    assert browser.ver_combo.parentWidget() is browser.download_section


def test_selected_file_download_and_star_are_in_detail(qtbot, monkeypatch, tmp_path):
    received = []
    browser = ResourceBrowser('shader', 'Shader', 'shaderpacks', lambda *args: received.append(args), lambda *args: None)
    qtbot.addWidget(browser)
    file = {'file_id': 20, 'label': 'Actual shader file', 'filename': 'shader.zip', 'game_versions': ['1.20.1']}
    def complete(key, work, done, **kwargs):
        if key[0] == 'ver': done([file])
        elif key[0] == 'compat-range': done({'versions': []})
    monkeypatch.setattr(browser, '_async', complete)
    browser.custom_dir = str(tmp_path)
    browser._fill_results([{'source': 'curseforge', 'curseforge_id': 10, 'slug': 'curseforge-10', 'title': 'Shader', 'description': ''}])
    browser.result_list.setCurrentRow(0)
    assert not browser.download_section.isHidden()
    assert browser.fav_btn.text() in ('☆', '★')
    assert browser.fav_btn.parentWidget() is browser.download_section
    assert browser.dl_btn.parentWidget() is browser.download_section
    assert browser.ver_combo.currentData() == file
    browser._download()
    assert received[0][1] == file
    assert received[0][3] == str(tmp_path)


def test_target_selection_keeps_search_filters(qtbot, monkeypatch):
    browser = ResourceBrowser('mod', 'Mod', 'mods', lambda *args: None, lambda *args: None)
    qtbot.addWidget(browser)
    browser.populate_game_versions({'versions': [{'id': '1.20.1', 'type': 'release'}]})
    browser.gv_combo.select_version('1.20.1')
    browser.loader_combo.setCurrentIndex(browser.loader_combo.findData('forge'))
    monkeypatch.setattr(browser, '_target_setter', lambda *args: None)
    browser._select_inst({'id': 'another-instance', 'base': '1.21.1', 'loader': 'fabric'})
    assert browser.gv_combo.current_version() == '1.20.1'
    assert browser.loader_combo.currentData() == 'forge'


def test_detail_filters_match_declared_loader_and_mc(qtbot):
    browser = ResourceBrowser('mod', 'Mod', 'mods', lambda *args: None, lambda *args: None)
    qtbot.addWidget(browser)
    records = [
        {'label': 'Fabric new', 'id': 'a', 'loaders': ['fabric'], 'game_versions': ['1.21.1']},
        {'label': 'Forge old', 'id': 'b', 'loaders': ['forge'], 'game_versions': ['1.20.1']},
        {'label': 'Fabric old', 'id': 'c', 'loaders': ['fabric'], 'game_versions': ['1.20.1', '1.20.2']},
    ]
    browser._fill_versions(records)
    browser.file_loader_filter.setCurrentIndex(browser.file_loader_filter.findData('fabric'))
    browser.file_mc_filter.setCurrentIndex(browser.file_mc_filter.findData('1.20.1'))
    assert browser.ver_combo.count() == 1
    assert browser.ver_combo.currentData() == records[2]
    browser.file_mc_filter.setCurrentIndex(browser.file_mc_filter.findData('1.21.1'))
    assert browser.ver_combo.currentData() == records[0]
    assert browser.gv_combo.current_version() == ''
    assert browser.loader_combo.currentData() is None


def test_many_versions_scroll_in_bounded_popup(qtbot):
    browser = ResourceBrowser('mod', 'Mod', 'mods', lambda *args: None, lambda *args: None)
    qtbot.addWidget(browser)
    browser.resize(1000, 700)
    browser.download_section.show()
    browser._fill_versions([{'label': f'File {i}', 'id': str(i), 'loaders': ['forge'],
                             'game_versions': ['1.20.1']} for i in range(80)])
    browser.show()
    browser.ver_combo.showPopup()
    view = browser.ver_combo.view()
    qtbot.waitUntil(view.isVisible)
    assert browser.ver_combo.count() == 80
    assert browser.ver_combo.maxVisibleItems() == 8
    assert view.height() <= view.maximumHeight()
    assert view.height() < 300
    assert view.verticalScrollBar().maximum() > 0
    browser.ver_combo.hidePopup()


def test_missing_compatibility_tags_are_not_inferred(qtbot):
    browser = ResourceBrowser('shader', 'Shader', 'shaderpacks', lambda *args: None, lambda *args: None)
    qtbot.addWidget(browser)
    browser._fill_versions([{'label': 'Untagged', 'id': 'unknown'},
        {'label': 'Tagged', 'id': 'known', 'game_versions': ['1.20.1']}])
    assert browser.ver_combo.count() == 2
    assert not browser.file_loader_filter.isEnabled()
    browser.file_mc_filter.setCurrentIndex(browser.file_mc_filter.findData('1.20.1'))
    assert browser.ver_combo.count() == 1
    assert browser.ver_combo.currentData()['id'] == 'known'


def test_long_description_scrolls_without_moving_download_section(qtbot):
    from PySide6.QtCore import QPoint
    browser = ResourceBrowser('mod', 'Mod', 'mods', lambda *args: None, lambda *args: None)
    qtbot.addWidget(browser)
    browser.resize(1050, 740)
    browser.desc_label.setText('A long resource description with instructions.\n' * 150)
    browser.desc_label.show()
    browser.download_section.show()
    browser.show()
    scrollbar = browser.detail_scroll.verticalScrollBar()
    qtbot.waitUntil(lambda: scrollbar.maximum() > 0)
    position = browser.dl_btn.mapTo(browser, QPoint(0, 0))
    assert browser.detail_column.rect().contains(browser.download_section.geometry())
    assert browser.dl_btn.isVisible()
    scrollbar.setValue(scrollbar.maximum())
    assert browser.dl_btn.mapTo(browser, QPoint(0, 0)) == position
    assert browser.detail_column.rect().contains(browser.download_section.geometry())
    assert browser.download_section.parentWidget() is browser.detail_column
    assert browser.detail_scroll.widget() is browser.panel


def test_cf_bookmark_hydrates_and_downloads_using_actual_resource_type(qtbot, monkeypatch):
    from launcher_app.ui.resource_center import FavoriteBrowser
    from unittest.mock import Mock
    browser = FavoriteBrowser('mod', '收藏', 'mods', lambda *args: None, lambda *args: None)
    qtbot.addWidget(browser)
    project = {'source': 'curseforge', 'curseforge_id': 123, 'slug': 'curseforge-123',
               'title': 'Fresh title', 'description': 'Fresh description', 'project_type': 'shader'}
    lookup = Mock(return_value=project)
    monkeypatch.setattr('launcher_app.resources.curseforge.get_mod', lookup)
    def complete(key, work, done, **kwargs):
        if key[0] == 'favorite-project': done(work())
        elif key[0] == 'ver': done([{'file_id': 456, 'label': 'Real file'}])
    monkeypatch.setattr(browser, '_async', complete)
    browser._fill_results([{'slug': 'curseforge-123', 'source': 'curseforge', 'title': 'Saved label',
                            '_favorite_ref': {'source': 'curseforge', 'project_id': '123'}}])
    browser.result_list.setCurrentRow(0)
    lookup.assert_called_once_with(123)
    assert browser.title_label.text() == 'Fresh title'
    assert browser.project_type == 'shader' and browser.sub_dir == 'shaderpacks'
    assert browser.ver_combo.currentData()['file_id'] == 456
    assert browser.fav_btn.isEnabled()


def test_failed_bookmark_lookup_preserves_reference(qtbot, monkeypatch):
    from launcher_app.ui.resource_center import FavoriteBrowser
    browser = FavoriteBrowser('mod', '收藏', 'mods', lambda *args: None, lambda *args: None)
    qtbot.addWidget(browser)
    monkeypatch.setattr(browser, '_async', lambda key, work, done, **kwargs: done(None))
    bookmark = {'slug': 'curseforge-123', 'source': 'curseforge', 'title': 'Saved label',
                '_favorite_ref': {'source': 'curseforge', 'project_id': '123'}}
    browser._fill_results([bookmark])
    browser.result_list.setCurrentRow(0)
    assert browser.result_list.count() == 1
    assert browser.result_list.item(0).data(Qt.ItemDataRole.UserRole) == bookmark
    assert browser.download_section.isHidden()
    assert '收藏标记仍保留' in browser.empty_label.text()


def test_cf_star_saves_reference_and_toggles(qtbot, monkeypatch, tmp_path):
    import launcher_app.core.favorites as favorites
    monkeypatch.setattr(favorites, '_path', lambda: str(tmp_path / 'favorites.json'))
    browser = ResourceBrowser('mod', 'Mod', 'mods', lambda *args: None, lambda *args: None)
    qtbot.addWidget(browser)
    browser._current = {'source': 'curseforge', 'slug': 'curseforge-123', 'curseforge_id': 123, 'title': 'Test'}
    browser._fav_current()
    assert favorites.is_favorited(favorites.load(), favorites.DEFAULT_FOLDER, 'curseforge-123')
    assert browser.fav_btn.text() == '★'
    browser._fav_current()
    assert not favorites.is_favorited(favorites.load(), favorites.DEFAULT_FOLDER, 'curseforge-123')
    assert browser.fav_btn.text() == '☆'


def test_favorite_page_has_project_list_and_shared_download_hooks(qtbot, monkeypatch, tmp_path):
    from launcher_app.ui.resource_center import ResourceCenter
    import launcher_app.core.favorites as favorites
    monkeypatch.setattr(favorites, '_path', lambda: str(tmp_path / 'favorites.json'))
    center = ResourceCenter(auto_load_versions=False)
    qtbot.addWidget(center)
    assert center.favorite_browser.split.count() == 2
    assert center.favorite_browser.detail_scroll.widget() is center.favorite_browser.panel
    assert center._fav_folder_combo.count() == 1
    center.set_hooks(lambda iid: str(tmp_path / iid), lambda *args: None, lambda *args: None)
    center.refresh_browser_instances([])
    center._set_shared_target(None, str(tmp_path))
    assert center.favorite_browser.custom_dir == str(tmp_path)


def test_resource_links_show_source_and_explicit_cross_platform_search(qtbot):
    browser = ResourceBrowser('mod', 'Mod', 'mods', lambda *args: None, lambda *args: None)
    qtbot.addWidget(browser)
    html = browser._resource_links({'source':'curseforge','curseforge_id':10}, 'A & B')
    assert '>MC百科</a>' in html
    assert '>CurseForge</a>' in html
    assert '>Modrinth 搜索</a>' in html
    assert 'A%20%26%20B' in html
    assert '在 MC百科' not in html
    html = browser._resource_links({'source':'modrinth','slug':'sodium'}, 'Sodium')
    assert 'https://modrinth.com/project/sodium' in html
    assert '>CurseForge 搜索</a>' in html


def test_favorites_load_on_open_restore_icons_and_filter_by_actual_type(qtbot, monkeypatch, tmp_path):
    from launcher_app.ui.resource_center import ResourceCenter, FavoriteBrowser
    import launcher_app.core.favorites as favorites
    from unittest.mock import Mock
    monkeypatch.setattr(favorites, '_path', lambda: str(tmp_path / 'favorites.json'))
    favorites.save({favorites.DEFAULT_FOLDER: {
        'sodium': {'name': 'Sodium', 'versions': []},
        'curseforge-123': {'name': 'A shader', 'source': 'curseforge', 'project_id': '123', 'versions': []}}})
    def resolve(bookmark):
        cf = bookmark['source'] == 'curseforge'
        return dict(bookmark, title='Fresh title', icon_url='https://example.com/icon.png',
                    project_type='shader' if cf else 'mod', _favorite_loaded=True)
    lookup = Mock(side_effect=resolve)
    monkeypatch.setattr(FavoriteBrowser, 'resolve_bookmark', staticmethod(lookup))
    def complete(self, key, work, done, **kwargs):
        if key[0] == 'favorite-list':
            done(work())
    monkeypatch.setattr(FavoriteBrowser, '_async', complete)
    center = ResourceCenter(auto_load_versions=False)
    qtbot.addWidget(center)
    assert lookup.call_count == 0
    center.switch_to(7)
    assert lookup.call_count == 2
    browser = center.favorite_browser
    assert browser.result_list.count() == 2
    for row in range(2):
        hit = browser.result_list.item(row).data(Qt.ItemDataRole.UserRole)
        assert hit['icon_url'] == 'https://example.com/icon.png'
        assert hit['_favorite_loaded']
    jobs = []
    monkeypatch.setattr(browser, '_async', lambda key, work, done, **kwargs: jobs.append((key, kwargs)))
    monkeypatch.setattr(browser, '_visible_rows', lambda: [0, 1])
    browser._enqueue_visible_icons()
    assert len(jobs) == 2
    assert all(key[0] == '__icon__' for key, kwargs in jobs)
    assert all(kwargs['cache'] is False for key, kwargs in jobs)
    center._fav_type_combo.setCurrentIndex(center._fav_type_combo.findData('shader'))
    assert browser.result_list.count() == 1
    assert browser.result_list.item(0).data(Qt.ItemDataRole.UserRole)['project_type'] == 'shader'
    assert lookup.call_count == 2
    assert 'icon_url' not in favorites.load()[favorites.DEFAULT_FOLDER]['curseforge-123']
