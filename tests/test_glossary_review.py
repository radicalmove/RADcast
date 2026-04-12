from __future__ import annotations

from pathlib import Path

from radcast.services.glossary_review import extract_glossary_review_candidates


def test_extract_glossary_candidates_returns_context_and_deduped_terms(tmp_path: Path) -> None:
    fixture_dir = Path(__file__).resolve().parent / "fixtures" / "glossary_review"
    caption_path = tmp_path / "simple.vtt"
    review_path = tmp_path / "simple.vtt.review.txt"
    caption_path.write_text((fixture_dir / "simple.vtt").read_text(encoding="utf-8"), encoding="utf-8")
    review_path.write_text((fixture_dir / "simple.vtt.review.txt").read_text(encoding="utf-8"), encoding="utf-8")

    candidates = extract_glossary_review_candidates(
        caption_path=caption_path,
        review_path=review_path,
        active_terms=["tikanga"],
    )

    assert [candidate.normalized_term for candidate in candidates] == ["tikanga", "transgression"]
    assert [candidate.term for candidate in candidates] == ["tikanga", "transgression"]
    assert [candidate.reason for candidate in candidates] == [
        "probable critical term miss: tikanga",
        "probable critical term miss: transgression",
    ]
    assert candidates[0].previous_context == "Welcome everyone"
    assert candidates[0].flagged_context == "Aitikanga Māori space"
    assert candidates[0].next_context == "And then we discuss transgression"
    assert candidates[0].already_known is True
    assert candidates[1].already_known is False
