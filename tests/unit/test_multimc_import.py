import json
import zipfile

import pytest

from launcher_app.resources.modpack import detect_modpack_format
from launcher_app.resources.multimc_import import read_profile


def test_multimc_patches_preserve_java_jvm_tweakers_and_local_classpath(tmp_path):
    path = tmp_path / 'pack.zip'
    with zipfile.ZipFile(path, 'w') as archive:
        archive.writestr('Pack/mmc-pack.json', json.dumps({'components': [
            {'uid': 'net.minecraft'}, {'uid': 'custom'}]}))
        archive.writestr('Pack/patches/net.minecraft.json', json.dumps({
            'uid': 'net.minecraft', 'version': '1.7.10', 'order': -2,
            'compatibleJavaMajors': [17, 21, 25], 'mainClass': 'Vanilla',
            'minecraftArguments': '--username ${auth_player_name}',
            'mainJar': {'downloads': {'artifact': {'url': 'https://example.org/client.jar'}}},
            'libraries': [{'name': 'example:library:1', 'downloads': {'artifact': {'url': 'https://example.org/lib.jar'}}}]}))
        archive.writestr('Pack/patches/custom.json', json.dumps({
            'uid': 'custom', 'order': 3, 'mainClass': 'Bootstrap',
            '+tweakers': ['ForgeTweaker'], '+jvmArgs': ['--add-opens', 'java.base/java.lang=ALL-UNNAMED'],
            'libraries': [{'name': 'example:patch:2:custom', 'MMC-hint': 'local'}]}))
        archive.writestr('Pack/libraries/patch-2-custom.jar', b'jar')
        archive.writestr('Pack/.minecraft/mods/mod.jar', b'mod')
    assert detect_modpack_format(str(path)) == 'multimc'
    with zipfile.ZipFile(path) as archive:
        prefix, name, mc, profile, local = read_profile(archive)
    assert prefix == 'Pack/' and mc == '1.7.10'
    assert profile['javaVersion']['majorVersion'] == 17
    assert profile['mainClass'] == 'Bootstrap'
    assert profile['arguments']['game'][-2:] == ['--tweakClass', 'ForgeTweaker']
    assert profile['arguments']['jvm'] == ['--add-opens', 'java.base/java.lang=ALL-UNNAMED']
    assert local == [('Pack/libraries/patch-2-custom.jar', 'example/patch/2/patch-2-custom.jar')]


def test_missing_component_is_not_silently_imported_as_vanilla(tmp_path):
    path = tmp_path / 'pack.zip'
    with zipfile.ZipFile(path, 'w') as archive:
        archive.writestr('mmc-pack.json', json.dumps({'components': [{'uid': 'custom'}]}))
    with zipfile.ZipFile(path) as archive, pytest.raises(ValueError, match='缺少导出的补丁'):
        read_profile(archive)


def test_identical_case_collisions_are_opt_in_and_content_checked(tmp_path):
    from launcher_app.resources.archive_inspection import inspect_archive
    path = tmp_path / 'pack.zip'
    with zipfile.ZipFile(path, 'w') as archive:
        archive.writestr('config/Mod/lang.lang', b'same')
        archive.writestr('config/mod/lang.lang', b'same')
    with pytest.raises(ValueError, match='case-colliding'):
        inspect_archive(path)
    assert inspect_archive(path, allow_identical_case_duplicates=True)['fileCount'] == 2
    with zipfile.ZipFile(path, 'w') as archive:
        archive.writestr('config/Mod/lang.lang', b'first')
        archive.writestr('config/mod/lang.lang', b'second')
    with pytest.raises(ValueError, match='different content'):
        inspect_archive(path, allow_identical_case_duplicates=True)
