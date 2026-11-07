"""Keep business entry points usable without importing a frontend or main.py."""
import ast
from pathlib import Path
import subprocess
import sys
import pytest

ROOT=Path(__file__).resolve().parents[2]
HEADLESS=(
    'instances.install_options', 'instances.instance_install_service', 'instances.install_requests',
    'instances.launch_preparation', 'instances.crash_diagnostics',
    'resources.download_jobs', 'resources.resource_compatibility',
    'runtime.running_games', 'runtime.jvm_options',
    'ai.tool_catalog', 'ai.tool_executor', 'ai.response_router', 'ai.assistant_defaults',
    'servers.repair_policy', 'instances.instance_actions',
    'instances.command_setup', 'runtime.online_mods',
    'core.path_validation', 'instances.kubejs_scripts',
    'runtime.game_runtime', 'runtime.launch_memory', 'runtime.process_metrics',
    'ai.game_integration', 'ai.context_builder',
)


@pytest.mark.parametrize('module',HEADLESS)
def test_business_module_does_not_import_window_or_widgets(module):
    tree=ast.parse((ROOT/'launcher_app'/Path(*module.split('.'))).with_suffix('.py').read_text(encoding='utf-8'))
    for node in ast.walk(tree):
        if isinstance(node,ast.ImportFrom):
            assert node.module!='main',module
            assert not (node.module or '').startswith(('launcher_app.ui','PySide6.QtWidgets')),module
        elif isinstance(node, ast.Import):
            for alias in node.names:
                assert alias.name != 'main', module
                assert not alias.name.startswith(('launcher_app.ui', 'PySide6.QtWidgets')), module


def test_headless_imports_and_full_tool_catalog_in_fresh_process():
    script='''
import sys
from launcher_app.instances.instance_install_service import InstanceInstallService
from launcher_app.resources.download_jobs import ArchiveImportJob, PackDownloadJob
from launcher_app.ai.tool_catalog import TOOLS, WRITE_TOOLS, CONFIRM_TOOLS
from launcher_app.ai.tool_executor import build_executor
from launcher_app.ai.response_router import route_answer
from launcher_app.instances.command_setup import CommandSetupRequest
from launcher_app.instances.instance_actions import InstanceActions
from launcher_app.runtime.game_runtime import GameRuntime
from launcher_app.runtime.launch_memory import WindowReadinessTracker
from launcher_app.ai.game_integration import GameIntegration
from launcher_app.core.path_validation import assess_game_path
from launcher_app.instances.kubejs_scripts import read_script
assert 'main' not in sys.modules
assert 'PySide6.QtWidgets' not in sys.modules
names={row['function']['name'] for row in TOOLS}
assert {'set_server_mod_enabled','restore_instance_snapshot','list_instance_snapshots','read_public_webpage'} <= names
assert 'set_server_mod_enabled' in WRITE_TOOLS & CONFIRM_TOOLS
print('headless boundaries OK')
'''
    result=subprocess.run([sys.executable,'-c',script],cwd=ROOT,capture_output=True,text=True,timeout=20)
    assert result.returncode==0,result.stderr


def test_legacy_ai_exports_share_the_headless_catalog():
    from launcher_app.ai import assistant,tool_catalog,tool_executor,response_router
    assert assistant.TOOLS is tool_catalog.TOOLS
    assert assistant.build_executor is tool_executor.build_executor
    assert assistant.route_answer is response_router.route_answer
