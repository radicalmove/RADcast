from pathlib import Path

import pytest

from radcast.services.caption_artifacts import (
    CueEdit,
    absolute_cue_times,
    apply_cue_edit,
    load_vtt_cues,
    save_vtt_cues,
)


def test_parse_vtt_cues_and_apply_text_and_timing_edit_round_trips_cleanly(tmp_path: Path):
    caption_path = tmp_path / "sample.vtt"
    caption_path.write_text(
        "WEBVTT\n\n1\n00:00:01.000 --> 00:00:02.500\nAitikanga Māori space\n\n2\n00:00:03.000 --> 00:00:04.500\nCorresponding transcription\n",
        encoding="utf-8",
    )

    cues = load_vtt_cues(caption_path)
    assert len(cues) == 2
    assert cues[0].text == "Aitikanga Māori space"

    updated = apply_cue_edit(
        cues,
        CueEdit(
            cue_index=0,
            text="tikanga Māori space",
            start_seconds=1.1,
            end_seconds=2.6,
        ),
    )
    save_vtt_cues(caption_path, updated)

    output = caption_path.read_text(encoding="utf-8")
    assert "tikanga Māori space" in output
    assert "00:00:01.100 --> 00:00:02.600" in output
    assert "Corresponding transcription" in output


def test_absolute_cue_times_include_trim_offset():
    assert absolute_cue_times(cue_start_seconds=2.4, cue_end_seconds=4.1, clip_start_seconds=10.0) == pytest.approx((12.4, 14.1))
