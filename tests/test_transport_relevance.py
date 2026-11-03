import os
import sys
import unittest
from datetime import datetime, timezone
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
os.environ.setdefault(
    "FAMILYBOT_FAMILY_CONFIG",
    os.path.join(os.path.dirname(__file__), "fixtures", "family.test.json"),
)

import tbane_monitor
from transport_relevance import classify_for_corridor, notice_relevant, parse_siri_disruptions

CORRIDOR = [
    "Hovseter", "Holmen", "Makrellbekken", "Smestad", "Borgen",
    "Majorstuen", "Nationaltheatret", "Stortinget", "Jernbanetorget",
]


def disruption(summary, *, lines=("2",), stop_names=(), stop_refs=()):
    return {
        "summary": summary,
        "lines": list(lines),
        "stop_names": list(stop_names),
        "stop_refs": list(stop_refs),
        "key": summary,
    }


class TransportRelevanceTests(unittest.TestCase):
    def test_station_notice_outside_corridor_is_removed(self):
        item = disruption(
            "Heisen på Lindeberg T-banestasjon er ute av drift",
            stop_names=("Lindeberg T",),
        )
        self.assertFalse(notice_relevant(item, CORRIDOR))

    def test_station_notice_inside_corridor_is_retained(self):
        item = disruption(
            "Heisen på Hovseter T-banestasjon er ute av drift",
            stop_names=("Hovseter T",),
        )
        self.assertTrue(notice_relevant(item, CORRIDOR))

    def test_line_wide_notice_without_stop_scope_is_retained(self):
        item = disruption("Linje 2 er innstilt mellom flere stasjoner")
        self.assertTrue(notice_relevant(item, CORRIDOR))

    def test_missing_corridor_config_preserves_line_only_compatibility(self):
        item = disruption("Heisen på Lindeberg er ute av drift", stop_names=("Lindeberg",))
        self.assertTrue(notice_relevant(item, []))

    def test_station_wording_without_structured_stops_uses_corridor_names(self):
        self.assertFalse(notice_relevant(disruption("Heisen på Lindeberg stasjon er ute av drift"), CORRIDOR))
        self.assertTrue(notice_relevant(disruption("Heisen på Majorstuen stasjon er ute av drift"), CORRIDOR))

    def test_station_scoped_system_notice_outside_corridor_is_not_system_wide(self):
        item = disruption("Heisen på Lindeberg er ute av drift", lines=("1", "2", "3", "4"), stop_names=("Lindeberg",))
        classified = classify_for_corridor([item], "2", CORRIDOR)
        self.assertEqual(classified, {"route": [], "system": []})

    def test_true_system_wide_notice_is_retained(self):
        item = disruption("Signalfeil gir driftsstans på T-banen", lines=("1", "2", "3", "4"))
        classified = classify_for_corridor([item], "2", CORRIDOR)
        self.assertEqual(classified["system"], [item])

    def test_siri_parser_keeps_affected_station_metadata(self):
        xml = """
        <Siri><PtSituationElement>
          <Summary lang="NO">Heisen på Lindeberg er ute av drift</Summary>
          <Affects><Networks><AffectedNetwork><AffectedLine><LineRef>RUT:Line:2</LineRef></AffectedLine></AffectedNetwork></Networks>
          <StopPoints><AffectedStopPoint><StopPointRef>NSR:Quay:123</StopPointRef><StopPointName>Lindeberg T</StopPointName></AffectedStopPoint></StopPoints></Affects>
        </PtSituationElement></Siri>
        """
        result = parse_siri_disruptions(xml, {"1", "2", "3", "4", "5"})
        self.assertEqual(result[0]["stop_names"], ["Lindeberg T"])
        self.assertEqual(result[0]["stop_refs"], ["NSR:Quay:123"])
        self.assertFalse(notice_relevant(result[0], CORRIDOR))


class SubwayAlertStateTests(unittest.TestCase):
    def test_cosmetic_notice_edits_share_alert_identity(self):
        original = "Signalfeil på linje 2 – noe forsinkelse."
        edited = "Signalfeil på linje 2: noe forsinkelse"
        self.assertTrue(tbane_monitor.summaries_similar(original, edited))

    def test_line_order_does_not_change_alert_fingerprint(self):
        first = disruption("Driftsstans", lines=("2", "1"))
        second = disruption("Driftsstans", lines=("1", "2"))
        self.assertEqual(tbane_monitor.alert_fingerprint(first), tbane_monitor.alert_fingerprint(second))

    def test_notified_variant_is_not_sent_again(self):
        observed = datetime(2026, 11, 3, 8, 0, tzinfo=timezone.utc)
        state = {
            "active_alerts": {},
            "notified_alerts": {
                "legacy": {"summary": "Signalfeil på linje 2 – noe forsinkelse.", "last_seen": "2026-11-03T07:00:00Z"}
            },
        }
        classified = {
            "line2": [disruption("Signalfeil på linje 2: noe forsinkelse")],
            "system": [],
        }

        updated, fired = tbane_monitor.reconcile_alerts(classified, state, observed)

        self.assertEqual(fired, [])
        self.assertEqual(len(updated["active_alerts"]), 1)
        self.assertEqual(len(updated["notified_alerts"]), 2)

    def test_failed_fetch_preserves_alert_cache(self):
        with (
            mock.patch.object(tbane_monitor, "fetch_disruptions", return_value=None),
            mock.patch.object(tbane_monitor, "load_state") as load_state,
            mock.patch.object(tbane_monitor, "save_state") as save_state,
            mock.patch.object(tbane_monitor, "send_telegram") as send_telegram,
        ):
            tbane_monitor.run()

        load_state.assert_not_called()
        save_state.assert_not_called()
        send_telegram.assert_not_called()


if __name__ == "__main__":
    unittest.main()
