import shutil
import subprocess
import unittest
from pathlib import Path

from django.test import SimpleTestCase

JS_TEST = Path(__file__).parent / "js" / "anchors.test.mjs"


@unittest.skipUnless(shutil.which("node"), "node is not installed")
class AnchorResolutionJsTests(SimpleTestCase):
    """The text-anchoring cascade lives in notes/static/notes/anchors.js and is
    exercised by node's built-in test runner, so it stays a pure module."""

    def test_anchor_resolution_suite_passes(self):
        result = subprocess.run(
            ["node", "--test", str(JS_TEST)],
            capture_output=True,
            text=True,
            timeout=120,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
