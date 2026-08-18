import importlib.util
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("validate_docs", ROOT / "scripts" / "validate_docs.py")
assert SPEC and SPEC.loader
VALIDATE_DOCS = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(VALIDATE_DOCS)


class DocumentationContractTests(unittest.TestCase):
    def test_repository_documentation_contract(self):
        self.assertEqual([], VALIDATE_DOCS.validate_repository(ROOT))


if __name__ == "__main__":
    unittest.main()
