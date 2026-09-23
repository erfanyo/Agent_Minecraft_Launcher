# -*- coding: utf-8 -*-
"""服务端日志诊断单测:证据解析、证据→文件匹配、建议分级与表格输出。

全部用纯函数,不读写真实服务端目录。
"""
import unittest

from server_log_diagnosis import (build_diagnosis, match_evidence_to_files,
                                  parse_log_evidence, strip_mod_id,
                                  suggestions_to_markdown)


# 贴近真实崩溃报告的样例(取自 lootbeams 的 NoClassDefFoundError 现场)。
CRASH_LOG = """---- Minecraft Crash Report ----
Description: Mod loading error has occurred

-- MOD lootbeams --
Details:
	Caused by 0: java.lang.NoClassDefFoundError: net/minecraft/client/renderer/RenderStateShard
	Mod File: /srv/mods/[战利品光束] lootbeams-1.20.1-1.2.6.jar
	Failure message: LootBeams (lootbeams) has failed to load correctly
		java.lang.NoClassDefFoundError: net/minecraft/client/renderer/RenderStateShard

-- MOD oculus --
	Caused by 0: java.lang.NoClassDefFoundError: net/irisshaders/iris/IrisApi
"""

# KubeJS 运行期错误(不属于 Mod 加载失败,不该被当成停用建议)。
# 注意:下面的 ``counter.js#501`` 是 KubeJS 日志的真实格式(文件#行号),必须原样保留;
# 它会被色值扫描器误认成 3 位 hex,故已在 ui_color_scan 登记为已知误报。
KUBEJS_LOG = """[18:17:39] [ERROR] ! business/counter.js#501: Error in 'BlockEvents.rightClicked':
TypeError: Cannot find function getIngredients in object com.github.ysbbbbbb.kaleidoscopetavern.blockentity.mixology.SignatureCocktailBlockEntity@42b69a24.
"""


def _mod(file, mod_id="", environment="unknown", disabled=False, description=""):
    return {"file": file, "modId": mod_id, "name": file,
            "environment": environment, "disabled": disabled,
            "description": description, "path": "/srv/mods/" + file}


class ParseEvidenceTests(unittest.TestCase):
    def test_extracts_mod_and_class_error(self):
        ev = parse_log_evidence(CRASH_LOG)
        self.assertIn("lootbeams", ev["mods"])
        self.assertTrue(ev["mods"]["lootbeams"]["errors"])
        self.assertIn("oculus", ev["mods"])

    def test_detects_client_only_trace(self):
        self.assertTrue(parse_log_evidence(CRASH_LOG)["clientOnly"])

    def test_runtime_script_error_is_not_mod_evidence(self):
        """KubeJS 脚本报错不该被误判成某个 Mod 需要停用。"""
        ev = parse_log_evidence(KUBEJS_LOG)
        self.assertEqual(ev["mods"], {})

    def test_empty_log(self):
        self.assertEqual(parse_log_evidence("")["mods"], {})

    def test_framework_phrases_are_not_treated_as_mods(self):
        """「Mod Loading has failed」是加载器自己那句话,不是某个 Mod 的名字。"""
        log = ("java.lang.Exception: Mod Loading has failed\n"
               "-- MOD Loading --\n"
               "Failure message: LootBeams (lootbeams) has failed to load correctly\n")
        ev = parse_log_evidence(log)
        self.assertNotIn("Loading", ev["mods"])
        self.assertIn("lootbeams", ev["mods"])

    def test_failure_message_prefers_bracketed_mod_id(self):
        """``Xxx (modid) has failed`` 要取括号里的 modId,而不是整个显示名。"""
        ev = parse_log_evidence(
            "Failure message: LootBeams (lootbeams) has failed to load correctly\n")
        self.assertIn("lootbeams", ev["mods"])
        self.assertNotIn("LootBeams (lootbeams)", ev["mods"])

    def test_strip_mod_id_removes_chinese_prefix(self):
        self.assertEqual(strip_mod_id("[FTB任务] ftb-quests-2001.jar"),
                         "ftb-quests-2001.jar")
        self.assertEqual(strip_mod_id("plain-id"), "plain-id")


class MatchEvidenceTests(unittest.TestCase):
    def test_matches_by_mod_id(self):
        mods = [_mod("[战利品光束] lootbeams-1.20.1-1.2.6.jar", "lootbeams")]
        matched = match_evidence_to_files(parse_log_evidence(CRASH_LOG), mods)
        self.assertIn("[战利品光束] lootbeams-1.20.1-1.2.6.jar", matched)

    def test_matches_by_filename_when_id_missing(self):
        mods = [_mod("lootbeams-1.20.1-1.2.6.jar", "")]
        matched = match_evidence_to_files(parse_log_evidence(CRASH_LOG), mods)
        self.assertIn("lootbeams-1.20.1-1.2.6.jar", matched)


class BuildDiagnosisTests(unittest.TestCase):
    def test_unique_mixin_handler_identifies_etf_without_mod_error_section(self):
        mods = [_mod('entity_texture_features.jar', 'entity_texture_features'),
                _mod('other.jar', 'other')]
        mods[0]['mixinConfigs'] = ['entity_texture_features.mixins.json']
        log = ('Attempted to load class net/minecraft/client/gui/screens/Screen '
               'for invalid dist DEDICATED_SERVER\n'
               'at net.minecraft.resources.ResourceLocation.'
               'handler$zkc000$etf$illegalPathOverride')
        result = build_diagnosis(mods, log)
        self.assertEqual([row['file'] for row in result['suggestions']],
                         ['entity_texture_features.jar'])
        self.assertEqual(result['suggestions'][0]['level'], 'medium')

    def test_mixin_handler_needs_unique_jar_config_evidence(self):
        mods = [_mod('entity_texture_features.jar', 'entity_texture_features')]
        log = ('Attempted to load class net/minecraft/client/gui/screens/Screen '
               'for invalid dist DEDICATED_SERVER\n'
               'at ResourceLocation.handler$zkc000$etf$illegalPathOverride')
        self.assertEqual(build_diagnosis(mods, log)['suggestions'], [])

    def test_high_level_from_log_evidence(self):
        mods = [_mod("[战利品光束] lootbeams-1.20.1-1.2.6.jar", "lootbeams"),
                _mod("keep.jar", "keep")]
        result = build_diagnosis(mods, CRASH_LOG)
        levels = {row["file"]: row["level"] for row in result["suggestions"]}
        self.assertEqual(levels["[战利品光束] lootbeams-1.20.1-1.2.6.jar"], "high")
        self.assertNotIn("keep.jar", levels)

    def test_medium_level_for_client_environment(self):
        mods = [_mod("appleskin.jar", "appleskin", environment="client")]
        result = build_diagnosis(mods, "")
        self.assertEqual(result["suggestions"][0]["level"], "medium")

    def test_already_disabled_is_not_suggested(self):
        mods = [_mod("lootbeams.jar.disabled", "lootbeams", disabled=True)]
        self.assertEqual(build_diagnosis(mods, CRASH_LOG)["suggestions"], [])

    def test_high_sorts_before_medium(self):
        mods = [_mod("client.jar", "clientmod", environment="client"),
                _mod("[战利品光束] lootbeams-1.20.1-1.2.6.jar", "lootbeams")]
        result = build_diagnosis(mods, CRASH_LOG)
        self.assertEqual(result["suggestions"][0]["level"], "high")

    def test_client_only_reason_is_specific(self):
        mods = [_mod("[战利品光束] lootbeams-1.20.1-1.2.6.jar", "lootbeams")]
        result = build_diagnosis(mods, CRASH_LOG)
        self.assertIn("客户端类", result["suggestions"][0]["reason"])

    def test_no_evidence_yields_note(self):
        result = build_diagnosis([_mod("keep.jar", "keep")], "")
        self.assertEqual(result["suggestions"], [])
        self.assertTrue(result["notes"])

    def test_missing_log_is_noted(self):
        result = build_diagnosis([_mod("client.jar", "c", environment="client")], "")
        self.assertTrue(any("未提供日志" in n for n in result["notes"]))


class MarkdownOutputTests(unittest.TestCase):
    def test_renders_two_column_table(self):
        mods = [_mod("[战利品光束] lootbeams-1.20.1-1.2.6.jar", "lootbeams",
                     description="掉落的战利品光束")]
        out = suggestions_to_markdown(build_diagnosis(mods, CRASH_LOG))
        self.assertIn("| Mod | 说明 |", out)
        self.assertIn("| --- | --- |", out)
        self.assertIn("lootbeams-1.20.1-1.2.6.jar", out)
        self.assertIn("掉落的战利品光束", out)
        self.assertIn("确定", out)

    def test_empty_result_has_no_table(self):
        out = suggestions_to_markdown({"suggestions": [], "notes": []})
        self.assertNotIn("|", out)
        self.assertIn("没有发现", out)

    def test_limit_truncates_with_note(self):
        mods = [_mod(f"m{i}.jar", f"id{i}", environment="client") for i in range(5)]
        out = suggestions_to_markdown(build_diagnosis(mods, ""), limit=2)
        self.assertIn("另有 3 项未列出", out)

    def test_output_is_parseable_by_render_layer(self):
        """产出的表格必须能被 chat_view 的 Markdown 表格识别器认出来。"""
        from chat_view import parse_markdown_tables
        mods = [_mod("client.jar", "c", environment="client")]
        out = suggestions_to_markdown(build_diagnosis(mods, ""))
        tables = parse_markdown_tables(out)
        self.assertEqual(len(tables), 1)
        self.assertEqual(tables[0][1], ["Mod", "说明"])
        self.assertTrue(tables[0][2])


if __name__ == '__main__':
    unittest.main()
