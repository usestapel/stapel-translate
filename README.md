# stapel-translate

[![CI](https://img.shields.io/github/actions/workflow/status/usestapel/stapel-translate/ci.yml?branch=main&logo=github&label=CI)](https://github.com/usestapel/stapel-translate/actions/workflows/ci.yml?query=branch%3Amain)
[![coverage](https://img.shields.io/codecov/c/github/usestapel/stapel-translate?branch=main&logo=codecov&label=coverage)](https://app.codecov.io/gh/usestapel/stapel-translate)
[![pypi](https://img.shields.io/pypi/v/stapel-translate?logo=pypi&logoColor=white&label=pypi)](https://pypi.org/project/stapel-translate/)
[![downloads](https://static.pepy.tech/badge/stapel-translate/month)](https://pepy.tech/project/stapel-translate)
[![python](https://img.shields.io/pypi/pyversions/stapel-translate?logo=python&logoColor=white)](https://pypi.org/project/stapel-translate/)
[![license](https://img.shields.io/github/license/usestapel/stapel-translate)](https://github.com/usestapel/stapel-translate/blob/main/LICENSE)
[![llms.txt](https://img.shields.io/badge/llms.txt-blue)](https://github.com/usestapel/stapel-translate/blob/main/docs/llms.txt)

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
