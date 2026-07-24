#!/usr/bin/env python3
"""
blinding.py — deterministic, seeded A/B token assignment.

Every (case, model, repetition) triple gets a *blind* token map
`{"A": "baseline"|"candidate", "B": "<the other>"}`. The map is:

  - Deterministic: identical seed + identical inputs -> identical map, every
    time, on every machine (no reliance on Python's process-randomized
    `hash()` or `random.seed()` global state).
  - Reproducible: re-running `prepare.py` with the same experiment seed
    regenerates byte-identical packets.
  - "Random enough": which of A/B is baseline varies per (case, model, rep)
    based on a SHA-256 digest of the composite key, not a fixed rule like
    "A is always baseline" — so a grader or executor cannot infer the
    mapping from position alone.

Nothing in this module ever prints or returns which token is "real" without
the caller explicitly asking — packets and grader-facing artifacts should be
built from the TOKEN side of the map only (see prepare.py / blind_review.py).
"""
from __future__ import annotations

import hashlib
from typing import Dict

VARIANT_NAMES = ("baseline", "candidate")
TOKENS = ("A", "B")


def _composite_key(seed: int, experiment_id: str, case_id: str, model_label: str, repetition: int) -> str:
    return f"{seed}|{experiment_id}|{case_id}|{model_label}|{repetition}"


def token_bit(seed: int, experiment_id: str, case_id: str, model_label: str, repetition: int) -> int:
    """Return a deterministic 0/1 bit derived from a SHA-256 digest of the composite key."""
    key = _composite_key(seed, experiment_id, case_id, model_label, repetition)
    digest = hashlib.sha256(key.encode("utf-8")).hexdigest()
    return int(digest[:2], 16) % 2


def assign_token_map(
    seed: int,
    experiment_id: str,
    case_id: str,
    model_label: str,
    repetition: int,
) -> Dict[str, str]:
    """Return the deterministic blind token map for one (case, model, repetition).

    Returns e.g. {"A": "candidate", "B": "baseline"} — never both keys the
    same variant, and stable for identical inputs.
    """
    bit = token_bit(seed, experiment_id, case_id, model_label, repetition)
    if bit == 0:
        return {"A": VARIANT_NAMES[0], "B": VARIANT_NAMES[1]}
    return {"A": VARIANT_NAMES[1], "B": VARIANT_NAMES[0]}


def token_for_variant(token_map: Dict[str, str], variant: str) -> str:
    """Inverse lookup: given a token map and a real variant name, return its blind token."""
    for token, name in token_map.items():
        if name == variant:
            return token
    raise KeyError(f"variant {variant!r} not present in token map {token_map!r}")


def variant_for_token(token_map: Dict[str, str], token: str) -> str:
    """Given a token map and a blind token ('A'/'B'), return the real variant name."""
    try:
        return token_map[token]
    except KeyError as exc:
        raise KeyError(f"token {token!r} not present in token map {token_map!r}") from exc
