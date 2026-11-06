from __future__ import annotations

import http.client
import json
import os
import socket
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import family_config  # noqa: E402
import install_familybot as installer  # noqa: E402
import manage_database  # noqa: E402
import reliability  # noqa: E402
import validate_config  # noqa: E402

PORTAL = Path(os.environ.get("FAMILYBOT_TEST_PORTAL_REPO", ROOT.parent / "familybot-portal"))
if not PORTAL.is_dir():
    PORTAL = ROOT / "familybot-portal"


class InstallContractTests(unittest.TestCase):
    def test_readiness_tolerates_slow_optional_adapter_fallback(self):
        class DelayedDashboard(BaseHTTPRequestHandler):
            def log_message(self, *_args):
                pass

            def do_GET(self):  # noqa: N802
                if self.path == "/api/dashboard":
                    time.sleep(2.2)  # exceeds the old two-second probe timeout
                payloads = {
                    "/api/health": {"ok": True, "service": "familybot-dashboard-api"},
                    "/api/session": {"api": "familybot-local-v2", "token": "fixture-token"},
                    "/api/dashboard": {"children": [], "weather": {"ok": False}, "transport": {"ok": False}},
                }
                body = (json.dumps(payloads[self.path]).encode() if self.path in payloads
                        else b"<html>FamilyBot</html>")
                self.send_response(200)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                try:
                    self.wfile.write(body)
                except (BrokenPipeError, ConnectionResetError):
                    pass

        server = ThreadingHTTPServer(("127.0.0.1", 0), DelayedDashboard)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            port = server.server_port
            installer.verify_local_service(port, port, "localhost")
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)

    def test_probe_has_bounded_route_specific_timeouts(self):
        with patch.object(installer.http.client, "HTTPConnection") as connection:
            response = connection.return_value.getresponse.return_value
            response.status = 200
            response.read.side_effect = [
                b'{"ok":true,"service":"familybot-dashboard-api"}',
                b'{"api":"familybot-local-v2","token":"test"}',
                b'{"children":[]}', b'<html>FamilyBot</html>',
            ]
            installer.service_probe("localhost", 12345, 12346)
            self.assertEqual([2, 2, 10, 2], [c.kwargs["timeout"] for c in connection.call_args_list])
            self.assertGreater(connection.call_args_list[2].kwargs["timeout"], 4 + 4)
        with patch.object(installer.http.client, "HTTPConnection") as connection:
            connection.return_value.getresponse.side_effect = TimeoutError
            with self.assertRaisesRegex(installer.InstallError, "/api/health.*TimeoutError"):
                installer.service_probe("localhost", 12345, 12346)

    def test_workspace_defaults_and_explicit_legacy_precedence(self):
        for environment, expected in (
            ({}, Path.home() / ".familybot"),
            ({"OPENCLAW_WORKSPACE": "/fictional/legacy"}, Path("/fictional/legacy")),
            ({"OPENCLAW_WORKSPACE": "/fictional/legacy", "FAMILYBOT_WORKSPACE": "/fictional/Ny familie Ø"},
             Path("/fictional/Ny familie Ø")),
        ):
            with self.subTest(environment=environment), patch.dict(os.environ, environment, clear=True):
                self.assertEqual(expected, family_config.workspace_path())
                self.assertEqual(expected, reliability.workspace_path())
                self.assertEqual(expected / "db/family.db", manage_database.parser().parse_args(["status"]).db)
                self.assertEqual(expected / "config/family.local.json", validate_config.default_config_path())

    def test_hostname_detection_override_and_origin_replacement(self):
        with patch.object(installer.sys, "platform", "darwin"), patch.object(installer.subprocess, "run") as run:
            run.return_value = subprocess.CompletedProcess([], 0, "Kitchen-Mac\n", "")
            self.assertEqual("kitchen-mac.local", installer.new_hostname())
            self.assertEqual("192.168.1.45", installer.new_hostname("192.168.1.45"))
            self.assertEqual(1, run.call_count)
        for bad in ("http://host.local", "bad host", "host.local:3000", "../host", ""):
            with self.assertRaises(installer.InstallError):
                installer.new_hostname(bad)
        config = {"portal": {"hostname": "familie.local", "web_port": 3100,
                             "allowed_origins": ["http://familie.local:3100", "http://localhost:3100"]}}
        installer.set_new_hostname(config, "kitchen.local")
        self.assertEqual(["http://kitchen.local:3100", "http://localhost:3100"], config["portal"]["allowed_origins"])

    def test_unrelated_http_success_does_not_pass_identity_check(self):
        with patch.object(installer.http.client, "HTTPConnection") as connection:
            response = connection.return_value.getresponse.return_value
            response.status = 200
            response.read.return_value = b'{"ok":true,"service":"unrelated"}'
            with self.assertRaises(installer.InstallError):
                installer.service_probe("localhost", 12345, 12346)

    def test_hostname_must_reach_the_local_instance(self):
        with patch.object(installer.socket, "getaddrinfo"), patch.object(installer, "service_probe") as probe:
            probe.side_effect = ["local-session", "other-household"]
            with self.assertRaises(installer.InstallError):
                installer.verify_local_service(12345, 12346, "test.local", timeout=0.01)
            self.assertEqual("127.0.0.1", probe.call_args_list[0].args[0])
        with patch.object(installer.socket, "getaddrinfo"), patch.object(installer, "service_probe") as probe:
            probe.side_effect = OSError("Local API missing")
            with self.assertRaises(installer.InstallError):
                installer.verify_local_service(12345, 12346, "other.local", timeout=0.01)
            self.assertEqual(1, probe.call_count)

    def test_conflicting_ambient_config_stops_before_workspace_creation(self):
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory) / "not-created"
            environment = {k: v for k, v in os.environ.items() if not k.startswith("FAMILYBOT_")}
            environment["FAMILYBOT_FAMILY_CONFIG"] = str(Path(directory) / "another-household.json")
            result = subprocess.run([sys.executable, str(ROOT / "scripts/install_familybot.py"),
                                     "--workspace", str(workspace), "--portal-repo", str(PORTAL),
                                     "--demo", "--no-deploy", "--non-interactive"],
                                    env=environment, capture_output=True, text=True, check=False)
            self.assertEqual(1, result.returncode)
            self.assertFalse(workspace.exists())


def available_port() -> int:
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        return listener.getsockname()[1]


class ProcessLifecycleTests(unittest.TestCase):
    def test_fresh_http_chore_restart_and_repeat_install(self):
        with tempfile.TemporaryDirectory(prefix="familybot-clean-") as directory:
            root = Path(directory)
            workspace = root / "Ny familie Ø"
            environment = {k: v for k, v in os.environ.items()
                           if not k.startswith("FAMILYBOT_") and k != "OPENCLAW_WORKSPACE"}
            pin = root / "pin"
            pin.write_text("482731\n")
            pin.chmod(0o600)
            command = [sys.executable, str(ROOT / "scripts/install_familybot.py"),
                       "--workspace", str(workspace), "--portal-repo", str(PORTAL),
                       "--demo", "--hostname", "localhost", "--non-interactive", "--no-deploy",
                       "--parent-pin-source", str(pin)]
            result = subprocess.run(command, env=environment, capture_output=True, text=True, check=False)
            self.assertEqual(0, result.returncode, result.stderr)
            command.remove("--hostname")
            command.remove("localhost")
            port = available_port()
            process = None

            def stop():
                nonlocal process
                if process and process.poll() is None:
                    process.terminate()
                    try:
                        process.wait(timeout=10)
                    except subprocess.TimeoutExpired:
                        process.kill()
                        process.wait(timeout=5)

            def request(path, method="GET", payload=None, token="", parent=""):
                connection = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
                try:
                    connection.request(method, path, json.dumps(payload) if payload is not None else None,
                                       {"Origin": "http://localhost:3000", "Content-Type": "application/json",
                                        "X-FamilyBot-Local-Token": token, "X-FamilyBot-Parent-Token": parent})
                    response = connection.getresponse()
                    return response.status, json.loads(response.read())
                finally:
                    connection.close()

            def start():
                nonlocal process
                process = subprocess.Popen(
                    [sys.executable, str(PORTAL / "local_api/familybot_api.py"), "--workspace", str(workspace),
                     "--port", str(port)], env=environment | {"FAMILYBOT_WORKSPACE": str(workspace)},
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                )
                for _ in range(100):
                    self.assertIsNone(process.poll(), "API process exited before readiness")
                    try:
                        status, session = request("/api/session")
                        if status == 200:
                            return session["token"]
                    except OSError:
                        time.sleep(0.05)
                self.fail("API did not start")

            try:
                token = start()
                status, dashboard = request("/api/dashboard", token=token)
                self.assertEqual(200, status)
                self.assertFalse(dashboard["transport"]["ok"])
                child = dashboard["children"][0]
                status, login = request("/api/parent/session", "POST", {"pin": "482731"}, token)
                self.assertEqual(200, status)
                parent = login["parent_token"]
                payload = {"title": "Vann testplanten", "assigned_to": child["name"].lower(),
                           "icon": "🌱", "points": 7, "requires_approval": True, "repeat_mode": "once"}
                self.assertEqual(403, request("/api/chores", "POST", payload, token)[0])
                status, created = request("/api/chores", "POST", payload, token, parent)
                self.assertEqual(201, status, created)
                completion_payload = {"member_id": child["id"], "idempotency_key": "http-clean-install-0001"}
                route = f"/api/chores/{created['chore']['id']}/complete"
                status, completed = request(route, "POST", completion_payload, token)
                self.assertEqual(201, status)
                self.assertEqual("pending", completed["completion"]["status"])
                self.assertEqual(completed["completion"]["id"], request(route, "POST", completion_payload, token)[1]["completion"]["id"])
                route = f"/api/completions/{completed['completion']['id']}"
                self.assertEqual(403, request(route, "PATCH", {"decision": "awarded"}, token)[0])
                status, approved = request(route, "PATCH", {"decision": "awarded"}, token, parent)
                self.assertEqual(200, status)
                self.assertEqual("awarded", approved["completion"]["status"])
                for route in ("/api/oda/status", "/api/hellofresh/status", "/api/hellofresh/menu"):
                    self.assertEqual(404, request(route, token=token)[0])
                stop()
                result = subprocess.run(command, env=environment, capture_output=True, text=True, check=False)
                self.assertEqual(0, result.returncode, result.stderr)
                new_token = start()
                self.assertNotEqual(token, new_token)
                self.assertEqual(403, request("/api/dashboard", token=token)[0])
                _, dashboard = request("/api/dashboard", token=new_token)
                restored = next(c for c in dashboard["children"] if c["id"] == child["id"])
                self.assertEqual(7, restored["weekly_achievement"]["total_points"])
                self.assertEqual(403, request("/api/chores", "POST", payload, new_token, parent)[0])
            finally:
                stop()


if __name__ == "__main__":
    unittest.main()
