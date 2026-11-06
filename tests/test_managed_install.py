"""Actual managed installation: disposable GitHub-hosted macOS runner only."""
from __future__ import annotations

import http.client
import json
import os
import sqlite3
import subprocess
import sys
import tempfile
import time
import unittest
import uuid
from pathlib import Path

from tests.test_install_readiness import PORTAL, ROOT, available_port, installer


@unittest.skipUnless(
    os.environ.get("FAMILYBOT_MANAGED_CI") == "1",
    "Managed deployment runs only on an explicitly opted-in disposable GitHub-hosted macOS runner",
)
class ManagedInstallTests(unittest.TestCase):
    def test_full_install_and_supervisor_restart(self):
        self.assertEqual("darwin", sys.platform, "Managed test requires macOS")
        self.assertEqual("true", os.environ.get("GITHUB_ACTIONS"), "Never deploy on a local review host")
        self.assertEqual("github-hosted", os.environ.get("RUNNER_ENVIRONMENT"), "Requires disposable hosted runner")
        with tempfile.TemporaryDirectory(prefix="familybot-managed-") as directory:
            root = Path(directory)
            workspace = root / "household"
            config = json.loads((ROOT / "config/family.demo.json").read_text())
            config["portal"]["web_port"] = available_port()
            config["portal"]["api_port"] = available_port()
            while config["portal"]["api_port"] == config["portal"]["web_port"]:
                config["portal"]["api_port"] = available_port()
            web_port = config["portal"]["web_port"]
            config["portal"]["allowed_origins"] = [f"http://localhost:{web_port}", f"http://127.0.0.1:{web_port}"]
            # Hosted runners do not provide a household LAN/mDNS resolver.
            # Exercise the real installer with its supported explicit-host config;
            # never weaken production hostname verification to make CI green.
            installer.set_new_hostname(config, "localhost")
            print("Managed CI uses explicit localhost; physical LAN/mDNS/iPad are NOT tested.", flush=True)
            source = root / "family.json"
            source.write_text(json.dumps(config))
            source.chmod(0o600)
            pin = root / "pin"
            pin.write_text("482731\n")
            pin.chmod(0o600)
            label = "ai.familybot.ci." + uuid.uuid4().hex
            environment = {k: v for k, v in os.environ.items()
                           if not k.startswith("FAMILYBOT_") and k != "OPENCLAW_WORKSPACE"}
            environment.update({"FAMILYBOT_PORTAL_LABEL": label,
                                "FAMILYBOT_LAUNCHAGENT_DIR": str(root / "LaunchAgents")})
            command = [sys.executable, str(ROOT / "scripts/install_familybot.py"),
                       "--portal-repo", str(PORTAL), "--workspace", str(workspace),
                       "--config-source", str(source), "--parent-pin-source", str(pin), "--non-interactive"]
            domain = f"gui/{os.getuid()}"
            # A missing GUI domain fails this CI gate; it must not masquerade as a passed deployment.
            subprocess.run(["launchctl", "print", domain], stdout=subprocess.DEVNULL, check=True)
            try:
                subprocess.run(command, env=environment, check=True, timeout=900)
                self.assertTrue((root / "LaunchAgents" / f"{label}.plist").is_file())
                settings = config["portal"]
                installer.verify_local_service(settings["api_port"], settings["web_port"], settings["hostname"])
                original = installer.service_probe(settings["hostname"], settings["api_port"], settings["web_port"])
                subprocess.run(["launchctl", "kickstart", "-k", f"{domain}/{label}"], check=True)
                installer.verify_local_service(settings["api_port"], settings["web_port"], settings["hostname"])
                for _ in range(30):
                    current = installer.service_probe(settings["hostname"], settings["api_port"], settings["web_port"])
                    if current != original:
                        break
                    time.sleep(1)
                self.assertNotEqual(original, current, "Managed restart must rotate the API session")
                connection = http.client.HTTPConnection(settings["hostname"], settings["api_port"], timeout=5)
                try:
                    connection.request("GET", "/api/dashboard", headers={
                        "Origin": f"http://{settings['hostname']}:{settings['web_port']}",
                        "X-FamilyBot-Local-Token": original,
                    })
                    self.assertEqual(403, connection.getresponse().status)
                finally:
                    connection.close()
                # Existing-household upgrade, with the fixture's only writer
                # stopped. Never run this managed path on a household host.
                subprocess.run(["launchctl", "bootout", f"{domain}/{label}"], check=True)
                database = workspace / "db/family.db"
                with sqlite3.connect(database) as db:
                    db.execute("UPDATE kanban_cards SET archived_at='2026-11-01'")
                    db.execute("UPDATE reward_goals SET active=0")
                    before = db.execute("SELECT COUNT(*) FROM kanban_cards").fetchone()[0]
                subprocess.run(command + ["--upgrade", "--writers-stopped", "--portal-runtime",
                                          str(workspace / "runtime/familybot-portal")],
                               env=environment, check=True, timeout=900)
                with sqlite3.connect(database) as db:
                    self.assertEqual(before, db.execute("SELECT COUNT(*) FROM kanban_cards").fetchone()[0])
                    self.assertEqual(0, db.execute("SELECT COUNT(*) FROM kanban_cards WHERE archived_at IS NULL").fetchone()[0])
                    self.assertEqual(0, db.execute("SELECT COUNT(*) FROM reward_goals WHERE active=1").fetchone()[0])
                self.assertTrue(list((workspace / "backups").glob("pre-upgrade-*/family.db")))
                installer.verify_local_service(settings["api_port"], settings["web_port"], settings["hostname"])
                subprocess.run([sys.executable, str(PORTAL / "tests/acceptance.py"),
                                "--workspace", str(workspace), "--host", settings["hostname"]], check=True)
            except (subprocess.SubprocessError, installer.InstallError, AssertionError, OSError):
                # Only reached behind the disposable hosted-runner guard. These
                # are this fixture's generated logs; no real household is present.
                for name in ("familybot-portal.log", "familybot-portal.error.log"):
                    log = Path.home() / "Library/Logs" / name
                    if log.is_file():
                        print(f"Managed fictional fixture diagnostic: {name}", flush=True)
                        print(log.read_text(errors="replace")[-12000:], flush=True)
                raise
            finally:
                for owned in (label, label + "-images"):
                    subprocess.run(["launchctl", "bootout", f"{domain}/{owned}"],
                                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)


if __name__ == "__main__":
    unittest.main()
