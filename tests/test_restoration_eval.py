from __future__ import annotations

from pathlib import Path

from radcast.experiments.restoration_eval import parse_report_text, score_report_file


def test_parse_and_score_report(tmp_path: Path) -> None:
    report = tmp_path / "report.txt"
    report.write_text(
        "\n".join(
            [
                "original",
                "  duration_s: 5.0",
                "  rms_db: -18.0",
                "  centroid_hz: 2000.0",
                "  band_0_250_db: 30.0",
                "  band_250_700_db: 36.0",
                "  band_700_2000_db: 20.0",
                "  band_2000_4500_db: 6.0",
                "  band_4500_8000_db: 10.0",
                "",
                "restored",
                "  duration_s: 5.0",
                "  rms_db: -20.0",
                "  centroid_hz: 1700.0",
                "  band_0_250_db: 31.0",
                "  band_250_700_db: 37.0",
                "  band_700_2000_db: 19.0",
                "  band_2000_4500_db: 5.0",
                "  band_4500_8000_db: 9.5",
                "",
                "adobe",
                "  duration_s: 5.0",
                "  rms_db: -21.0",
                "  centroid_hz: 1750.0",
                "  band_0_250_db: 30.0",
                "  band_250_700_db: 36.5",
                "  band_700_2000_db: 18.5",
                "  band_2000_4500_db: 5.5",
                "  band_4500_8000_db: 9.0",
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    blocks = parse_report_text(report.read_text(encoding="utf-8"))
    assert blocks["restored"]["centroid_hz"] == 1700.0

    payload = score_report_file(report)
    assert "score" in payload
    assert payload["score"] > 0
    assert payload["diffs"]["band_0_250_db"] == 1.0
