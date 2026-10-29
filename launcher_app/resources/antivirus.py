"""Best-effort Defender custom scan; never changes protection/remediation policy."""
import os
import re
import subprocess
import tempfile
import time
from pathlib import Path

from launcher_app.core.task_context import checkpoint


def find_defender():
    if os.name != 'nt':
        return None
    platform = Path(os.environ.get('ProgramData', r'C:\ProgramData'), 'Microsoft', 'Windows Defender', 'Platform')
    candidates = []
    try:
        versions = sorted((p for p in platform.iterdir() if p.is_dir()),
                          key=lambda p: tuple(int(n) for n in re.findall(r'\d+', p.name)), reverse=True)
        candidates.extend(p / 'MpCmdRun.exe' for p in versions)
    except OSError:
        pass
    candidates.append(Path(os.environ.get('ProgramFiles', r'C:\Program Files'), 'Windows Defender', 'MpCmdRun.exe'))
    return next((str(p) for p in candidates if p.is_file()), None)


def find_eset():
    if os.name != 'nt':
        return None
    for root in ('ProgramFiles', 'ProgramFiles(x86)'):
        folder = os.environ.get(root)
        if folder:
            binary = Path(folder, 'ESET', 'ESET Security', 'ecls.exe')
            if binary.is_file():
                return str(binary)
    return None


def scan_available_archive(path, timeout_seconds=300):
    """Prefer Defender; do not replace an alert with a second engine's clean result."""
    result = scan_archive(path, timeout_seconds)
    if result['status'] in ('unavailable', 'incomplete') and find_eset():
        fallback = scan_archive(path, timeout_seconds, engine='eset')
        fallback['previous_attempt'] = result
        return fallback
    return result


def scan_archive(path, timeout_seconds=300, *, engine='defender'):
    if engine not in ('defender', 'eset'):
        raise ValueError('不支持的扫描引擎')
    archive = Path(path).resolve(strict=True)
    if not archive.is_file() or archive.suffix.lower() not in ('.zip', '.mrpack'):
        raise ValueError('杀毒检查只接受本地 ZIP/MRPACK 文件')
    binary = find_defender() if engine == 'defender' else find_eset()
    name = 'Microsoft Defender' if engine == 'defender' else 'ESET'
    base = {'engine': name, 'remediation_requested': False,
            'notice': '仅请求检测，不修改系统防护设置；无检出不等于绝对安全。'}
    if not binary:
        return {**base, 'status': 'unavailable', 'message': f'未找到可用 {name}，请使用本机杀软手动扫描。'}
    from launcher_app.runtime.windows_runtime_support import _trusted_signature
    if not _trusted_signature(binary)[0]:
        return {**base, 'status': 'unavailable', 'message': f'{name} 扫描程序的系统签名验证未通过，未执行。'}
    process = None
    try:
        # A list, absolute trusted binary and no shell. No enabling AV, adding
        # exclusions, restoring/quarantining items, or custom executable paths.
        with tempfile.TemporaryFile() as output:
            arguments = ([binary, '-Scan', '-ScanType', '3', '-File', str(archive), '-DisableRemediation']
                         if engine == 'defender' else
                         [binary, '/clean-mode=none', '/arch', '/no-symlink', str(archive)])
            process = subprocess.Popen(arguments, stdout=output, stderr=subprocess.STDOUT,
                                       creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
            deadline = time.monotonic() + timeout_seconds
            while process.poll() is None:
                checkpoint()
                if time.monotonic() >= deadline:
                    return {**base, 'status': 'incomplete', 'message': '扫描等待超时，不能认为文件已通过。'}
                try:
                    process.wait(timeout=0.2)
                except subprocess.TimeoutExpired:
                    pass
            code = process.returncode
            output.seek(0)
            report = output.read(65536)
            report_path = archive.with_name(archive.name + f'.{engine}-scan.txt')
            details = {}
            try:
                try:
                    report_text = report.decode('utf-8')
                except UnicodeDecodeError:
                    report_text = report.decode('mbcs' if os.name == 'nt' else 'utf-8', errors='replace')
                report_path.write_text(report_text, encoding='utf-8')
                details['report_path'] = str(report_path)
            except OSError:
                pass
            if engine == 'eset':
                state = ('no_detection_reported' if code == 0 else
                         'attention_required' if code in (1, 50) else 'incomplete')
                return {**base, **details, 'status': state, 'exit_code': code,
                        'message': ('ESET 本次未报告威胁；不代表绝对安全。' if code == 0 else
                                    'ESET 报告威胁，请查看扫描报告。' if code in (1, 50) else
                                    'ESET 未完成全部扫描，请手动检查；不能认定已通过。')}
            failure = re.search(rb'Failed with hr\s*=\s*(0x[0-9a-f]+)', report, re.I)
            if failure:
                return {**base, **details, 'status': 'incomplete', 'exit_code': code,
                        'hresult': failure[1].decode('ascii'),
                        'message': 'Defender 明确报告扫描失败，未完成杀毒检查；请查看本机扫描报告。'}
            if code == 0:
                return {**base, **details, 'status': 'no_detection_reported', 'exit_code': code,
                        'message': '本次不自动处理文件的扫描未报告威胁；不是无恶意代码的保证。'}
            # Code 2 can mean detection OR scan errors per Microsoft docs.
            return {**base, **details, 'status': 'attention_required' if code == 2 else 'incomplete', 'exit_code': code,
                    'message': '可能检出威胁或扫描出错，请查看本次扫描报告，不能认定已通过；只检测模式的告警未必出现在Windows安全中心。'}
    except OSError:
        return {**base, 'status': 'incomplete', 'message': '无法启动扫描，可能服务未运行或需要系统权限，请手动检查。'}
    finally:
        if process is not None and process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()
