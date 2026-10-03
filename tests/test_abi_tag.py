"""
Tests that ``_abi_tag`` yields a tag pip can install, for every SOABI shape.

The Windows 3.13 spelling (``cp313-win_amd64``) is the one that shipped as
``cpwin_amd64`` (gh-68); the others are here so a fix for it cannot
regress them. Each name is checked against ``packaging``'s own parser when
that is installed, and against the shape of a tag otherwise.
"""

import re
import sys
import unittest
from pathlib import Path

SRC = Path(__file__).parent.parent / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from just_buildit import _wheel

CASES = {
    "cpython-312-x86_64-linux-gnu": "cp312",
    "cpython-313t-x86_64-linux-gnu": "cp313t",
    "cpython-311-darwin": "cp311",
    "cp313-win_amd64": "cp313",
    "cp314t-win_amd64": "cp314t",
}


class AbiTag(unittest.TestCase):
    def test_every_soabi_shape(self):
        for soabi, want in CASES.items():
            with self.subTest(soabi=soabi):
                self.assertEqual(_wheel._abi_tag(soabi), want)

    def test_no_soabi_falls_back_to_python_tag(self):
        # Windows before 3.13 defines no SOABI.
        self.assertEqual(_wheel._abi_tag(""), _wheel._python_tag())

    def test_name_parses_as_a_wheel(self):
        try:
            from packaging.utils import parse_wheel_filename
        except ImportError:
            for soabi in CASES:
                self.assertRegex(_wheel._abi_tag(soabi), r"^cp\d+t?$")
            return
        for soabi in CASES:
            abi = _wheel._abi_tag(soabi)
            name = f"p-1.0-cp313-{abi}-win_amd64.whl"
            with self.subTest(soabi=soabi):
                parse_wheel_filename(name)
                self.assertTrue(re.fullmatch(r"cp\d+t?", abi))


if __name__ == "__main__":
    unittest.main()
