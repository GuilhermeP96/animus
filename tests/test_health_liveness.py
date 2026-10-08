import ast
import asyncio
from pathlib import Path
import time
import unittest


class HealthTests(unittest.IsolatedAsyncioTestCase):
    async def test_slow_statistics_do_not_block_liveness_and_response_is_compatible(self):
        source = Path(__file__).resolve().parents[1] / 'animus/server/app.py'
        tree = ast.parse(source.read_text())
        selected = [n for n in tree.body if isinstance(n, ast.AsyncFunctionDef) and n.name in ('health', 'health_live')]
        for node in selected: node.decorator_list = []
        class Engine:
            def get_stats(self):
                time.sleep(0.2)
                return {'total_memories': 42, 'unique_nodes': 3}
        context = {'asyncio': asyncio, 'get_engine': lambda: Engine(), '_connected_peers': {}}
        exec(compile(ast.Module(body=selected, type_ignores=[]), str(source), 'exec'), context)
        diagnostic = asyncio.create_task(context['health']())
        await asyncio.sleep(0.02)
        self.assertFalse(diagnostic.done(), 'Statistics must remain pending without blocking the loop')
        self.assertEqual(await asyncio.wait_for(context['health_live'](), 0.05), {'status': 'alive'})
        self.assertEqual(await diagnostic, {'status': 'healthy', 'memories': 42, 'nodes': 3, 'peers_online': 0})
