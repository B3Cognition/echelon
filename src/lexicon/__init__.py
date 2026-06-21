"""Lexicon — a controlled specification language and deterministic validator.

Lexicon authoring is non-deterministic (an LLM writes it); Lexicon *validation*
is deterministic. The validator parses the grammar (P), resolves every term
against a governed glossary (T), and hard-gates on slot completeness,
determinism, observability, and example coverage. A soft quality score never
acts as the accept/reject gate — it only orders repairs.

The grammar implemented here is the template-level controlled language from the
"Deterministic Grammar Driven Authoring" design: an ``ARTIFACT:`` header plus
colon-keyword blocks (REQ / AC / ERROR / RULE / INPUT / CLAIM / EVIDENCE /
LIMIT / TBR).
"""

__version__ = "0.1.0"
