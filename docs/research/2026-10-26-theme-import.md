# Десять дополнительных тёмных тем для jw

Реализация [#41](https://github.com/aprudkin/jirawarrior-tui/issues/41),
2026-10-26. Продолжает набор из #33: **27 цветовых тем, 21 тёмная и 6 светлых**.
Все десять новых вариантов тёмные. Выбраны известные семейства тем терминалов
и редакторов; это не рейтинг популярности по загрузкам.

## Где искать палитры

- [iTerm2 Color Schemes](https://iterm2colorschemes.com/) и его
  [исходный каталог](https://github.com/mbadolato/iTerm2-Color-Schemes):
  скриншоты и схемы для разных терминалов, включая iTerm2, Terminal и Kitty.
- [Gogh](https://gogh.website/): каталог терминальных цветовых схем с предпросмотром.
- [VS Code Themes](https://vscodethemes.com/): сравнение тем редактора на примерах кода.
- [Catppuccin](https://catppuccin.com/palette/) и
  [Rosé Pine](https://rosepinetheme.com/palette/): именованные цвета вариантов
  одного семейства, удобные для переноса в другой интерфейс.

Каталоги используются для выбора; точные цвета и лицензии берутся из первичных
репозиториев ниже. Их установочные скрипты не запускались. Наличие схемы для
терминала или VS Code не означает совместимость её файла с Textual.

## Закреплённые первичные источники

| Имена в jw | Источник цветов | Снимок upstream |
| --- | --- | --- |
| `one-dark` | [Atom colors.less](https://github.com/atom/one-dark-syntax/blob/9c96f4454362267ac45322063e193ccf9d2debb1/styles/colors.less) | `9c96f4454362267ac45322063e193ccf9d2debb1` |
| `solarized-dark` | [Solarized, таблица README](https://github.com/altercation/solarized/blob/62f656a02f93c5190a8753159e34b385588d5ff3/README.md#the-values) | `62f656a02f93c5190a8753159e34b385588d5ff3` |
| `ayu-dark`, `ayu-mirage` | [dark.yaml](https://github.com/ayu-theme/ayu-colors/blob/d461f02983546636bc6e1e0c48190fdb74036426/themes/dark.yaml), [mirage.yaml](https://github.com/ayu-theme/ayu-colors/blob/d461f02983546636bc6e1e0c48190fdb74036426/themes/mirage.yaml) | `d461f02983546636bc6e1e0c48190fdb74036426` |
| `night-owl` | [Night Owl-color-theme.json](https://github.com/sdras/night-owl-vscode-theme/blob/cc291eba7976b20d7c66bde6883c27b902196b07/themes/Night%20Owl-color-theme.json) | `cc291eba7976b20d7c66bde6883c27b902196b07` |
| `github-dark` | [GitHub classic/colors.json](https://github.com/primer/github-vscode-theme/blob/cd78e5e4e7bcf132a6f428ae0f32264bb1b729cf/src/classic/colors.json) | `cd78e5e4e7bcf132a6f428ae0f32264bb1b729cf` |
| `catppuccin-frappe`, `catppuccin-macchiato` | [palette.json](https://github.com/catppuccin/palette/blob/07d02aa110ef9eb7e7427afca5c73ba9cf7f8ebd/palette.json), ключи `frappe` / `macchiato` | `07d02aa110ef9eb7e7427afca5c73ba9cf7f8ebd` |
| `rose-pine-moon` | [palette.json](https://github.com/rose-pine/palette/blob/92af52b465ab6e47437aca223c9b8d3009a2023b/palette.json), ключ `moon` | `92af52b465ab6e47437aca223c9b8d3009a2023b` |
| `kanagawa-dragon` | [colors.lua](https://github.com/rebelot/kanagawa.nvim/blob/bb85e4bfc8d89b0e62c8fa53ccdd13d12e2f77b3/lua/kanagawa/colors.lua), [themes.lua](https://github.com/rebelot/kanagawa.nvim/blob/bb85e4bfc8d89b0e62c8fa53ccdd13d12e2f77b3/lua/kanagawa/themes.lua) | `bb85e4bfc8d89b0e62c8fa53ccdd13d12e2f77b3` |

Все источники имеют MIT-условия. Полные тексты и copyright сохранены в
[THIRD_PARTY_NOTICES.md](../../THIRD_PARTY_NOTICES.md), включённом в wheel/sdist.

## Адаптация к jw, не копирование редактора целиком

Формат — статические `textual.theme.Theme` в
[`themes.py`](../../src/jira_overview/themes.py), зарегистрированные существующим
кодом приложения. Новых зависимостей, загрузок палитр при запуске и импортера
пользовательских файлов нет. `theme.json`, XDG-пути и прежние имена сохранены;
стандартная тема остаётся `textual-dark`. Выбор — через **t → имя → Enter**.

| Тема | Фон | Основной текст | Характер |
| --- | --- | --- | --- |
| One Dark | `#282c34` | `#abb2bf` | Нейтральный графит, синие и фиолетовые акценты |
| Solarized Dark | `#002b36` | `#93a1a1` | Тёмный сине-зелёный, приглушённая охра |
| Ayu Dark | `#0d1017` | `#bfbdb6` | Почти чёрный, янтарный и голубой |
| Ayu Mirage | `#1f2430` | `#cccac2` | Мягкий серо-синий, золотой и пастельный |
| Night Owl | `#011627` | `#d6deeb` | Глубокий синий, голубые и бирюзовые акценты |
| GitHub Dark (classic) | `#24292e` | `#e1e4e8` | Классический серый GitHub, не вариант Dark Default |
| Catppuccin Frappé | `#303446` | `#c6d0f5` | Более светлая из новых пастельных схем |
| Catppuccin Macchiato | `#24273a` | `#cad3f5` | Более тёмная пастельная схема |
| Rosé Pine Moon | `#232136` | `#e0def4` | Лиловые поверхности и розовые акценты |
| Kanagawa Dragon | `#181616` | `#c5c9c5` | Тёплый угольный, приглушённые природные цвета |

Соответствие `primary/secondary/accent/success/warning/error` ролям Textual —
решение этой адаптации, а не обещание одинаковых семантических ролей upstream.
Особенности:

- One Dark: HSL из `colors.less` переведён в RGB с округлением каждого канала
  до ближайшего целого (`floor(channel * 255 + 0.5)`). Тёмная поверхность
  `#21252b` получена из той же основы HSL(220, 13%, 18%) снижением lightness
  до 15%; остальные цвета — исходные HSL-токены.
- Solarized: для текста выбран **base1**, а не более тусклый base0, чтобы
  сохранить читаемость на base02 и курсоре.
- Ayu: фон — `surface.base` / `ui.bg`, поверхность — `surface.lift`, панель —
  `ui.panel.bg`; цвета взяты из указанного снимка, не старой версии палитры.
- Catppuccin: `base`, `text`, `mantle`, `surface0`; синий, mauve, pink,
  green, yellow, red соответствуют акцентам и состояниям jw.
- Rosé Pine Moon: `base`, `text`, `surface`, `overlay`; foam, iris, rose,
  gold и love — акценты и состояния.
- Kanagawa Dragon: `dragonBlack3`, `dragonWhite`, `dragonBlack1`, `dragonBlack4`;
  статусы намеренно используют мягкие Dragon green/yellow/red, а не яркие
  диагностические цвета Neovim.
- Фон курсора задан отдельно для каждой темы, текст не заменяется ярким
  accent-цветом. `NEW`/`Comment` сохраняют существующие bold ANSI green/yellow;
  конечные RGB этих двух меток зависят от терминала, универсальный численный
  контраст для произвольной терминальной палитры не гарантируется.

## Проверка

Синтетические Textual Pilot-тесты расширены на все 16 дополнительных тем:
набор/режим/базовые цвета, предпросмотр, отмена, сохранение, перезапуск, панели,
ошибки ввода, таблицы, курсор с фокусом и без, текст и цвета меток. Проверяется
контраст текста ключа не ниже 4.5:1 в проверяемых состояниях, а также отсутствие
новых HTTP-запросов, браузерных действий и изменений истории просмотра при выборе.
Отдельная проверка поставки требует copyright новых палитр в metadata лицензий.
Живая Jira, настоящий браузер и пользовательская история для этого не нужны.
