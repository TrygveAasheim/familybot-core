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

    def test_fresh_setup_uses_paired_public_refs_without_review_placeholders(self):
        commands = "\n".join(
            f"git clone --branch main https://github.com/TrygveAasheim/{repo}.git"
            for repo in ("familybot-core", "familybot-portal")
        )
        self.assertEqual([], VALIDATE_DOCS.validate_fresh_install_refs(commands))
        for invalid in (
            commands.replace("--branch main", "--branch dev", 1),
            commands + "\ngit switch --detach REVIEWED_CORE_SHA",
            commands + "\ncodex/readiness-review-fixes",
        ):
            with self.subTest(invalid=invalid):
                self.assertTrue(VALIDATE_DOCS.validate_fresh_install_refs(invalid))


if __name__ == "__main__":
    unittest.main()
