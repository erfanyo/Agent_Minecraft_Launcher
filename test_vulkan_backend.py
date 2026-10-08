# -*- coding: utf-8 -*-
"""Vulkan 推理后端的防退化测试(P1#5)。

背景:llama.cpp CPU 与 Vulkan 是不同的 llama-server 二进制(分目录共存)。
Vulkan 需官方资产(win-x64/linux-x64/linux-arm64),SHA256 强校验。
本测试固化资产命名、回退规则、GPU flag、目录隔离,防止后续改动脱节。
"""
import os
import sys
import unittest
import platform


class VulkanBackendTests(unittest.TestCase):
    def test_resolve_falls_back_to_cpu_without_vulkan_binary(self):
        import local_ai
        # 环境里没下载 Vulkan 二进制时,auto/vulkan 都必须安全回退 cpu
        exe, backend = local_ai.resolve_server_exe("auto")
        self.assertIn(backend, ("cpu", "vulkan"))
        if backend == "cpu":
            self.assertEqual(exe, local_ai.SERVER_EXE)
        # 显式 cpu 永远是 CPU
        exe2, backend2 = local_ai.resolve_server_exe("cpu")
        self.assertEqual(backend2, "cpu")
        self.assertEqual(exe2, local_ai.SERVER_EXE)

    def test_gpu_flags(self):
        import local_ai
        self.assertEqual(local_ai._gpu_flags("cpu"), [])
        self.assertEqual(local_ai._gpu_flags("vulkan"), ["-ngl", "99"])

    def test_vulkan_dir_is_separate(self):
        import paths
        self.assertNotEqual(paths.runtime_llama_vulkan_dir(), paths.runtime_llama_dir())
        self.assertIn("llama-cpp-vulkan", paths.runtime_llama_vulkan_dir())

    def test_asset_names_by_variant(self):
        from tools import fetch_llamacpp as ff
        self.assertEqual(ff._asset_name("b10590", "windows", "x86_64", "cpu"),
                         "llama-b10590-bin-win-cpu-x64.zip")
        self.assertEqual(ff._asset_name("b10590", "windows", "x86_64", "vulkan"),
                         "llama-b10590-bin-win-vulkan-x64.zip")
        self.assertEqual(ff._asset_name("b10590", "linux", "x86_64", "vulkan"),
                         "llama-b10590-bin-ubuntu-vulkan-x64.tar.gz")
        self.assertEqual(ff._asset_name("b10590", "linux", "aarch64", "vulkan"),
                         "llama-b10590-bin-ubuntu-vulkan-arm64.tar.gz")
        # mac 走 Metal,无 Vulkan 资产
        self.assertIsNone(ff._asset_name("b10590", "osx", "arm64", "vulkan"))

    def test_vulkan_assets_have_pinned_sha256(self):
        from tools import fetch_llamacpp as ff
        for asset in ("llama-b10590-bin-win-vulkan-x64.zip",
                      "llama-b10590-bin-ubuntu-vulkan-x64.tar.gz",
                      "llama-b10590-bin-ubuntu-vulkan-arm64.tar.gz"):
            self.assertIn(asset, ff.ASSET_SHA256, f"{asset} 未登记 SHA256")
            self.assertEqual(64, len(ff.ASSET_SHA256[asset]))

    def test_vulkan_supported_platform(self):
        import local_ai
        if sys.platform.startswith("darwin"):
            self.assertFalse(local_ai._vulkan_supported(), "mac 无 Vulkan(走 Metal)")

    def test_gpu_backend_from_settings_is_valid(self):
        import local_ai
        self.assertIn(local_ai.gpu_backend_from_settings(), local_ai.GPU_BACKENDS)


if __name__ == "__main__":
    unittest.main()
