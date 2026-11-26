"""``masked_in_logs``: the values of the secrets a node uses are masked in every log line while it runs."""

from __future__ import annotations

import io
import logging
from collections.abc import Iterator
from threading import Thread

import pytest

from openartifact.logging_config import _masked_values, _SensitiveFilter, masked_in_logs

logger = logging.getLogger("openartifact.test_masking")


class _Log:
    """The lines the application's filter let through on a private logger."""

    def __init__(self) -> None:
        self.stream = io.StringIO()
        self.handler = logging.StreamHandler(self.stream)
        self.handler.addFilter(_SensitiveFilter())
        self.handler.setFormatter(logging.Formatter("%(message)s"))

    def write(self, message: str, *args: object) -> str:
        logger.info(message, *args)
        return self.read()

    def read(self) -> str:
        text = self.stream.getvalue()
        self.stream.seek(0)
        self.stream.truncate()
        return text


@pytest.fixture
def log() -> Iterator[_Log]:
    holder = _Log()
    logger.addHandler(holder.handler)
    logger.setLevel(logging.INFO)
    logger.propagate = False
    yield holder
    logger.removeHandler(holder.handler)
    logger.propagate = True


def test_a_registered_value_is_masked_in_the_message_and_its_arguments(log: _Log) -> None:
    with masked_in_logs(["s3cr3t"]):
        assert log.write("call with s3cr3t and %s", "s3cr3t") == "call with *** and ***\n"
    assert (
        log.write("call with s3cr3t") == "call with s3cr3t\n"
    )  # after the block: an ordinary word


def test_short_values_count_inside_the_block(log: _Log) -> None:
    with masked_in_logs(["x1"]):
        assert log.write("value x1") == "value ***\n"


def test_the_encoded_forms_are_masked_too(log: _Log) -> None:
    with masked_in_logs(["a b&c"]):
        assert log.write("q=%s b64=%s", "a%20b%26c", "YSBiJmM=") == "q=*** b64=***\n"


def test_a_value_stays_masked_until_the_outer_block_ends(log: _Log) -> None:
    with masked_in_logs(["token-x"]):
        with masked_in_logs(["token-x"]):
            assert log.write("inner token-x") == "inner ***\n"
        assert log.write("after the inner block token-x") == "after the inner block ***\n"
    assert log.write("after the outer block token-x") == "after the outer block token-x\n"
    assert "token-x" not in _masked_values


def test_two_overlapping_blocks_of_different_values_end_independently(log: _Log) -> None:
    first, second = masked_in_logs(["one-value"]), masked_in_logs(["two-value"])
    first.__enter__()
    second.__enter__()
    first.__exit__(None, None, None)
    assert log.write("one-value two-value") == "one-value ***\n"
    second.__exit__(None, None, None)
    assert log.write("one-value two-value") == "one-value two-value\n"


def test_the_value_is_released_when_the_block_raises(log: _Log) -> None:
    with pytest.raises(RuntimeError), masked_in_logs(["boom-value"]):
        raise RuntimeError("boom")
    assert log.write("boom-value") == "boom-value\n"
    assert not _masked_values


def test_a_traceback_with_the_value_is_masked(log: _Log) -> None:
    with masked_in_logs(["hidden-value"]):
        try:
            raise ValueError("failed for hidden-value")
        except ValueError:
            logger.exception("it broke")
    out = log.read()
    assert "hidden-value" not in out
    assert "ValueError: failed for ***" in out


def test_other_threads_log_masked_while_the_block_runs(log: _Log) -> None:
    with masked_in_logs(["thread-value"]):
        worker = Thread(target=lambda: logger.info("from a thread thread-value"))
        worker.start()
        worker.join()
        assert log.read() == "from a thread ***\n"
