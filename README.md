# stapel-translate

[![CI](https://github.com/usestapel/stapel-translate/actions/workflows/ci.yml/badge.svg)](https://github.com/usestapel/stapel-translate/actions/workflows/ci.yml)
[![codecov](https://codecov.io/gh/usestapel/stapel-translate/graph/badge.svg)](https://codecov.io/gh/usestapel/stapel-translate)

> AI-powered content translation — multilingual support, LLM routing (Anthropic/OpenAI)

Part of the [Stapel framework](https://github.com/usestapel) — composable Django apps for building production-grade platforms.

## Installation

```bash
pip install stapel-translate
```

## Quick start

```python
# settings.py
INSTALLED_APPS = [
    ...
    'stapel_translate',
]
```

## Bus events

### Emits
| `translations.changed` | [schema](schemas/emits/translations.changed.json) | One or more translation keys were updated for a language. |

### Consumes
| `user.deleted` | [schema](schemas/consumes/user.deleted.json) |
| `user.deletion_initiated` | [schema](schemas/consumes/user.deletion_initiated.json) |

## License

MIT — see [LICENSE](LICENSE)
