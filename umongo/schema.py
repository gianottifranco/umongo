"""Schema used in Document"""
from .abstract import BaseSchema
from .i18n import gettext as _

from .marshmallow_bonus import schema_from_umongo_get_attribute


__all__ = (
    'Schema',
)


class Schema(BaseSchema):
    """Schema used in Document"""

    _marshmallow_schemas_cache = {}

    def as_marshmallow_schema(self, *, mongo_world=False):
        """
        Return a pure-marshmallow version of this schema class.

        :param mongo_world: If True the schema will work against the mongo world
            instead of the OO world (default: False).
        """
        # Use a cache to avoid generating several times the same schema
        cache_key = (self.__class__, self.MA_BASE_SCHEMA_CLS, mongo_world)
        if cache_key in self._marshmallow_schemas_cache:
            return self._marshmallow_schemas_cache[cache_key]

        # Create schema if not found in cache
        nmspc = {
            name: field.as_marshmallow_field(mongo_world=mongo_world)
            for name, field in self.fields.items()
        }
        name = 'Marshmallow%s' % type(self).__name__
        # By default OO world returns `missing` fields as `None`,
        # disable this behavior here to let marshmallow deal with it
        if not mongo_world:
            nmspc['get_attribute'] = schema_from_umongo_get_attribute
        m_schema = type(name, (self.MA_BASE_SCHEMA_CLS, ), nmspc)
        # Add i18n support to the schema
        # We can't use I18nErrorDict here because __getitem__ is not called
        # when error_messages is updated with _default_error_messages.
        m_schema._default_error_messages = {
            k: _(v) for k, v in m_schema._default_error_messages.items()}
        self._marshmallow_schemas_cache[cache_key] = m_schema
        return m_schema
