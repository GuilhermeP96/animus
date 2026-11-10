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
                       PYTHONDONTWRITEBYTECODE='1', PYTHONPATH=str(root))
    result = subprocess.run([sys.executable, '-m', 'pytest', '-q', '-p', 'no:cacheprovider'],
                            cwd=root, env=environment, timeout=150, check=False)
    raise SystemExit(result.returncode)
