import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))

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


if __name__ == "__main__":
    unittest.main()
