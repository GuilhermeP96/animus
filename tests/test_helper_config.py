"""Helpers must never load a caller's project .env or echo validation input."""
import importlib.util
import os
from pathlib import Path
import tempfile
import unittest

from pydantic import ValidationError

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('helper_config', ROOT / 'skills/animus-rag/scripts/helper_config.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class HelperConfigTests(unittest.TestCase):
    def test_caller_dotenv_is_ignored(self):
        previous = Path.cwd()
        with tempfile.TemporaryDirectory() as tmp:
            Path(tmp, '.env').write_text('UNRELATED_SECRET=CANARY_DO_NOT_EXPOSE\nANIMUS_NODE_NAME=wrong-project\n')
            try:
                os.chdir(tmp)
                cfg = module.HelperConfig()
                self.assertNotEqual(cfg.node_name, 'wrong-project')
            finally:
                os.chdir(previous)

    def test_validation_hides_input(self):
        with self.assertRaises(ValidationError) as raised:
            module.HelperConfig(server_port='CANARY_DO_NOT_EXPOSE')
        self.assertNotIn('CANARY_DO_NOT_EXPOSE', str(raised.exception))
