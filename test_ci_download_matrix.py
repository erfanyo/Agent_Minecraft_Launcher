"""Offline end-to-end download checks for the supported Minecraft generations.

The tiny HTTP server exercises the real downloader and SHA-1 checks without
depending on Mojang or Modrinth availability during a CI run.
"""
import hashlib
import json
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit

import game_files
import instance_install_service
import modrinth


VERSIONS = ("1.7.10", "1.8.9", "1.12.2", "1.16.5", "1.18.2",
            "1.19.4", "1.20.1", "1.21.1")


def _sha1(data):
    return hashlib.sha1(data).hexdigest()


class LocalDownloads(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.routes = {}
        self.requests = []
        routes, requests = self.routes, self.requests

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                parsed = urlsplit(self.path)
                requests.append((parsed.path, parse_qs(parsed.query)))
                body = routes.get(parsed.path)
                if callable(body):
                    body = body(parse_qs(parsed.query))
                if body is None:
                    self.send_error(404)
                    return
                if not isinstance(body, bytes):
                    body = json.dumps(body).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *_args):
                pass

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.addCleanup(self._stop_server)
        self.base = f"http://127.0.0.1:{self.server.server_port}"

    def _stop_server(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)

    def _file(self, path, data):
        self.routes[path] = data
        return {"url": self.base + path, "sha1": _sha1(data), "size": len(data)}

    def test_vanilla_instance_downloads_across_supported_generations(self):
        details = {}
        for version in VERSIONS:
            client = self._file(f"/client/{version}.jar", f"client {version}".encode())
            library = self._file(f"/library/{version}.jar", f"library {version}".encode())
            asset = f"asset {version}".encode()
            digest = _sha1(asset)
            self.routes[f"/assets/{digest[:2]}/{digest}"] = asset
            asset_name = ("minecraft/lang/en_us.lang" if version in VERSIONS[:3]
                          else "minecraft/sounds/test.ogg")
            index = {"objects": {asset_name: {"hash": digest, "size": len(asset)}}}
            index_bytes = json.dumps(index).encode()
            asset_index = self._file(f"/index/{version}.json", index_bytes)
            details[version] = {
                "id": version, "downloads": {"client": client},
                "assetIndex": {"id": version, **asset_index},
                "libraries": [{"name": f"ci:fixture:{version}", "downloads": {
                    "artifact": {"path": f"ci/fixture/{version}/fixture.jar", **library}}}],
            }

        service = instance_install_service.InstanceInstallService(
            lambda: self.temp.name, lambda: True)
        with patch.object(instance_install_service, "fetch_version_manifest",
                          return_value={"versions": [{"id": v, "type": "release", "url": v}
                                                     for v in VERSIONS]}), \
             patch.object(instance_install_service, "fetch_version_detail",
                          side_effect=lambda url: details[url]), \
             patch.object(game_files, "RESOURCE_URL", self.base + "/assets/{hash2}/{hash}"):
            for version in VERSIONS:
                with self.subTest(version=version):
                    status = []
                    self.assertTrue(service.install_version(version, status_cb=status.append), status)
                    root = Path(self.temp.name)
                    self.assertEqual((root / "versions" / version / f"{version}.jar").read_bytes(),
                                     f"client {version}".encode())
                    self.assertEqual((root / "libraries" / "ci" / "fixture" / version /
                                      "fixture.jar").read_bytes(), f"library {version}".encode())
                    asset = f"asset {version}".encode()
                    digest = _sha1(asset)
                    self.assertEqual((root / "assets" / "objects" / digest[:2] / digest).read_bytes(), asset)
                    if version in VERSIONS[:3]:
                        self.assertEqual((root / "assets" / "virtual" / "legacy" /
                                          "minecraft" / "lang" / "en_us.lang").read_bytes(), asset)
            self.assertFalse(service.install_version("1.6.4"))

    def test_modrinth_resource_types_download_and_verify(self):
        cases = (
            ("mod", "sodium", "1.20.1", "fabric", ".jar"),
            ("shader", "shader-demo", None, None, ".zip"),
            ("resourcepack", "textures-demo", None, None, ".zip"),
            ("datapack", "data-demo", None, None, ".zip"),
            ("modpack", "pack-demo", "1.21.1", "fabric", ".mrpack"),
        )
        for kind, slug, version, loader, extension in cases:
            payload = f"{kind} payload".encode()
            filename = slug + extension
            file_info = self._file(f"/files/{filename}", payload)
            row = {"id": slug + "-v1", "version_number": "1.0-beta", "version_type": "beta",
                   "game_versions": [version] if version else [],
                   "loaders": [loader] if loader else [], "dependencies": [],
                   "files": [{"filename": filename, "primary": True,
                              "hashes": {"sha1": file_info["sha1"]}, **file_info}]}

            def versions(query, row=row, version=version, loader=loader):
                if query.get("game_versions") and version not in json.loads(query["game_versions"][0]):
                    return []
                if query.get("loaders") and loader not in json.loads(query["loaders"][0]):
                    return []
                return [row]

            self.routes[f"/v2/project/{slug}/version"] = versions

        with patch.object(modrinth, "BASE", self.base + "/v2"):
            for kind, slug, version, loader, extension in cases:
                with self.subTest(kind=kind):
                    target = Path(self.temp.name) / kind
                    if kind == "modpack":
                        saved = modrinth.download_modpack(slug, str(target), version, loader)
                        self.assertEqual(Path(saved).read_bytes(), b"modpack payload")
                    else:
                        saved = modrinth.download_mod(slug, version, loader, str(target), strict=True)
                        self.assertEqual(saved, slug + extension)
                        self.assertEqual((target / saved).read_bytes(), f"{kind} payload".encode())
            self.routes["/v2/project/missing/version"] = []
            self.assertIsNone(modrinth.download_mod("missing", "1.20.1", "fabric",
                                                    self.temp.name, strict=True))

    def test_corrupt_resource_is_not_reported_as_downloaded(self):
        payload = b"corrupt"
        self.routes["/files/bad.jar"] = payload
        self.routes["/v2/project/bad/version"] = [{
            "id": "bad-v1", "version_number": "1", "version_type": "release",
            "files": [{"filename": "bad.jar", "primary": True,
                       "url": self.base + "/files/bad.jar",
                       "hashes": {"sha1": _sha1(b"correct")}}],
        }]
        target = Path(self.temp.name) / "bad"
        with patch.object(modrinth, "BASE", self.base + "/v2"):
            with self.assertRaises(Exception):
                modrinth.download_mod("bad", "1.20.1", "fabric", str(target), strict=True)
        self.assertFalse((target / "bad.jar").exists())


if __name__ == "__main__":
    unittest.main()
