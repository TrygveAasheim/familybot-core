from __future__ import annotations

import json
import os
import plistlib
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class LaunchAgentInstallTests(unittest.TestCase):
    def install(self, config: dict) -> tuple[Path, subprocess.CompletedProcess[str], tempfile.TemporaryDirectory[str]]:
        temporary = tempfile.TemporaryDirectory()
        root = Path(temporary.name)
        workspace = root / "workspace"
        launch_agents = root / "LaunchAgents"
        config_path = root / "family.json"
        config_path.write_text(json.dumps(config), encoding="utf-8")
        environment = os.environ.copy()
        environment.update({
            "FAMILYBOT_WORKSPACE": str(workspace),
            "FAMILYBOT_FAMILY_CONFIG": str(config_path),
            "FAMILYBOT_LAUNCH_AGENTS_DIR": str(launch_agents),
            "FAMILYBOT_PYTHON": sys.executable,
            "FAMILYBOT_OPENCLAW": "",
        })
        result = subprocess.run(
            ["bash", str(ROOT / "scripts/install_launchagents.sh")],
            capture_output=True,
            text=True,
            env=environment,
            check=False,
        )
        return launch_agents, result, temporary

    def test_dashboard_profile_installs_no_background_jobs(self):
        launch_agents, result, temporary = self.install({
            "profile": "dashboard",
            "members": [{"member_id": 1, "role": "parent", "name": "Test"}],
            "integrations": {},
        })
        self.addCleanup(temporary.cleanup)
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual([], list(launch_agents.glob("familybot.*.plist")))

    def test_agent_profile_installs_only_enabled_jobs_and_custom_schedule(self):
        launch_agents, result, temporary = self.install({
            "profile": "agent",
            "members": [{"member_id": 1, "role": "parent", "name": "Test"}],
            "integrations": {
                "email": {"enabled": True, "account": "test@example.invalid"},
                "spond": {"enabled": False},
                "transport": {"enabled": False},
            },
            "notifications": {
                "weekday_time": "07:15",
                "weekend_briefing": False,
                "weekly_summary": False,
            },
        })
        self.addCleanup(temporary.cleanup)
        self.assertEqual(0, result.returncode, result.stderr)
        labels = {path.stem for path in launch_agents.glob("familybot.*.plist")}
        self.assertEqual(
            {
                "familybot.briefing.weekday",
                "familybot.delivery",
                "familybot.email",
                "familybot.health",
                "familybot.status",
                "familybot.ukeplan",
            },
            labels,
        )
        weekday = plistlib.loads(
            (launch_agents / "familybot.briefing.weekday.plist").read_bytes()
        )
        self.assertEqual(
            [{"Weekday": day, "Hour": 7, "Minute": 15} for day in range(1, 6)],
            weekday["StartCalendarInterval"],
        )

    def test_core_deploy_installs_only_the_enabled_adapter_lock(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            workspace = root / "workspace"
            python_target = workspace / "runtime/core/.venv/bin/python"
            python_target.parent.mkdir(parents=True)
            python_target.symlink_to(sys.executable)
            config = json.loads((ROOT / "config/family.demo.json").read_text(encoding="utf-8"))
            config["profile"] = "connected"
            config["integrations"] = {
                "email": {"enabled": True, "account": "familybot-test"},
                "spond": {"enabled": False},
            }
            config_path = root / "family.json"
            config_path.write_text(json.dumps(config), encoding="utf-8")
            config_path.chmod(0o600)
            uv_log = root / "uv.log"
            fake_uv = root / "uv"
            fake_uv.write_text(
                "#!/bin/bash\nprintf '%s\\n' \"$*\" >> \"$FAMILYBOT_TEST_UV_LOG\"\n",
                encoding="utf-8",
            )
            fake_uv.chmod(0o700)
            branch = subprocess.run(
                ["git", "-C", str(ROOT), "branch", "--show-current"],
                check=True,
                capture_output=True,
                text=True,
            ).stdout.strip()
            environment = os.environ.copy()
            environment.update(
                {
                    "FAMILYBOT_WORKSPACE": str(workspace),
                    "FAMILYBOT_FAMILY_CONFIG": str(config_path),
                    "FAMILYBOT_LAUNCH_AGENTS_DIR": str(root / "LaunchAgents"),
                    "FAMILYBOT_PYTHON": sys.executable,
                    "FAMILYBOT_UV": str(fake_uv),
                    "FAMILYBOT_DEPLOY_BRANCH": branch,
                    "FAMILYBOT_TEST_UV_LOG": str(uv_log),
                }
            )
            result = subprocess.run(
                ["bash", str(ROOT / "scripts/deploy_core.sh")],
                capture_output=True,
                text=True,
                env=environment,
                check=False,
            )
            self.assertEqual(0, result.returncode, result.stderr)
            sync = uv_log.read_text(encoding="utf-8")
            self.assertIn("requirements-base.txt", sync)
            self.assertIn("requirements-email.txt", sync)
            self.assertNotIn("requirements-spond.txt", sync)


if __name__ == "__main__":
    unittest.main()
