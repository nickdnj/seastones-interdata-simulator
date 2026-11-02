"""sxscore: the seastones.score/1 format (ADR-004, ARCHITECTURE 9.3, docs/score-format.md).

RS-03 provides the parser and canonical emitter (``score``) and the validator
(``validate``; CLI ``python -m toolchain.sxscore.validate``). The compiler to 3-halfword
table records is VS-20.
"""

from .score import FORMAT_NAME, Event, Problem, Score, Value, emit, parse

__all__ = ["FORMAT_NAME", "Event", "Problem", "Score", "Value", "emit", "parse"]
