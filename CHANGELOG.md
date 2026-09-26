# Changelog

## Porygon-Jev 0.2 — 2026-09-26

This release expands the structured context Jev receives for each legal action.

### New features

- Type matchup context: STAB, effectiveness multiplier, and labels for damaging moves.
- Per-battle short-term memory: the last three resolved action observations are sent with each decision. HP changes are described cautiously; unchanged HP does not assert immunity.
- Utility move context: self stat boosts, healing fraction, and primary inflicted status. The existing raw boosts field remains target dependent.
- Ability evidence: sorted move flags and `ignore_ability` accompany the opponent's revealed ability. The agent does not claim a general ability-block calculation.
- Request pacing: a minimum interval between Jev attempts, exponential backoff after rate limits, and support for `Retry-After`.
- JSONL telemetry retains the decision context, selected action, selection source, confidence, and option probabilities. The record schema is version 5 and the nested decision schema is version 4.

### Verification and limits

- 17 pytest checks pass, including intercepted Jev requests for utility fields and revealed or unknown ability cases.
- Jev's behavior against revealed Soundproof remains a live battle experiment. Move flags can be incomplete, and no full damage calculator or ability rule engine is included.
