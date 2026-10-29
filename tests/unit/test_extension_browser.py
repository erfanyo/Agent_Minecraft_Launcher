from launcher_app.browser import browser_setup


def install(root, vendor, browser, binary, profile='Default'):
    (root / 'local' / vendor / browser / 'User Data' / profile / 'Extensions' /
     'mmlmfjhmonkocbjadbfplnigmagldckm').mkdir(parents=True)
    executable = root / 'programs' / vendor / browser / 'Application' / binary
    executable.parent.mkdir(parents=True)
    executable.write_bytes(b'placeholder, never executed')
    return str(executable)


def environment(tmp_path, monkeypatch):
    monkeypatch.setattr(browser_setup.sys, 'platform', 'win32')
    monkeypatch.setenv('LOCALAPPDATA', str(tmp_path / 'local'))
    monkeypatch.setenv('ProgramFiles', str(tmp_path / 'programs'))
    monkeypatch.delenv('ProgramFiles(x86)', raising=False)


def test_selects_edge_when_extension_only_installed_in_edge(tmp_path, monkeypatch):
    environment(tmp_path, monkeypatch)
    expected = install(tmp_path, 'Microsoft', 'Edge', 'msedge.exe')
    assert browser_setup.find_extension_browser() == expected


def test_multiple_browser_installations_do_not_silently_choose_profile(tmp_path, monkeypatch):
    environment(tmp_path, monkeypatch)
    install(tmp_path, 'Microsoft', 'Edge', 'msedge.exe')
    install(tmp_path, 'Google', 'Chrome', 'chrome.exe', 'Profile 2')
    assert browser_setup.find_extension_browser() is None


def test_missing_extension_does_not_select_an_arbitrary_executable(tmp_path, monkeypatch):
    environment(tmp_path, monkeypatch)
    assert browser_setup.find_extension_browser() is None
