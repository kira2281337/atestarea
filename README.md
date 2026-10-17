Kononenko Kira

# dice

CLI-утилита для броска игральных костей на Python (Click + SQLAlchemy + SQLite). Каждый выпавший результат сохраняется в базу `stats.db`, а команда `stats` показывает, как часто выпадали значения. Работа утилиты логируется в файл `app.log`.

## Установка

```
git clone https://github.com/kira2281337/atestarea.git
cd dice
python -m venv .venv
.venv\Scripts\activate.bat
pip install -r requirements.txt
pip install -e .
```

На Linux/macOS активация: `source .venv/bin/activate`.

## Использование

```
dice roll                     # одна кость d6
dice roll --count 3 --sides 20
dice roll -c 2 -s 10
dice stats --view abs         # абсолютные числа
dice stats --view rel         # проценты
dice stats                    # оба вида: 12 (34.3%)
```

Без установки можно запускать так: `python dice.py roll`.

Пример:

```
$ dice roll -c 3 -s 20
🎲 [12, 1, 20]
Сумма: 33

$ dice stats --view abs
d20: 1 — 1, 2 — 0, ..., 12 — 1, ..., 20 — 1
```

Некорректный ввод (`--count 0`, `--sides 1`) даёт понятную ошибку и ненулевой код выхода.

## Тесты и проверка кода

```
pytest
ruff format --check .
ruff check .
```

## Структура

- `dice.py` — CLI и бизнес-логика (`roll_dice`, `save_throws`, `count_throws`, `format_stats`)
- `test_dice.py` — автоматические тесты
- `pyproject.toml` — настройки пакета
- `requirements.txt` — зависимости