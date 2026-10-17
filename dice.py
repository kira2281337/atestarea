import logging
import os
import random
from contextlib import contextmanager

import click
from sqlalchemy import create_engine, func, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column

DEFAULT_DB_URL = "sqlite:///stats.db"
DEFAULT_LOG_FILE = "app.log"

logger = logging.getLogger("dice")


class StorageError(Exception):
    """Ошибка работы с базой данных."""


class Base(DeclarativeBase):
    pass


class Throw(Base):
    __tablename__ = "throws"

    id: Mapped[int] = mapped_column(primary_key=True)
    sides: Mapped[int]
    value: Mapped[int]


def setup_logging():
    """Настраивает запись логов в файл app.log."""
    log_file = os.environ.get("DICE_LOG_FILE", DEFAULT_LOG_FILE)
    for handler in list(logger.handlers):
        logger.removeHandler(handler)
        handler.close()
    handler = logging.FileHandler(log_file, encoding="utf-8")
    handler.setFormatter(
        logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
    )
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    logger.propagate = False


@contextmanager
def get_session():
    """Открывает сессию, создаёт таблицы и гарантированно освобождает ресурсы."""
    engine = create_engine(os.environ.get("DICE_DB_URL", DEFAULT_DB_URL))
    try:
        Base.metadata.create_all(engine)
        with Session(engine) as session:
            yield session
    except SQLAlchemyError as exc:
        logger.exception("Ошибка базы данных")
        raise StorageError("Ошибка при работе с базой данных") from exc
    finally:
        engine.dispose()


def roll_dice(count, sides):
    if count < 1:
        raise ValueError("--count должно быть не меньше 1")
    if sides < 2:
        raise ValueError("--sides должно быть не меньше 2")
    return [random.randint(1, sides) for _ in range(count)]


def save_throws(session, sides, values):
    try:
        session.add_all(Throw(sides=sides, value=v) for v in values)
        session.commit()
    except SQLAlchemyError as exc:
        session.rollback()
        logger.exception("Не удалось сохранить броски")
        raise StorageError("Не удалось сохранить броски в базу данных") from exc


def count_throws(session):
    """Возвращает {sides: {value: сколько раз выпало}}."""
    query = select(Throw.sides, Throw.value, func.count())
    query = query.group_by(Throw.sides, Throw.value)
    try:
        rows = session.execute(query).all()
    except SQLAlchemyError as exc:
        logger.exception("Не удалось прочитать статистику")
        raise StorageError("Не удалось прочитать статистику из базы данных") from exc
    result = {}
    for sides, value, cnt in rows:
        result.setdefault(sides, {})[value] = cnt
    return result


def format_stat(count, total, view):
    percent = count / total * 100 if total else 0
    if view == "abs":
        return f"{count}"
    if view == "rel":
        return f"{percent:.1f}%"
    if view is None:
        return f"{count} ({percent:.1f}%)"
    raise ValueError(f"Неизвестный вид статистики: {view}")


def format_stats(data, view):
    """Возвращает список строк вида 'd6: 1 — 4, 2 — 7, ...'."""
    lines = []
    for sides in sorted(data):
        counts = data[sides]
        total = sum(counts.values())
        parts = [
            f"{value} — {format_stat(counts.get(value, 0), total, view)}"
            for value in range(1, sides + 1)
        ]
        lines.append(f"d{sides}: " + ", ".join(parts))
    return lines


@click.group()
def cli():
    """Утилита для бросания костей со статистикой."""
    setup_logging()


@cli.command()
@click.option("--count", "-c", type=int, default=1, help="Сколько костей бросить")
@click.option("--sides", "-s", type=int, default=6, help="Сколько граней у кости")
def roll(count, sides):
    """Бросает кости и сохраняет результаты."""
    try:
        values = roll_dice(count, sides)
    except ValueError as exc:
        logger.warning("Некорректный ввод: count=%s sides=%s", count, sides)
        raise click.BadParameter(str(exc)) from exc

    try:
        with get_session() as session:
            save_throws(session, sides, values)
    except StorageError as exc:
        raise click.ClickException(str(exc)) from exc

    logger.info("Брошено %s костей d%s: %s", count, sides, values)
    click.echo(f"🎲 {values}")
    click.echo(f"Сумма: {sum(values)}")


@cli.command()
@click.option("--view", type=click.Choice(["abs", "rel"]), default=None)
def stats(view):
    """Показывает статистику выпавших значений."""
    try:
        with get_session() as session:
            data = count_throws(session)
    except StorageError as exc:
        raise click.ClickException(str(exc)) from exc

    logger.info("Запрошена статистика, view=%s", view)
    if not data:
        click.echo("Бросков пока нет")
        return
    for line in format_stats(data, view):
        click.echo(line)


if __name__ == "__main__":
    cli()
