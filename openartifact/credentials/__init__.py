"""The credential store (ADR-024): named secrets, encrypted at rest, used by name.

``crypto`` encrypts and decrypts a value, ``store`` keeps the encrypted values and hands them to the
executors only, ``refs`` is the syntax ``${secret:NAME}`` and the masking of values in results.
"""
