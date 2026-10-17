import logging

import pytest
from click.testing import CliRunner
from sqlalchemy import create_engine, func, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

import dice
from dice import (
    Base,
    StorageError,
    Throw,
    cli,
    count_throws,
    format_stat,
    format_stats,
    roll_dice,
    save_throws,
)


@pytest.fixture
def session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as s:
        yield s


@pytest.fixture
def cli_env(tmp_path, monkeypatch):
    """Подменяет базу и лог-файл на временные."""
    db_file = tmp_path / "test.db"
    log_file = tmp_path / "test.log"
    monkeypatch.setenv("DICE_DB_URL", f"sqlite:///{db_file.as_posix()}")
    monkeypatch.setenv("DICE_LOG_FILE", str(log_file))
    return {"db": db_file, "log": log_file}


@pytest.fixture(autouse=True)
def close_log_handlers():
    yield
    logger = logging.getLogger("dice")
    for handler in list(logger.handlers):
        logger.removeHandler(handler)
        handler.close()


# --- roll_dice ---


def test_roll_dice_length_and_range():
    values = roll_dice(100, 6)
    assert len(values) == 100
    assert all(1 <= v <= 6 for v in values)


def test_roll_dice_minimal_values():
    values = roll_dice(1, 2)
    assert len(values) == 1
    assert values[0] in (1, 2)


@pytest.mark.parametrize("count", [0, -1])
def test_roll_dice_invalid_count(count):
    with pytest.raises(ValueError, match="--count"):
        roll_dice(count, 6)


@pytest.mark.parametrize("sides", [1, 0, -5])
def test_roll_dice_invalid_sides(sides):
    with pytest.raises(ValueError, match="--sides"):
        roll_dice(1, sides)


# --- save_throws / count_throws ---


def test_save_and_count(session):
    save_throws(session, 6, [1, 1, 2])
    save_throws(session, 20, [20])
    assert count_throws(session) == {6: {1: 2, 2: 1}, 20: {20: 1}}


def test_count_empty(session):
    assert count_throws(session) == {}


def test_save_empty_list(session):
    save_throws(session, 6, [])
    assert count_throws(session) == {}


def test_save_throws_rolls_back_on_error(session, monkeypatch):
    def broken_commit():
        raise SQLAlchemyError("boom")

    monkeypatch.setattr(session, "commit", broken_commit)
    with pytest.raises(StorageError):
        save_throws(session, 6, [1])
    total = session.execute(select(func.count()).select_from(Throw)).scalar()
    assert total == 0


def test_save_throws_without_table_raises_storage_error():
    engine = create_engine("sqlite:///:memory:")
    with Session(engine) as s:
        with pytest.raises(StorageError):
            save_throws(s, 6, [1])


def test_count_throws_without_table_raises_storage_error():
    engine = create_engine("sqlite:///:memory:")
    with Session(engine) as s:
        with pytest.raises(StorageError):
            count_throws(s)


# --- форматирование ---


def test_format_stat_abs():
    assert format_stat(12, 35, "abs") == "12"


def test_format_stat_rel():
    assert format_stat(3, 30, "rel") == "10.0%"


def test_format_stat_both():
    assert format_stat(12, 35, None) == "12 (34.3%)"


def test_format_stat_zero_total():
    assert format_stat(0, 0, "rel") == "0.0%"


def test_format_stat_unknown_view():
    with pytest.raises(ValueError):
        format_stat(1, 2, "weird")


def test_format_stats_includes_missing_faces():
    lines = format_stats({3: {1: 2, 3: 2}}, "abs")
    assert lines == ["d3: 1 — 2, 2 — 0, 3 — 2"]


def test_format_stats_both_views():
    lines = format_stats({2: {1: 1, 2: 3}}, None)
    assert lines == ["d2: 1 — 1 (25.0%), 2 — 3 (75.0%)"]


def test_format_stats_sorted_by_sides():
    lines = format_stats({20: {1: 1}, 2: {1: 1}}, "abs")
    assert lines[0].startswith("d2:")
    assert lines[1].startswith("d20:")


# --- CLI ---


def test_cli_roll_success(cli_env):
    result = CliRunner().invoke(cli, ["roll", "-c", "3", "-s", "20"])
    assert result.exit_code == 0
    assert "🎲" in result.output
    assert "Сумма:" in result.output
    assert cli_env["db"].exists()


def test_cli_rejects_bad_sides(cli_env):
    result = CliRunner().invoke(cli, ["roll", "-c", "2", "-s", "1"])
    assert result.exit_code != 0
    assert "--sides" in result.output


def test_cli_rejects_bad_count(cli_env):
    result = CliRunner().invoke(cli, ["roll", "--count", "0"])
    assert result.exit_code != 0
    assert "--count" in result.output


def test_cli_rejects_non_integer(cli_env):
    result = CliRunner().invoke(cli, ["roll", "--count", "abc"])
    assert result.exit_code != 0


def test_cli_stats_empty(cli_env):
    result = CliRunner().invoke(cli, ["stats"])
    assert result.exit_code == 0
    assert "Бросков пока нет" in result.output


def test_cli_stats_views(cli_env, monkeypatch):
    monkeypatch.setattr(dice, "roll_dice", lambda count, sides: [1, 1, 2])
    runner = CliRunner()
    assert runner.invoke(cli, ["roll"]).exit_code == 0

    abs_result = runner.invoke(cli, ["stats", "--view", "abs"])
    assert abs_result.exit_code == 0
    assert "d6: 1 — 2, 2 — 1, 3 — 0, 4 — 0, 5 — 0, 6 — 0" in abs_result.output

    rel_result = runner.invoke(cli, ["stats", "--view", "rel"])
    assert "1 — 66.7%, 2 — 33.3%, 3 — 0.0%" in rel_result.output

    both_result = runner.invoke(cli, ["stats"])
    assert "1 — 2 (66.7%), 2 — 1 (33.3%), 3 — 0 (0.0%)" in both_result.output


def test_cli_stats_invalid_view(cli_env):
    result = CliRunner().invoke(cli, ["stats", "--view", "xyz"])
    assert result.exit_code != 0


def test_cli_database_error_gives_nonzero_exit(tmp_path, monkeypatch):
    bad_db = tmp_path / "no_such_dir" / "x.db"
    monkeypatch.setenv("DICE_DB_URL", f"sqlite:///{bad_db.as_posix()}")
    monkeypatch.setenv("DICE_LOG_FILE", str(tmp_path / "test.log"))
    result = CliRunner().invoke(cli, ["stats"])
    assert result.exit_code == 1
    assert "Error:" in result.output


def test_cli_writes_log_file(cli_env):
    CliRunner().invoke(cli, ["roll", "-c", "2"])
    text = cli_env["log"].read_text(encoding="utf-8")
    assert "INFO" in text
    assert "Брошено 2 костей" in text