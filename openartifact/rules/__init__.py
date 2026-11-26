"""One rule system (ADR-052, generalised by ADR-060): a rule is a *trigger*, a *condition tree* and a *consequence*.

``tree`` holds the condition tree (groups of conditions, the bounds) and the in-memory evaluator over a mapping of
facts; ``catalog`` holds the schemas: per purpose (retention of executions, guards, the planned lane rules) the
fields a condition may test, their operators and value kinds, and the consequences. The SQL compiler of the
retention rules stays in ``engine/retention.py``: one tree format, two evaluators.
"""
