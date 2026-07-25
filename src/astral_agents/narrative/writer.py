from __future__ import annotations

from astral_agents.domain.models import CanonicalEvent, NarrativeEpisode, ScenarioBundle


class TemplateNarrativeWriter:
    """A safe offline writer that cannot invent state outside the event log."""

    def write(
        self,
        run_id: str,
        start_round: int,
        end_round: int,
        events: list[CanonicalEvent],
        bundle: ScenarioBundle,
    ) -> NarrativeEpisode:
        relevant = [
            event
            for event in events
            if start_round <= event.round_no <= end_round
            and event.public_summary
            and event.event_type not in {"character_waited"}
        ]
        if not relevant:
            relevant = [
                event
                for event in events
                if start_round <= event.round_no <= end_round and event.public_summary
            ]

        titles = {
            1: "静默登舰",
            2: "互斥的时间",
            3: "回声的形状",
            4: "单向航线",
        }
        sequence = (start_round - 1) // bundle.scenario.episode_interval + 1
        title = titles.get(sequence, f"第 {sequence} 次校准")
        paragraphs: list[str] = []
        by_round: dict[int, list[CanonicalEvent]] = {}
        for event in relevant:
            by_round.setdefault(event.round_no, []).append(event)
        for round_no, round_events in sorted(by_round.items()):
            sentences = [
                f"{event.public_summary}〔{event.id}〕"
                for event in round_events
                if event.public_summary
            ]
            if sentences:
                paragraphs.append(f"第 {round_no} 轮，" + " ".join(sentences))
        body = "\n\n".join(paragraphs) or "这一段时间里，团队保持观察，没有确认新的事实。"
        event_ids = [event.id for event in relevant]
        return NarrativeEpisode(
            id=f"EP-{start_round:03d}-{end_round:03d}",
            title=title,
            start_round=start_round,
            end_round=end_round,
            point_of_view="已确认事件视角",
            event_ids=event_ids,
            body=body,
            generated_by="template",
            inferred_facts=[],
            validation_passed=all(event_id in {event.id for event in events} for event_id in event_ids),
        )

