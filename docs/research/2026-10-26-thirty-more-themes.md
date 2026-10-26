# Ещё 20 тёмных и 10 светлых тем

Реализация [#43](https://github.com/aprudkin/jirawarrior-tui/issues/43)
расширяет набор после [#41](https://github.com/aprudkin/jirawarrior-tui/issues/41):
27 → 57 цветовых тем (41 тёмная, 16 светлых). Textual остаётся на 6.6.0,
новых runtime-зависимостей нет. Это статические адаптации Base16, а не загрузчик
пользовательских YAML и не плагины редакторов.

## Источник и атрибуция

Первичный источник включённых Base16-определений —
[tinted-theming/schemes](https://github.com/tinted-theming/schemes/tree/3662d9d0c4e551101620478229455a72bb016ced/base16),
закреплённый commit `3662d9d0c4e551101620478229455a72bb016ced`.
[README источника](https://github.com/tinted-theming/schemes/blob/3662d9d0c4e551101620478229455a72bb016ced/README.md)
объясняет единый каталог схем. Каждая включённая палитра и её автор перечислены
в [THIRD_PARTY_NOTICES.md](../../THIRD_PARTY_NOTICES.md#base16--tinted-theming-ещё-30-палитр);
там же полный текст MIT-лицензии. Уведомления входят в wheel/sdist.

Набор выбирался для разнообразия цветовых семейств, а не как рейтинг популярности.
`github.yaml` называется в приложении `github-light`, чтобы режим был явным и
не было коллизии с прежней `github-dark`. Существующие имена не меняются.

- Тёмные: `atlas`, `ashes`, `bespin`, `brewer`, `chalk`, `darcula`, `eighties`, `embers`,
  `espresso`, `flat`, `github-dark-dimmed`, `gruvbox-material-dark-medium`,
  `horizon-dark`, `material`, `material-darker`, `material-palenight`, `oceanicnext`,
  `spaceduck`, `tomorrow-night`, `zenburn`.
- Светлые: `ayu-light`, `github-light`, `gruvbox-material-light-medium`, `horizon-light`,
  `material-lighter`, `one-light`, `papercolor-light`, `selenized-light`, `tomorrow`,
  `atelier-sulphurpool-light`.

## Перенос ролей

| Роль Textual | Оттенок Base16 |
| --- | --- |
| background | base00 |
| surface, panel | base01 |
| foreground | base05, с исключениями ниже |
| primary | base0D |
| secondary | base0C |
| accent | base0E |
| success | base0B |
| warning | base0A |
| error | base08, с контрастной адаптацией ниже |
| block-cursor-background, block-cursor-blurred-background | base00 |
| block-cursor-foreground | выбранный foreground |
| block-cursor-text-style | none |

Цвета не вычисляются и не загружаются во время работы. Для основного текста выбран
первый из base05/base06/base07 с контрастом не ниже 4.5:1 на base00 и base01.
Поэтому у `bespin` и `atelier-sulphurpool-light` используется base06,
у `material-lighter`, `material-palenight` и `papercolor-light` — base07.
Ошибка настроек выводится цветом error. Если base08 даёт контраст ниже 4.5:1
на base00/base01, он статически осветлён (тёмные темы) или затемнён (светлые)
смешением RGB с белым/чёрным до порога 4.6:1 с шагом 1% (каналы округлены
до целого, половины вверх). Это производный цвет,
а не буквальный HEX upstream. Остальные HEX соответствуют закреплённым YAML,
с нормализацией регистра.

Курсор использует base00, чтобы выделение строки не перекрашивало ключ и локальные
метки в малоконтрастный акцент. Метки NEW/Comment сохраняют текст, жирность и
именованные ANSI-цвета green/yellow: их конечные RGB задаёт терминал, универсальный
численный контраст для произвольной терминальной палитры не заявляется.

## Границы проверки

`tests/test_themes.py` содержит независимые ожидания имён, режимов и основных
цветов всех 46 дополнительных тем; полный состав — 57 тем без ANSI.
Textual Pilot проверяет клавиатурный выбор, предпросмотр/отмену, подтверждение,
перезапуск, настройки/ошибку ввода (включая контраст реально отрисованного текста
ошибки во всех 30 новых темах), реальные стили текста и курсора, метки,
неизменность HTTP-запросов, браузерных действий и истории от выбора темы.
Тест дистрибутива проверяет поставку нового MIT-уведомления.

Живая Jira, настоящие браузеры и приватная конфигурация для этой проверки не нужны.
