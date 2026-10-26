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

### Base16 / Tinted Theming: ещё 30 палитр

Палитры перенесены из [tinted-theming/schemes](https://github.com/tinted-theming/schemes/tree/3662d9d0c4e551101620478229455a72bb016ced/base16),
commit `3662d9d0c4e551101620478229455a72bb016ced`.
Это адаптации именно Base16-вариантов, не полные темы соответствующих редакторов.
Авторы указаны по полям `author` закреплённых YAML. Соответствие ролям UI и
контрастные оттенки текста описаны в [заметке](docs/research/2026-10-26-thirty-more-themes.md).

| Имя в приложении | Режим | Источник | Автор палитры |
| --- | --- | --- | --- |
| `atlas` | Тёмная | [atlas.yaml](https://github.com/tinted-theming/schemes/blob/3662d9d0c4e551101620478229455a72bb016ced/base16/atlas.yaml) | Alex Lende (https://ajlende.com) |
| `ashes` | Тёмная | [ashes.yaml](https://github.com/tinted-theming/schemes/blob/3662d9d0c4e551101620478229455a72bb016ced/base16/ashes.yaml) | Jannik Siebert (https://github.com/janniks) |
| `bespin` | Тёмная | [bespin.yaml](https://github.com/tinted-theming/schemes/blob/3662d9d0c4e551101620478229455a72bb016ced/base16/bespin.yaml) | Jan T. Sott |
| `brewer` | Тёмная | [brewer.yaml](https://github.com/tinted-theming/schemes/blob/3662d9d0c4e551101620478229455a72bb016ced/base16/brewer.yaml) | Timothée Poisot (http://github.com/tpoisot) |
| `chalk` | Тёмная | [chalk.yaml](https://github.com/tinted-theming/schemes/blob/3662d9d0c4e551101620478229455a72bb016ced/base16/chalk.yaml) | Chris Kempson (http://chriskempson.com) |
| `darcula` | Тёмная | [darcula.yaml](https://github.com/tinted-theming/schemes/blob/3662d9d0c4e551101620478229455a72bb016ced/base16/darcula.yaml) | jetbrains |
| `eighties` | Тёмная | [eighties.yaml](https://github.com/tinted-theming/schemes/blob/3662d9d0c4e551101620478229455a72bb016ced/base16/eighties.yaml) | Chris Kempson (http://chriskempson.com) |
| `embers` | Тёмная | [embers.yaml](https://github.com/tinted-theming/schemes/blob/3662d9d0c4e551101620478229455a72bb016ced/base16/embers.yaml) | Jannik Siebert (https://github.com/janniks) |
| `espresso` | Тёмная | [espresso.yaml](https://github.com/tinted-theming/schemes/blob/3662d9d0c4e551101620478229455a72bb016ced/base16/espresso.yaml) | Unknown. Maintained by Alex Mirrington (https://github.com/alexmirrington) |
| `flat` | Тёмная | [flat.yaml](https://github.com/tinted-theming/schemes/blob/3662d9d0c4e551101620478229455a72bb016ced/base16/flat.yaml) | Chris Kempson (http://chriskempson.com) |
| `github-dark-dimmed` | Тёмная | [github-dark-dimmed.yaml](https://github.com/tinted-theming/schemes/blob/3662d9d0c4e551101620478229455a72bb016ced/base16/github-dark-dimmed.yaml) | Tinted Theming (https://github.com/tinted-theming) |
| `gruvbox-material-dark-medium` | Тёмная | [gruvbox-material-dark-medium.yaml](https://github.com/tinted-theming/schemes/blob/3662d9d0c4e551101620478229455a72bb016ced/base16/gruvbox-material-dark-medium.yaml) | Mayush Kumar (https://github.com/MayushKumar), sainnhe (https://github.com/sainnhe/gruvbox-material-vscode) |
| `horizon-dark` | Тёмная | [horizon-dark.yaml](https://github.com/tinted-theming/schemes/blob/3662d9d0c4e551101620478229455a72bb016ced/base16/horizon-dark.yaml) | Michaël Ball (http://github.com/michael-ball/) |
| `material` | Тёмная | [material.yaml](https://github.com/tinted-theming/schemes/blob/3662d9d0c4e551101620478229455a72bb016ced/base16/material.yaml) | Nate Peterson |
| `material-darker` | Тёмная | [material-darker.yaml](https://github.com/tinted-theming/schemes/blob/3662d9d0c4e551101620478229455a72bb016ced/base16/material-darker.yaml) | Nate Peterson |
| `material-palenight` | Тёмная | [material-palenight.yaml](https://github.com/tinted-theming/schemes/blob/3662d9d0c4e551101620478229455a72bb016ced/base16/material-palenight.yaml) | Nate Peterson |
| `oceanicnext` | Тёмная | [oceanicnext.yaml](https://github.com/tinted-theming/schemes/blob/3662d9d0c4e551101620478229455a72bb016ced/base16/oceanicnext.yaml) | https://github.com/voronianski/oceanic-next-color-scheme |
| `spaceduck` | Тёмная | [spaceduck.yaml](https://github.com/tinted-theming/schemes/blob/3662d9d0c4e551101620478229455a72bb016ced/base16/spaceduck.yaml) | Guillermo Rodriguez (https://github.com/pineapplegiant), packaged by Gabriel Fontes (https://github.com/Misterio77) |
| `tomorrow-night` | Тёмная | [tomorrow-night.yaml](https://github.com/tinted-theming/schemes/blob/3662d9d0c4e551101620478229455a72bb016ced/base16/tomorrow-night.yaml) | Chris Kempson (http://chriskempson.com) |
| `zenburn` | Тёмная | [zenburn.yaml](https://github.com/tinted-theming/schemes/blob/3662d9d0c4e551101620478229455a72bb016ced/base16/zenburn.yaml) | elnawe |
| `ayu-light` | Светлая | [ayu-light.yaml](https://github.com/tinted-theming/schemes/blob/3662d9d0c4e551101620478229455a72bb016ced/base16/ayu-light.yaml) | Tinted Theming (https://github.com/tinted-theming), Ayu Theme (https://github.com/ayu-theme) |
| `github-light` | Светлая | [github.yaml](https://github.com/tinted-theming/schemes/blob/3662d9d0c4e551101620478229455a72bb016ced/base16/github.yaml) | Tinted Theming (https://github.com/tinted-theming) |
| `gruvbox-material-light-medium` | Светлая | [gruvbox-material-light-medium.yaml](https://github.com/tinted-theming/schemes/blob/3662d9d0c4e551101620478229455a72bb016ced/base16/gruvbox-material-light-medium.yaml) | Mayush Kumar (https://github.com/MayushKumar), sainnhe (https://github.com/sainnhe/gruvbox-material-vscode) |
| `horizon-light` | Светлая | [horizon-light.yaml](https://github.com/tinted-theming/schemes/blob/3662d9d0c4e551101620478229455a72bb016ced/base16/horizon-light.yaml) | Michaël Ball (http://github.com/michael-ball/) |
| `material-lighter` | Светлая | [material-lighter.yaml](https://github.com/tinted-theming/schemes/blob/3662d9d0c4e551101620478229455a72bb016ced/base16/material-lighter.yaml) | Nate Peterson |
| `one-light` | Светлая | [one-light.yaml](https://github.com/tinted-theming/schemes/blob/3662d9d0c4e551101620478229455a72bb016ced/base16/one-light.yaml) | Daniel Pfeifer (http://github.com/purpleKarrot) |
| `papercolor-light` | Светлая | [papercolor-light.yaml](https://github.com/tinted-theming/schemes/blob/3662d9d0c4e551101620478229455a72bb016ced/base16/papercolor-light.yaml) | Jon Leopard (http://github.com/jonleopard), Tinted Theming (https://github.com/tinted-theming), based on PaperColor Theme (https://github.com/NLKNguyen/papercolor-theme) |
| `selenized-light` | Светлая | [selenized-light.yaml](https://github.com/tinted-theming/schemes/blob/3662d9d0c4e551101620478229455a72bb016ced/base16/selenized-light.yaml) | Jan Warchol (https://github.com/jan-warchol/selenized) / adapted to base16 by ali |
| `tomorrow` | Светлая | [tomorrow.yaml](https://github.com/tinted-theming/schemes/blob/3662d9d0c4e551101620478229455a72bb016ced/base16/tomorrow.yaml) | Chris Kempson (http://chriskempson.com) |
| `atelier-sulphurpool-light` | Светлая | [atelier-sulphurpool-light.yaml](https://github.com/tinted-theming/schemes/blob/3662d9d0c4e551101620478229455a72bb016ced/base16/atelier-sulphurpool-light.yaml) | Bram de Haan (http://atelierbramdehaan.nl) |

Лицензия репозитория источников:
[MIT](https://github.com/tinted-theming/schemes/blob/3662d9d0c4e551101620478229455a72bb016ced/LICENSE).

```text
Copyright (c) 2022 Tinted Theming (https://github.com/tinted-theming)

Permission is hereby granted, free of charge, to any person obtaining
a copy of this software and associated documentation files (the
"Software"), to deal in the Software without restriction, including
without limitation the rights to use, copy, modify, merge, publish,
distribute, sublicense, and/or sell copies of the Software, and to
permit persons to whom the Software is furnished to do so, subject to
the following conditions:

The above copyright notice and this permission notice shall be
included in all copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND,
EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF
MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND
NONINFRINGEMENT. IN NO EVENT SHALL THE AUTHORS OR COPYRIGHT HOLDERS BE
LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY, WHETHER IN AN ACTION
OF CONTRACT, TORT OR OTHERWISE, ARISING FROM, OUT OF OR IN CONNECTION
WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE SOFTWARE.
```

### One Dark

Источник палитры: <https://github.com/atom/one-dark-syntax/blob/9c96f4454362267ac45322063e193ccf9d2debb1/styles/colors.less>.
Лицензия upstream: [LICENSE.md](https://raw.githubusercontent.com/atom/one-dark-syntax/9c96f4454362267ac45322063e193ccf9d2debb1/LICENSE.md).

```text
Copyright (c) 2016 GitHub Inc.

Permission is hereby granted, free of charge, to any person obtaining
a copy of this software and associated documentation files (the
"Software"), to deal in the Software without restriction, including
without limitation the rights to use, copy, modify, merge, publish,
distribute, sublicense, and/or sell copies of the Software, and to
permit persons to whom the Software is furnished to do so, subject to
the following conditions:

The above copyright notice and this permission notice shall be
included in all copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND,
EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF
MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND
NONINFRINGEMENT. IN NO EVENT SHALL THE AUTHORS OR COPYRIGHT HOLDERS BE
LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY, WHETHER IN AN ACTION
OF CONTRACT, TORT OR OTHERWISE, ARISING FROM, OUT OF OR IN CONNECTION
WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE SOFTWARE.
```

### Solarized Dark

Источник палитры: <https://github.com/altercation/solarized/blob/62f656a02f93c5190a8753159e34b385588d5ff3/README.md>.
Лицензия upstream: [LICENSE](https://raw.githubusercontent.com/altercation/solarized/62f656a02f93c5190a8753159e34b385588d5ff3/LICENSE).

```text
Copyright (c) 2011 Ethan Schoonover

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in
all copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN
THE SOFTWARE.
```

### Ayu Dark / Mirage

Источник палитры: <https://github.com/ayu-theme/ayu-colors/blob/d461f02983546636bc6e1e0c48190fdb74036426/themes/dark.yaml>.
Второй вариант: <https://github.com/ayu-theme/ayu-colors/blob/d461f02983546636bc6e1e0c48190fdb74036426/themes/mirage.yaml>.
Лицензия upstream: [license](https://raw.githubusercontent.com/ayu-theme/ayu-colors/d461f02983546636bc6e1e0c48190fdb74036426/license).

```text
MIT License

Copyright (c) Konstantin Pschera <me@kons.ch> (kons.ch)

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

### Night Owl

Источник палитры: <https://github.com/sdras/night-owl-vscode-theme/blob/cc291eba7976b20d7c66bde6883c27b902196b07/themes/Night%20Owl-color-theme.json>.
Лицензия upstream: [LICENSE.md](https://raw.githubusercontent.com/sdras/night-owl-vscode-theme/cc291eba7976b20d7c66bde6883c27b902196b07/LICENSE.md).

```text
MIT License

Copyright (c) 2018 Sarah Drasner

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

### GitHub Dark (classic)

Источник палитры: <https://github.com/primer/github-vscode-theme/blob/cd78e5e4e7bcf132a6f428ae0f32264bb1b729cf/src/classic/colors.json>.
Лицензия upstream: [LICENSE](https://raw.githubusercontent.com/primer/github-vscode-theme/cd78e5e4e7bcf132a6f428ae0f32264bb1b729cf/LICENSE).

```text
MIT License

Copyright (c) 2020 Primer

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

### Catppuccin Frappé / Macchiato

Источник палитры: <https://github.com/catppuccin/palette/blob/07d02aa110ef9eb7e7427afca5c73ba9cf7f8ebd/palette.json>.
Лицензия upstream: [LICENSE](https://raw.githubusercontent.com/catppuccin/palette/07d02aa110ef9eb7e7427afca5c73ba9cf7f8ebd/LICENSE).

```text
MIT License

Copyright (c) 2021 Catppuccin

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

### Rosé Pine / Rosé Pine Moon / Rosé Pine Dawn

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

### Kanagawa Wave / Dragon

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
