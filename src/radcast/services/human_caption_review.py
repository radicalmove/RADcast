"""Persistence for human caption review decisions."""

from __future__ import annotations

import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from radcast.models import HumanCaptionReviewDecision, HumanCaptionReviewDecisionType
from radcast.services.caption_artifacts import absolute_cue_times


class HumanCaptionReviewStore:
    """Persist manual caption approvals and corrections per source-audio lineage."""

    _MATCH_TOLERANCE_SECONDS = 0.5

    def __init__(self, manifest_path: Path):
        self.manifest_path = Path(manifest_path)
        self.manifest_path.parent.mkdir(parents=True, exist_ok=True)
        if not self.manifest_path.exists():
            self._write([])

    def list_decisions(self) -> list[HumanCaptionReviewDecision]:
        return [HumanCaptionReviewDecision.model_validate(item) for item in self._read()]

    def save_approval(
        self,
        *,
        source_audio_hash: str,
        absolute_start_seconds: float,
        absolute_end_seconds: float,
        reason_category: str,
        original_text: str,
    ) -> HumanCaptionReviewDecision:
        return self._save_decision(
            HumanCaptionReviewDecision(
                id=str(uuid4()),
                source_audio_hash=source_audio_hash,
                absolute_start_seconds=absolute_start_seconds,
                absolute_end_seconds=absolute_end_seconds,
                decision_type=HumanCaptionReviewDecisionType.APPROVED,
                reason_category=reason_category,
                original_text=original_text,
            )
        )

    def save_correction(
        self,
        *,
        source_audio_hash: str,
        absolute_start_seconds: float,
        absolute_end_seconds: float,
        reason_category: str,
        original_text: str,
        corrected_text: str,
        corrected_start_seconds: float,
        corrected_end_seconds: float,
    ) -> HumanCaptionReviewDecision:
        return self._save_decision(
            HumanCaptionReviewDecision(
                id=str(uuid4()),
                source_audio_hash=source_audio_hash,
                absolute_start_seconds=absolute_start_seconds,
                absolute_end_seconds=absolute_end_seconds,
                decision_type=HumanCaptionReviewDecisionType.CORRECTED,
                reason_category=reason_category,
                original_text=original_text,
                corrected_text=corrected_text,
                corrected_start_seconds=corrected_start_seconds,
                corrected_end_seconds=corrected_end_seconds,
            )
        )

    def match_decisions(
        self,
        *,
        source_audio_hash: str,
        cue_start_seconds: float,
        cue_end_seconds: float,
        clip_start_seconds: float | None = None,
    ) -> list[HumanCaptionReviewDecision]:
        absolute_start_seconds, absolute_end_seconds = absolute_cue_times(
            cue_start_seconds=cue_start_seconds,
            cue_end_seconds=cue_end_seconds,
            clip_start_seconds=clip_start_seconds,
        )
        matched: list[HumanCaptionReviewDecision] = []
        for decision in self.list_decisions():
            if decision.source_audio_hash != source_audio_hash:
                continue
            if not self._times_match(
                expected_start=decision.absolute_start_seconds,
                expected_end=decision.absolute_end_seconds,
                actual_start=absolute_start_seconds,
                actual_end=absolute_end_seconds,
            ):
                continue
            matched.append(decision)
        return matched

    def _save_decision(self, new_decision: HumanCaptionReviewDecision) -> HumanCaptionReviewDecision:
        existing = self.list_decisions()
        replaced = False
        for idx, decision in enumerate(existing):
            if self._same_slot(decision, new_decision):
                payload = new_decision.model_copy(update={"id": decision.id, "created_at": decision.created_at})
                payload.updated_at = datetime.now(timezone.utc)
                existing[idx] = payload
                replaced = True
                break
        if not replaced:
            existing.append(new_decision)
        self._write([item.model_dump(mode="json") for item in existing])
        return new_decision

    def _same_slot(
        self, existing: HumanCaptionReviewDecision, new_decision: HumanCaptionReviewDecision
    ) -> bool:
        if existing.source_audio_hash != new_decision.source_audio_hash:
            return False
        if existing.reason_category != new_decision.reason_category:
            return False
        if existing.original_text != new_decision.original_text:
            return False
        return self._times_match(
            expected_start=existing.absolute_start_seconds,
            expected_end=existing.absolute_end_seconds,
            actual_start=new_decision.absolute_start_seconds,
            actual_end=new_decision.absolute_end_seconds,
        )

    @classmethod
    def _times_match(
        cls,
        *,
        expected_start: float,
        expected_end: float,
        actual_start: float,
        actual_end: float,
    ) -> bool:
        return (
            abs(expected_start - actual_start) <= cls._MATCH_TOLERANCE_SECONDS
            and abs(expected_end - actual_end) <= cls._MATCH_TOLERANCE_SECONDS
        )

    def _read(self) -> list[dict[str, object]]:
        try:
            payload = json.loads(self.manifest_path.read_text(encoding="utf-8"))
        except (FileNotFoundError, json.JSONDecodeError):
            return []
        if not isinstance(payload, list):
            return []
        return [item for item in payload if isinstance(item, dict)]

    def _write(self, payload: list[dict[str, object]]) -> None:
        fd, temp_name = tempfile.mkstemp(
            prefix=f"{self.manifest_path.name}.",
            suffix=".tmp",
            dir=self.manifest_path.parent,
        )
        temp_path = Path(temp_name)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(payload, handle, indent=2, default=str)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temp_path, self.manifest_path)
        except Exception:
            try:
                temp_path.unlink(missing_ok=True)
            finally:
                raise
