# maxkit

Асинхронное API для работы с мессенджером [Max](https://max.ru).

> [!NOTE]
> maxkit — поддерживаемый преемник [aiomax](https://github.com/dpnspn/aiomax)
> (оригинальный репозиторий заархивирован 14.07.2026). Модуль по-прежнему
> импортируется как `aiomax`, поэтому переход с PyPI-пакета `aiomax` сводится
> к замене зависимости — код ботов менять не нужно.

## Начало работы

Чтобы установить maxkit, выполните следующую команду:

```bash
pip install maxkit
```

Чтобы установить git-версию maxkit (возможны баги и нестабильность), выполните команду:

```bash
pip install git+https://github.com/gistrec/maxkit.git
```

Импорт в коде остаётся прежним:

```python
import aiomax
```

> [!IMPORTANT]
> С недавнего времени для подключения к серверам Max нужен [сертификат Минцифры](https://www.gosuslugi.ru/crt).
> Если у вас не установлен сертификат, при создании класса бота можно указать параметр `use_certificate=True` - тогда библиотека будет использовать встроенный сертификат Минцифры.

> [!WARNING]
> При использовании сертификатов Минцифры государство Российской Федерации может получать доступ ко всему отправляемому трафику.
> Рекомендуется не использовать сессию бота для отправки конфиденциальных данных при установленном `use_certificate=True`.

Документация и примеры ботов [тут](https://github.com/gistrec/maxkit/wiki)

## Aiomax Community

Обсудить aiomax / задать вопрос можно в сети чатов Aiomax Community
[Telegram](https://t.me/aiomax_chat) / [Max](https://max.ru/join/45DmBRwDNvcZVqYvf_cSCPu-_DuvYa5VmuQ4K2cmC_Q)

Новости о aiomax и Max Bot API выходят на телеграм канале [Aiomax Changelog](https://t.me/aiomax_cl)
