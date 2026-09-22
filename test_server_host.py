import sys
import tempfile
import time
import unittest
from pathlib import Path
import os
import subprocess

from server_host_client import managed_status, send_server_command


class ServerHostTests(unittest.TestCase):
    def test_detached_host_reconnects_logs_and_commands(self):
        with tempfile.TemporaryDirectory() as root:
            script = Path(root, 'fake_server.py')
            script.write_text(
                "import sys\n"
                "print('SERVER READY', flush=True)\n"
                "for line in sys.stdin:\n"
                "    command = line.strip()\n"
                "    print('COMMAND ' + command, flush=True)\n"
                "    if command == 'stop': break\n",
                encoding='utf-8')
            starter = (
                'import sys; from server_host_client import start_managed_server; '
                'start_managed_server(sys.argv[1], sys.executable, [sys.argv[2]], timeout=8)')
            subprocess.run([sys.executable, '-c', starter, root, str(script)],
                           cwd=Path(__file__).resolve().parent, check=True,
                           stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
            # The process that launched the host has now exited: this models
            # closing AMCL and opening it again before reconnecting.
            state = managed_status(root)
            try:
                self.assertTrue(state['running'])
                reconnected = managed_status(root)
                self.assertTrue(reconnected['running'])
                self.assertEqual(reconnected['sessionId'], state['sessionId'])
                send_server_command(root, 'say hello')
                deadline = time.monotonic() + 5
                log = Path(state['logFile'])
                while time.monotonic() < deadline:
                    text = log.read_text(encoding='utf-8', errors='replace') if log.exists() else ''
                    if 'COMMAND say hello' in text:
                        break
                    time.sleep(0.05)
                self.assertIn('SERVER READY', text)
                self.assertIn('COMMAND say hello', text)
            finally:
                try:
                    send_server_command(root, 'stop')
                except Exception:
                    pass
            deadline = time.monotonic() + 5
            while time.monotonic() < deadline:
                ended = managed_status(root, probe=False)
                if ended and not ended['running']:
                    break
                time.sleep(0.05)
            self.assertFalse(ended['running'])
            self.assertEqual(ended['exitCode'], 0)
            # host.json is finalized just before the detached helper exits;
            # wait until Windows releases its working-directory handle.
            deadline = time.monotonic() + 5
            while time.monotonic() < deadline:
                try:
                    os.kill(ended['hostPid'], 0)
                except OSError:
                    break
                time.sleep(0.05)
            time.sleep(0.3)


if __name__ == '__main__':
    unittest.main()
