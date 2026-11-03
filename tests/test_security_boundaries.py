import io
import sys
import unittest
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from find_transport import NoEnturRedirects, request_json  # noqa: E402


class ProviderBoundaryTests(unittest.TestCase):
    def test_entur_helper_accepts_only_fixed_https_origin(self):
        for url in (
            "http://api.entur.io/geocoder/v1/autocomplete",
            "https://example.com/geocoder/v1/autocomplete",
            "https://user@api.entur.io/geocoder/v1/autocomplete",
            "https://api.entur.io:444/geocoder/v1/autocomplete",
        ):
            with self.subTest(url=url), self.assertRaises(ValueError):
                request_json(urllib.request.Request(url), opener=lambda *_args, **_kwargs: io.BytesIO(b"{}"))

    def test_entur_helper_decodes_bounded_provider_response(self):
        result = request_json(
            urllib.request.Request("https://api.entur.io/geocoder/v1/autocomplete"),
            opener=lambda *_args, **_kwargs: io.BytesIO(b'{"features": []}'),
        )
        self.assertEqual(result, {"features": []})

    def test_entur_helper_refuses_redirects(self):
        with self.assertRaises(RuntimeError):
            NoEnturRedirects().redirect_request(None, None, 302, "redirect", {}, "https://example.com")

    def test_healthcheck_has_no_shell_command_execution(self):
        source = (ROOT / "scripts" / "healthcheck.py").read_text(encoding="utf-8")
        self.assertNotIn("shell=True", source)
        self.assertNotIn("subprocess.run(cmd", source)

    def test_untrusted_content_uses_dedicated_agents(self):
        briefing = (ROOT / "scripts" / "briefing.py").read_text(encoding="utf-8")
        ukeplan = (ROOT / "scripts" / "interpret_ukeplan.py").read_text(encoding="utf-8")
        agent_setup = (ROOT / "scripts" / "configure_inference_agents.sh").read_text(encoding="utf-8")

        self.assertIn('"familybot-briefing"', briefing)
        self.assertIn('"familybot-ukeplan"', ukeplan)
        self.assertNotIn('"--agent", "main"', briefing)
        self.assertNotIn('"--agent", "main"', ukeplan)
        self.assertIn('tools.elevated.enabled"', agent_setup)
        self.assertIn("group:runtime", agent_setup)
        self.assertIn('skills"', agent_setup)


if __name__ == "__main__":
    unittest.main()
