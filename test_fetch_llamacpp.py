import io
import os
import tarfile
import tempfile
import unittest
import zipfile

from tools import fetch_llamacpp


class FetchLlamaCppTests(unittest.TestCase):
    def test_windows_extract_keeps_server_dependencies_only(self):
        with tempfile.TemporaryDirectory() as temp:
            archive = os.path.join(temp, "runtime.zip")
            output = os.path.join(temp, "out")
            with zipfile.ZipFile(archive, "w") as bundle:
                bundle.writestr("build/bin/llama-server.exe", b"server")
                bundle.writestr("build/bin/llama-server-impl.dll", b"impl")
                bundle.writestr("build/bin/llama.dll", b"llama")
                bundle.writestr("build/bin/ggml.dll", b"ggml")
                bundle.writestr("build/bin/llama-cli.exe", b"unneeded")
            extracted = fetch_llamacpp._extract(archive, output, "windows")
            self.assertIn("llama-server.exe", extracted)
            self.assertIn("llama-server-impl.dll", extracted)
            self.assertFalse(os.path.exists(os.path.join(output, "llama-cli.exe")))
            fetch_llamacpp.verify_runtime(output, "windows")

    def test_posix_extract_keeps_shared_libraries(self):
        with tempfile.TemporaryDirectory() as temp:
            archive = os.path.join(temp, "runtime.tar.gz")
            output = os.path.join(temp, "out")
            with tarfile.open(archive, "w:gz") as bundle:
                for name, content in (("bin/llama-server", b"server"),
                                      ("lib/libllama.so.0", b"library"),
                                      ("bin/llama-cli", b"unneeded")):
                    info = tarfile.TarInfo(name)
                    info.size = len(content)
                    bundle.addfile(info, io.BytesIO(content))
            extracted = fetch_llamacpp._extract(archive, output, "linux")
            self.assertIn("llama-server", extracted)
            self.assertIn("libllama.so.0", extracted)
            self.assertFalse(os.path.exists(os.path.join(output, "llama-cli")))
            fetch_llamacpp.verify_runtime(output, "linux")

    def test_incomplete_windows_runtime_is_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            with open(os.path.join(temp, "llama-server.exe"), "wb") as stream:
                stream.write(b"server")
            with self.assertRaisesRegex(RuntimeError, "llama-server-impl.dll"):
                fetch_llamacpp.verify_runtime(temp, "windows")

    def test_every_supported_asset_has_a_pinned_digest(self):
        for os_name in ("windows", "osx", "linux"):
            for arch in ("x64", "arm64"):
                asset = fetch_llamacpp._asset_name(fetch_llamacpp.DEFAULT_VERSION, os_name, arch)
                self.assertIn(asset, fetch_llamacpp.ASSET_SHA256)
                self.assertEqual(64, len(fetch_llamacpp.ASSET_SHA256[asset]))


if __name__ == "__main__":
    unittest.main()
