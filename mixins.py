"""Shared view mixins for stapel_translate."""


class SerializerSeamMixin:
    """Expose request/response serializer classes as overridable seams.

    Views declare ``request_serializer_class`` and/or
    ``response_serializer_class`` and instantiate serializers through the
    getters, so downstream projects can swap a serializer by subclassing a
    view and overriding a single attribute (or getter) without copying any
    view logic.

    Views that use several distinct serializers across actions declare
    purpose-prefixed attributes (e.g. ``list_response_serializer_class``)
    with matching getters, keeping the same suffix convention.
    """

    request_serializer_class = None
    response_serializer_class = None

    def get_request_serializer_class(self):
        return self.request_serializer_class

    def get_response_serializer_class(self):
        return self.response_serializer_class
