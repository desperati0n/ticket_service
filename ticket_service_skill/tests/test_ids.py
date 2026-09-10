from ticket_mcp.ids import Snowflake


def test_snowflake_generates_unique_positive_integer_ids():
    generator = Snowflake(worker_id=7)

    first = generator.next_id()
    second = generator.next_id()

    assert isinstance(first, int)
    assert first > 0
    assert second > first


def test_snowflake_rejects_worker_id_outside_five_bits():
    for worker_id in (-1, 32):
        try:
            Snowflake(worker_id)
        except ValueError as exc:
            assert "between 0 and 31" in str(exc)
        else:
            raise AssertionError("invalid worker_id was accepted")
