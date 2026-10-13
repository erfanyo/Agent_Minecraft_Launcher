import json
from pathlib import Path
import socket
import tempfile
import threading
import time
import unittest
from tools import bridge_weather_test as weather


class WeatherScriptTests(unittest.TestCase):
    def fixture(self, directory, success=True, transport='tcp'):
        self.stop = threading.Event()
        self.addCleanup(self.stop.set)
        self.commands = []
        directory.joinpath('ai_request.json').write_text(json.dumps({
            'seq': 11, 'ts': int(time.time()*1000), 'text': weather.PROMPT,
            'player': 'BridgeTester', 'protocol_version': 2, 'exec_mode': 'player',
            'permission_level': 4 if success else 0, 'server_type': 'singleplayer'}))
        port = 0
        listener = None
        if transport == 'tcp':
            directory.joinpath('token.txt').write_text('test-only-token')
            listener = socket.socket()
            listener.bind(('127.0.0.1', 0))
            listener.listen()
            listener.settimeout(2)
            port = listener.getsockname()[1]
            self.addCleanup(listener.close)
        def fake_mod():
            try:
                if listener:
                    client, _ = listener.accept()
                    with client:
                        request = json.loads(client.makefile('rb').readline())
                        self.commands.append(request)
                        reply = {'seq': request['seq'], 'command': weather.COMMAND,
                                 'success': success, 'result': 'Set weather to rain' if success else 'Permission denied'}
                        client.sendall((json.dumps(reply)+'\n').encode())
                else:
                    deadline = time.monotonic()+2
                    while time.monotonic()<deadline:
                        request=weather.read_json(directory/'command_request.json')
                        if request:
                            self.commands.append(request)
                            weather.write_json(directory/'command_reply.json', {'seq':request['seq'],
                                'success':success,'result':'Executed' if success else 'Permission denied'})
                            break
                        time.sleep(.01)
                deadline=time.monotonic()+2
                while time.monotonic()<deadline and not self.stop.is_set():
                    reply=weather.read_json(directory/'ai_reply.json')
                    if reply:
                        self.chat_reply=reply
                        directory.joinpath('ai_reply.json').unlink()
                        return
                    time.sleep(.01)
            except OSError:
                pass
        thread=threading.Thread(target=fake_mod,daemon=True)
        thread.start()
        self.addCleanup(thread.join, 3)
        return port

    def test_tcp_success_and_player_identity(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory=Path(temporary)
            port=self.fixture(directory)
            result=weather.run_case(directory,port=port,started_ms=0,result_timeout=2)
            self.assertTrue(result['passed'])
            self.assertEqual(self.commands[0]['as_player'],'BridgeTester')
            self.assertEqual(self.chat_reply['seq'],11)
            self.assertNotIn('test-only-token',json.dumps(result))
            self.assertFalse(result['worldWeatherVerified'])

    def test_tcp_denied_is_a_passing_negative_case(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory=Path(temporary)
            port=self.fixture(directory,success=False)
            result=weather.run_case(directory,port=port,started_ms=0,result_timeout=2,expect='denied')
            self.assertTrue(result['passed'])
            self.assertFalse(result['execution']['success'])

    def test_legacy_file_round_trip(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory=Path(temporary)
            self.fixture(directory,transport='file')
            result=weather.run_case(directory,started_ms=0,result_timeout=2)
            self.assertTrue(result['passed'])
            self.assertEqual(result['transport'],'file')
            self.assertEqual(self.commands[0]['as_player'],'BridgeTester')

    def test_wrong_sequence_rejected(self):
        with self.assertRaisesRegex(ValueError,'sequence'):
            weather.validate_result({'seq':2},1)

    def test_wrong_command_rejected(self):
        with self.assertRaisesRegex(ValueError,'another command'):
            weather.validate_result({'seq':1,'command':'give @p diamond','success':True,'result':'ok'},1)

    def test_console_and_old_protocol_rejected(self):
        for request in ({'player':'Steve'}, {'player':'Steve','protocol_version':2,'exec_mode':'console'},
                        {'player':'','protocol_version':2}):
            with self.subTest(request=request), self.assertRaises(ValueError):
                weather.validate_request(request)

    def test_stale_ai_request_is_ignored(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory=Path(temporary)
            weather.write_json(directory/'ai_request.json',{'seq':1,'text':weather.PROMPT,'ts':1})
            with self.assertRaises(TimeoutError):
                weather.wait_request(directory,started_ms=2,timeout=.05)

    def test_malformed_protocol_rejected(self):
        for version in (None, '2', True, 1):
            with self.subTest(version=version), self.assertRaises(ValueError):
                weather.validate_request({'player':'Steve','protocol_version':version})

    def test_boolean_sequence_is_not_integer_sequence(self):
        with self.assertRaises(ValueError):
            weather.validate_result({'seq':True,'command':weather.COMMAND,'success':True,'result':'ok'},1)

    def test_incomplete_result_rejected(self):
        for success, feedback in ((1,'ok'), ('true','ok'), (True,None)):
            with self.subTest(success=success), self.assertRaises(ValueError):
                weather.validate_result({'seq':1,'command':weather.COMMAND,'success':success,'result':feedback},1)

    def test_invalid_json_ignored(self):
        with tempfile.TemporaryDirectory() as temporary:
            path=Path(temporary)/'request.json'
            for content in ('{broken', '[]', 'null'):
                path.write_text(content)
                self.assertIsNone(weather.read_json(path))

    def test_future_request_is_ignored(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory=Path(temporary)
            weather.write_json(directory/'ai_request.json',{'seq':1,'text':weather.PROMPT,'ts':time.time()*1000+60000})
            with self.assertRaises(TimeoutError):
                weather.wait_request(directory,started_ms=0,timeout=.05)

    def test_denial_does_not_pass_expected_success(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory=Path(temporary)
            port=self.fixture(directory,success=False)
            result=weather.run_case(directory,port=port,started_ms=0,result_timeout=2,expect='success')
            self.assertFalse(result['passed'])

    def test_success_does_not_pass_expected_denial(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory=Path(temporary)
            port=self.fixture(directory,success=True)
            result=weather.run_case(directory,port=port,started_ms=0,result_timeout=2,expect='denied')
            self.assertFalse(result['passed'])

    def test_invalid_case_parameters_rejected(self):
        with self.assertRaises(ValueError):
            weather.run_case(Path('.'),expect='anything')
