# Лицензии зависимостей и включённых палитр

Проверка метаданных установленных дистрибутивов кандидата 0.1.0.
Зависимости **не встроены и не перелицензированы**: uv устанавливает их
отдельно, вместе с лицензиями/атрибуцией соответствующих wheels. Перед
перераспространением собранного окружения сохраняйте эти файлы и исполняйте
условия каждой лицензии; MIT проекта не распространяется на все зависимости.

| Runtime-дистрибутив | Проверенная версия | Лицензия |
| --- | --- | --- |
| textual | 6.6.0 | MIT |
| httpx | 0.28.1 | BSD-3-Clause |
| anyio | 4.15.1 | MIT |
| certifi | 2026.10.19 | MPL-2.0 |
| h11 | 0.16.0 | MIT |
| httpcore | 1.0.9 | BSD-3-Clause |
| idna | 3.20 | BSD-3-Clause |
| linkify-it-py | 2.2.0 | MIT |
| markdown-it-py | 4.2.0 | MIT |
| mdit-py-plugins | 0.6.1 | MIT |
| mdurl | 0.1.2 | MIT |
| platformdirs | 4.13.5 | MIT |
| Pygments | 2.21.0 | BSD-2-Clause |
| rich | 15.0.0 | MIT |
| typing_extensions | 4.16.0 | PSF-2.0 |

Отдельное изолированное build-окружение: hatchling 1.27.0 (MIT),
packaging 26.3 (Apache-2.0 OR BSD-2-Clause), pathspec 1.1.1 (MPL-2.0),
pluggy 1.7.0 (MIT), trove-classifiers 2026.9.21.13 (Apache-2.0).
Они не являются дополнительными runtime-зависимостями приложения.
Python распространяется отдельно под PSF License; uv и Git — отдельные
инструменты установки, Go Task — необязательная обёртка, не часть пакета.

Условия MIT/BSD/PSF, MPL для неизменённых отдельно устанавливаемых certifi
и pathspec и альтернативная лицензия packaging не требуют перелицензировать
собственный код этого клиента. Сторонние файлы этих зависимостей не изменялись. Будущая упаковка
зависимостей внутрь приложения потребует отдельной проверки обязанностей.

`uv.lock` фиксирует версии для разработки. Установка из Git-тега не применяет
lockfile; её транзитивные версии могут отличаться от таблицы. Для фактически
установленных версий источником лицензий остаются metadata и license-файлы
дистрибутивов в окружении, а не эта таблица.

## Включённые цветовые палитры

`src/jira_overview/themes.py` содержит локальные адаптации следующих палитр.
Цвета взяты из указанных закреплённых источников; соответствие UI-ролям Textual
и настройки курсора заданы этим проектом. Новых runtime-зависимостей нет.
Настоящий документ с уведомлениями включён в license-файлы wheel/sdist.

### Rosé Pine / Rosé Pine Dawn

Источник палитры: <https://github.com/rose-pine/palette/blob/92af52b465ab6e47437aca223c9b8d3009a2023b/palette.json>.
Лицензия upstream: [LICENSE](https://raw.githubusercontent.com/rose-pine/palette/92af52b465ab6e47437aca223c9b8d3009a2023b/LICENSE).

```text
MIT License

Copyright (c) mvllow

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
```

### Everforest Dark / Light (medium)

Источник палитры: <https://github.com/sainnhe/everforest/blob/85a86eb62409e3ec88713bff3d1b9d7374e112e4/palette.md>.
Лицензия upstream: [LICENSE](https://raw.githubusercontent.com/sainnhe/everforest/85a86eb62409e3ec88713bff3d1b9d7374e112e4/LICENSE).

```text
MIT License

Copyright (c) 2019 sainnhe

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
```

### Kanagawa Wave

Источник палитры: <https://github.com/rebelot/kanagawa.nvim/blob/bb85e4bfc8d89b0e62c8fa53ccdd13d12e2f77b3/lua/kanagawa/colors.lua>.
Лицензия upstream: [LICENSE](https://raw.githubusercontent.com/rebelot/kanagawa.nvim/bb85e4bfc8d89b0e62c8fa53ccdd13d12e2f77b3/LICENSE).

```text
MIT License

Copyright (c) 2021 Tommaso Laurenzi

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
```

### Gruvbox Light

Источник палитры и атрибуции: [gruvbox.vim](https://github.com/morhetz/gruvbox/blob/ef8864bb42bf244f0295d1c5a403b27e3d139695/colors/gruvbox.vim).
[README upstream](https://github.com/morhetz/gruvbox/blob/ef8864bb42bf244f0295d1c5a403b27e3d139695/README.md#license)
объявляет MIT/X11; отдельного LICENSE в этом снимке нет. Атрибуция взята из
заголовка исходного файла; ниже приведены условия MIT.

```text
Author: morhetz <morhetz@gmail.com>
Source: https://github.com/morhetz/gruvbox
License: MIT/X11

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
```
