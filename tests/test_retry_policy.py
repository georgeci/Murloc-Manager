from murloc.retry_policy import RetryPolicy


def test_retry_within_limit() -> None:
    p = RetryPolicy(max_attempts=3)
    assert p.should_retry(1) is True
    assert p.should_retry(2) is True
    assert p.should_retry(3) is False


def test_retry_zero_attempts() -> None:
    p = RetryPolicy(max_attempts=1)
    assert p.should_retry(1) is False
