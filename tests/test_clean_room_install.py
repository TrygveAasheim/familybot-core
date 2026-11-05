from __future__ import annotations

import importlib.util
import json
import os
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PORTAL = (
    ROOT.parent / "familybot-portal"
    if (ROOT.parent / "familybot-portal").is_dir()
    else ROOT / "familybot-portal"
)


class CleanRoomInstallTests(unittest.TestCase):
    def test_custom_household_size_seeds_every_child(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            workspace = root / "custom-household"
            config = json.loads((ROOT / "config/family.demo.json").read_text(encoding="utf-8"))
            config["members"] = [
                {"member_id": 1, "role": "parent", "name": "Nora Nordmann", "slug": "nora"}
            ] + [
                {
                    "member_id": member_id,
                    "role": "child",
                    "name": name,
                    "slug": name.split()[0].casefold(),
                    "avatar": avatar,
                    "grade": grade,
                    "school": "Nordvik skole (fiktiv)",
                    "default_reward": {
                        "title": "Velg familieaktivitet",
                        "emoji": "🎯",
                        "target_value": 30,
                        "goal_type": "points",
                        "unit_label": "poeng",
                    },
                }
                for member_id, name, avatar, grade in (
                    (2, "Mikkel Nordmann", "🦊", "4A"),
                    (3, "Ingrid Nordmann", "🦋", "2B"),
                    (4, "Selma Nordmann", "🐳", "1C"),
                )
            ]
            config_path = root / "family.json"
            config_path.write_text(json.dumps(config, ensure_ascii=False), encoding="utf-8")
            config_path.chmod(0o600)
            pin = root / "pin.txt"
            pin.write_text("482731\n", encoding="utf-8")
            pin.chmod(0o600)
            result = subprocess.run(
                [
                    sys.executable,
                    str(ROOT / "scripts/install_familybot.py"),
                    "--workspace",
                    str(workspace),
                    "--portal-repo",
                    str(PORTAL),
                    "--config-source",
                    str(config_path),
                    "--non-interactive",
                    "--no-deploy",
                    "--parent-pin-source",
                    str(pin),
                ],
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(0, result.returncode, result.stderr)
            with sqlite3.connect(workspace / "db/family.db") as connection:
                self.assertEqual(1, connection.execute(
                    "SELECT COUNT(*) FROM family_members WHERE role='parent'"
                ).fetchone()[0])
                self.assertEqual(3, connection.execute(
                    "SELECT COUNT(*) FROM family_members WHERE role='child'"
                ).fetchone()[0])
                self.assertEqual(9, connection.execute(
                    "SELECT COUNT(*) FROM family_chore_meta"
                ).fetchone()[0])
                self.assertEqual(3, connection.execute(
                    "SELECT COUNT(*) FROM reward_goals WHERE active=1"
                ).fetchone()[0])

    def test_invalid_configuration_stops_before_database_creation(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            workspace = root / "invalid-household"
            config = root / "invalid.json"
            config.write_text('{"schema_version": 1, "members": []}', encoding="utf-8")
            pin = root / "pin.txt"
            pin.write_text("482731\n", encoding="utf-8")
            result = subprocess.run(
                [
                    sys.executable,
                    str(ROOT / "scripts/install_familybot.py"),
                    "--workspace",
                    str(workspace),
                    "--portal-repo",
                    str(PORTAL),
                    "--config-source",
                    str(config),
                    "--non-interactive",
                    "--no-deploy",
                    "--parent-pin-source",
                    str(pin),
                ],
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertNotEqual(0, result.returncode)
            self.assertFalse((workspace / "db/family.db").exists())

    def test_existing_connected_profile_can_use_the_upgrade_entry_point(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            workspace = root / "existing-household"
            pin = root / "pin.txt"
            pin.write_text("482731\n", encoding="utf-8")
            pin.chmod(0o600)
            command = [
                sys.executable,
                str(ROOT / "scripts/install_familybot.py"),
                "--workspace",
                str(workspace),
                "--portal-repo",
                str(PORTAL),
                "--demo",
                "--non-interactive",
                "--no-deploy",
                "--parent-pin-source",
                str(pin),
            ]
            first = subprocess.run(command, capture_output=True, text=True, check=False)
            self.assertEqual(0, first.returncode, first.stderr)
            config_path = workspace / "config/family.local.json"
            config = json.loads(config_path.read_text(encoding="utf-8"))
            config["profile"] = "connected"
            config_path.write_text(json.dumps(config, ensure_ascii=False), encoding="utf-8")
            config_path.chmod(0o600)

            upgraded = subprocess.run(command, capture_output=True, text=True, check=False)

            self.assertEqual(0, upgraded.returncode, upgraded.stderr)
            self.assertIn("existing capability profile", upgraded.stdout)
            with sqlite3.connect(workspace / "db/family.db") as connection:
                self.assertEqual(
                    {"core": 1, "portal": 2},
                    dict(connection.execute(
                        "SELECT component,MAX(version) FROM familybot_schema_migrations GROUP BY component"
                    )),
                )

    def test_empty_dashboard_install_is_idempotent_and_supports_chore_approval(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            workspace = root / "new-household"
            pin_source = root / "pin.txt"
            pin_source.write_text("482731\n", encoding="utf-8")
            pin_source.chmod(0o600)
            command = [
                sys.executable,
                str(ROOT / "scripts/install_familybot.py"),
                "--workspace",
                str(workspace),
                "--portal-repo",
                str(PORTAL),
                "--demo",
                "--non-interactive",
                "--no-deploy",
                "--parent-pin-source",
                str(pin_source),
            ]
            environment = os.environ.copy()
            first = subprocess.run(command, capture_output=True, text=True, env=environment, check=False)
            self.assertEqual(0, first.returncode, first.stderr)
            second = subprocess.run(command, capture_output=True, text=True, env=environment, check=False)
            self.assertEqual(0, second.returncode, second.stderr)

            database = workspace / "db/family.db"
            self.assertEqual(0o600, database.stat().st_mode & 0o777)
            self.assertEqual(0o600, (workspace / "config/family.local.json").stat().st_mode & 0o777)
            self.assertEqual(0o600, (workspace / "config/parent-pin.txt").stat().st_mode & 0o777)
            with sqlite3.connect(database) as connection:
                versions = dict(
                    connection.execute(
                        "SELECT component,MAX(version) FROM familybot_schema_migrations GROUP BY component"
                    )
                )
                self.assertEqual({"core": 1, "portal": 2}, versions)
                self.assertEqual(4, connection.execute("SELECT COUNT(*) FROM family_members").fetchone()[0])
                self.assertEqual(6, connection.execute("SELECT COUNT(*) FROM family_chore_meta").fetchone()[0])

            saved_family_config = sys.modules.pop("family_config", None)
            saved_config_path = os.environ.get("FAMILYBOT_FAMILY_CONFIG")
            os.environ["FAMILYBOT_FAMILY_CONFIG"] = str(
                workspace / "config/family.local.json"
            )
            sys.path.insert(0, str(PORTAL / "local_api"))
            try:
                spec = importlib.util.spec_from_file_location(
                    "clean_room_familybot_api", PORTAL / "local_api/familybot_api.py"
                )
                assert spec and spec.loader
                api = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(api)
            finally:
                sys.path.pop(0)
                if saved_family_config is not None:
                    sys.modules["family_config"] = saved_family_config
                else:
                    sys.modules.pop("family_config", None)
                if saved_config_path is None:
                    os.environ.pop("FAMILYBOT_FAMILY_CONFIG", None)
                else:
                    os.environ["FAMILYBOT_FAMILY_CONFIG"] = saved_config_path
            repository = api.FamilyRepository(
                database,
                workspace=workspace,
                audit_path=workspace / "logs/audit.jsonl",
            )
            chore = repository.create_child_chore(
                {
                    "title": "Van plantene",
                    "assigned_to": "mikkel nordmann",
                    "icon": "🌱",
                    "points": 4,
                    "requires_approval": True,
                    "repeat_mode": "once",
                }
            )
            completion = repository.complete_chore(
                chore["id"],
                {"member_id": 3, "idempotency_key": "clean-room-completion-0001"},
            )
            self.assertEqual("pending", completion["status"])
            decided = repository.decide_completion(completion["id"], {"decision": "awarded"}, 1)
            self.assertEqual("awarded", decided["status"])

            restarted = api.FamilyRepository(
                database,
                workspace=workspace,
                audit_path=workspace / "logs/audit-after-restart.jsonl",
            )
            active_config_path = os.environ.get("FAMILYBOT_FAMILY_CONFIG")
            os.environ["FAMILYBOT_FAMILY_CONFIG"] = str(
                workspace / "config/family.local.json"
            )
            try:
                dashboard = restarted.dashboard()
            finally:
                if active_config_path is None:
                    os.environ.pop("FAMILYBOT_FAMILY_CONFIG", None)
                else:
                    os.environ["FAMILYBOT_FAMILY_CONFIG"] = active_config_path
            child = next(item for item in dashboard["children"] if item["id"] == 3)
            self.assertGreaterEqual(child["weekly_achievement"]["total_points"], 4)
            self.assertFalse(dashboard["transport"]["ok"])
            self.assertIn("utilgjengelig", dashboard["weather"]["status"])


if __name__ == "__main__":
    unittest.main()
