"""Run the offline suite with ephemeral user state, never the peer's live HOME."""
from pathlib import Path
import os
import subprocess
import sys
import tempfile

root = Path(__file__).resolve().parents[2]
if (root / '.env').exists():
    raise SystemExit('Private dotenv cannot enter a CI snapshot')
with tempfile.TemporaryDirectory(prefix='.animus-ci-', dir=root) as directory:
    home = Path(directory) / 'home'
    home.mkdir(mode=0o700)
    environment = {k: v for k, v in os.environ.items()
                   if not k.startswith(('ANIMUS_', 'TURNSTILE_'))}
    environment.update(HOME=str(home), USERPROFILE=str(home),
                       XDG_DATA_HOME=str(home / '.local/share'),
                       PYTHONIOENCODING='utf-8', PYTHONUTF8='1',
                       PYTHONDONTWRITEBYTECODE='1', PYTHONPATH=str(root))
    if os.name == 'nt':
        environment.update(HOMEDRIVE=home.drive, HOMEPATH=str(home)[len(home.drive):],
                           APPDATA=str(home / 'AppData/Roaming'),
                           LOCALAPPDATA=str(home / 'AppData/Local'))
    # Give Python and native PowerShell helpers one explicit owned fixture root,
    # independent of the user's provider directories and default TEMP location.
    result = subprocess.run([sys.executable, '-m', 'pytest', '-q', '-p', 'no:cacheprovider',
                             '--basetemp', str(Path(directory) / 'pytest')],
                            cwd=root, env=environment,
                            timeout=900 if os.name == 'nt' else 150, check=False,
                            **({'umask': 0o022} if os.name == 'posix' else {}))
    raise SystemExit(result.returncode)
