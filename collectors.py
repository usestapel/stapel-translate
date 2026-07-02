"""Registry of translation-key collectors.

A collector is a zero-argument callable returning a stats dict (see
``error_collector`` / ``notification_collector``). The dashboard buttons
call the same functions directly; the ``collect_translations`` management
command runs every registered collector — projects can plug their own:

    from stapel_translate.collectors import register_collector
    register_collector("catalog", collect_catalog_keys)
"""

_registry = {
    # Dotted paths keep module import light; resolved on first run.
    "errors": "stapel_translate.error_collector.collect_error_keys_from_services",
    "notifications": "stapel_translate.notification_collector.collect_notification_keys",
}


def register_collector(name, collector):
    """Register a collector under *name* (callable or dotted path)."""
    _registry[name] = collector


def get_collectors():
    """{name: callable} for every registered collector."""
    from django.utils.module_loading import import_string

    resolved = {}
    for name, collector in _registry.items():
        if isinstance(collector, str):
            collector = import_string(collector)
        resolved[name] = collector
    return resolved
