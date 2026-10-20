import json
import os
from pathlib import Path
import subprocess
import sys

import pytest


@pytest.mark.skipif(os.name=='nt',reason='POSIX exec must retain process identity')
def test_reexec_keeps_module_invocation_and_pid(tmp_path):
    package=tmp_path/'restart_fixture';package.mkdir();(package/'__init__.py').write_text('')
    (package/'__main__.py').write_text('''import json,os
from animus.network import updater
if not os.environ.get('ANIMUS_OWNED_RESTART_PROBE'):
    os.environ['ANIMUS_OWNED_RESTART_PROBE']=str(os.getpid())
    updater.restart_in_place()
else:
    print(json.dumps({'same_pid':str(os.getpid())==os.environ['ANIMUS_OWNED_RESTART_PROBE']}))
''')
    env={**os.environ,'PYTHONPATH':str(tmp_path)+os.pathsep+str(Path(__file__).resolve().parents[1])}
    env.pop('ANIMUS_OWNED_RESTART_PROBE',None)
    result=subprocess.run([sys.executable,'-m','restart_fixture'],env=env,capture_output=True,text=True,timeout=15,check=True)
    assert json.loads(result.stdout)['same_pid'] is True
