"""Source wrapper tests: fictional jobs, private locks, no launchd/provider calls."""
from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class SchedulerPathTests(unittest.TestCase):
    def test_all_dispatches_support_spaced_interpreter_and_workspace(self):
        with tempfile.TemporaryDirectory(prefix="familybot-scheduler-") as directory:
            workspace = Path(directory) / "Ny familie Ø"
            for relative in ("logs", "scripts", "test-locks", "runtime/core/.venv/bin"):
                (workspace / relative).mkdir(parents=True)
            python = workspace / "runtime/core/.venv/bin/python"
            python.symlink_to(sys.executable)
            runner = (ROOT / "scripts/cron_runner.sh").read_text()
            # Only relocate lock storage in this source copy: never acquire,
            # inspect or remove the existing installation's /tmp task locks.
            original = 'LOCK_DIR="/tmp/familybot_${task}.lock"'
            self.assertEqual(1, runner.count(original))
            runner = runner.replace(original, 'LOCK_DIR="$WORKSPACE/test-locks/${task}.lock"')
            fixture = "import pathlib, sys\nprint(pathlib.Path(__file__).name, *sys.argv[1:])\n"
            expected = {
                "email": "process_emails.py", "spond": "spond_sync.py", "tbane": "tbane_monitor.py",
                "health": "healthcheck.py", "status": "update_status.py",
                "briefing-daily": "briefing.py daily", "briefing-weekly": "briefing.py weekly",
                "delivery": "flush_outbox.py", "ukeplan-interpret": "interpret_ukeplan.py --limit 1",
            }
            for name in {v.split()[0] for v in expected.values()} | {"job_state.py", "sre_reconcile.py"}:
                (workspace / "scripts" / name).write_text(fixture)
            environment = {k: v for k, v in os.environ.items()
                           if not k.startswith("FAMILYBOT_") and k != "OPENCLAW_WORKSPACE"}
            environment["FAMILYBOT_WORKSPACE"] = str(workspace)
            for task, output in expected.items():
                with self.subTest(task=task):
                    result = subprocess.run(["bash", "-c", runner, "fixture-runner", task],
                                            env=environment, capture_output=True, text=True, timeout=10)
                    self.assertEqual(0, result.returncode, result.stderr)
                    self.assertIn(output, (workspace / "logs/cron.log").read_text())
                    self.assertFalse(list((workspace / "test-locks").iterdir()))
            self.assertIn("sre_reconcile.py", (workspace / "logs/cron.log").read_text())
            (workspace / "scripts/process_emails.py").write_text("raise SystemExit(7)\n")
            result = subprocess.run(["bash", "-c", runner, "fixture-runner", "email"],
                                    env=environment, capture_output=True, timeout=10)
            self.assertEqual(7, result.returncode)
            self.assertFalse(list((workspace / "test-locks").iterdir()))

    def test_documented_recovery_ref_works_detached_and_on_branch(self):
        command = 'git symbolic-ref --quiet --short HEAD || git rev-parse HEAD'
        self.assertIn(f'export FAMILYBOT_DEPLOY_BRANCH="$({command})"', (ROOT / "REDEPLOY.md").read_text())
        with tempfile.TemporaryDirectory(prefix="familybot-ref-") as directory:
            repo = Path(directory)
            def git(*args):
                return subprocess.run(["git", "-C", str(repo), *args], check=True,
                                      capture_output=True, text=True).stdout.strip()
            git("init", "-b", "fixture")
            git("-c", "user.name=Fixture", "-c", "user.email=fixture@example.invalid",
                "-c", "commit.gpgsign=false", "commit", "--allow-empty", "-m", "fictional source")
            sha = git("rev-parse", "HEAD")
            for detached, expected in ((False, "fixture"), (True, sha)):
                if detached:
                    git("switch", "--detach", sha)
                result = subprocess.run(["bash", "-c", command], cwd=repo,
                                        check=True, capture_output=True, text=True)
                self.assertEqual(expected, result.stdout.strip())
