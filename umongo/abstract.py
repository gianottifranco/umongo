from marshmallow import (Schema as MaSchema, fields as ma_fields,
                         validate as ma_validate, missing, EXCLUDE)

from .i18n import gettext as _, N_
from .marshmallow_bonus import schema_from_umongo_get_attribute


__all__ = ('BaseSchema', 'BaseField', 'BaseValidator', 'BaseDataObject')


class I18nErrorDict(dict):
    def __getitem__(self, name):
        raw_msg = dict.__getitem__(self, name)
        return _(raw_msg)


class BaseSchema(MaSchema):
    """
    All schema used in umongo should inherit from this base schema
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.error_messages = I18nErrorDict(self.error_messages)

    _marshmallow_schemas_cache = {}

    def map_to_field(self, func):
        """
        Apply a function to every field in the schema

        >>> def func(mongo_path, path, field):
        ...     pass
        """
        for name, field in self.fields.items():
            mongo_path = field.attribute or name
            func(mongo_path, name, field)
            if hasattr(field, 'map_to_field'):
                field.map_to_field(mongo_path, name, func)

    def as_marshmallow_schema(self, params=None, base_schema_cls=MaSchema,
                              check_unknown_fields=True, mongo_world=False, meta=None):
        """
        Return a pure-marshmallow version of this schema class.

        :param params: Per-field dict to pass parameters to their field creation.
        :param base_schema_cls: Class the schema will inherit from (
            default: :class:`marshmallow.Schema`).
        :param check_unknown_fields: Unknown fields are considered as errors (default: True).
        :param mongo_world: If True the schema will work against the mongo world
            instead of the OO world (default: False).
        :param meta: Optional dict with attributes for the schema's Meta class.
        """
        params = params or {}
        meta = meta or {}
        # Use hashable parameters as cache dict key and dict parameters for manual comparison
        cache_key = (self.__class__, base_schema_cls, check_unknown_fields, mongo_world)
        cache_modifiers = (params, meta)
        if cache_key in self._marshmallow_schemas_cache:
            for modifiers, ma_schema in self._marshmallow_schemas_cache[cache_key]:
                if modifiers == cache_modifiers:
                    return ma_schema
        nmspc = {
            name: field.as_marshmallow_field(
                params=params.get(name),
                base_schema_cls=base_schema_cls,
                check_unknown_fields=check_unknown_fields,
                mongo_world=mongo_world)
            for name, field in self.fields.items()
        }
        name = 'Marshmallow%s' % type(self).__name__
        if not check_unknown_fields:
            meta.setdefault('unknown', EXCLUDE)
        # By default OO world returns `missing` fields as `None`,
        # disable this behavior here to let marshmallow deal with it
        if not mongo_world:
            nmspc['get_attribute'] = schema_from_umongo_get_attribute
        if meta:
            nmspc['Meta'] = type('Meta', (base_schema_cls.Meta,), meta)
        m_schema = type(name, (base_schema_cls, ), nmspc)
        # Add i18n support to the schema
        # We can't use I18nErrorDict here because __getitem__ is not called
        # when error_messages is updated with _default_error_messages.
        m_schema._default_error_messages = {
            k: _(v) for k, v in m_schema._default_error_messages.items()}
        self._marshmallow_schemas_cache.setdefault(cache_key, []).append(
            (cache_modifiers, m_schema))
        return m_schema


class BaseField(ma_fields.Field):
    """
    All fields used in umongo should inherit from this base field.

    ==============================   ===============
    Enabled flags                    resulting index
    ==============================   ===============
    <no flags>
    allow_none
    required
    required, allow_none
    required, unique, allow_none     unique
    unique                           unique, sparse
    unique, required                 unique
    unique, allow_none               unique, sparse
    ==============================   ===============

    .. note:: Even with allow_none flag, the unique flag will refuse duplicated
    `null` value (consider unsetting the field with `del` instead)
    """

    default_error_messages = {
        'unique': N_('Field value must be unique.'),
        'unique_compound': N_('Values of fields {fields} must be unique together.')
    }

    MARSHMALLOW_ARGS_PREFIX = 'marshmallow_'

    def __init__(self, *args, io_validate=None, unique=False, instance=None, **kwargs):
        if 'missing' in kwargs:
            raise RuntimeError("uMongo doesn't use `missing` argument, use `default` "
                "instead and `marshmallow_missing`/`marshmallow_default` "
                "to tell `as_marshmallow_field` to use a custom value when "
                "generating pure Marshmallow field.")
        if 'default' in kwargs:
            kwargs['missing'] = kwargs['default']

        # Store attributes prefixed with marshmallow_ to use them when
        # creating pure marshmallow Schema
        self._ma_kwargs = {
            key[len(self.MARSHMALLOW_ARGS_PREFIX):]: val
            for key, val in kwargs.items()
            if key.startswith(self.MARSHMALLOW_ARGS_PREFIX)
        }
        kwargs = {
            key: val
            for key, val in kwargs.items()
            if not key.startswith(self.MARSHMALLOW_ARGS_PREFIX)
        }

        super().__init__(*args, **kwargs)

        self._ma_kwargs.setdefault('missing', self.default)
        self._ma_kwargs.setdefault('default', self.default)

        # Overwrite error_messages to handle i18n translation
        self.error_messages = I18nErrorDict(self.error_messages)
        # `io_validate` will be run after `io_validate_resursive`
        # only if this one doesn't returns errors. This is useful for
        # list and embedded fields.
        self.io_validate = io_validate
        self.io_validate_recursive = None
        self.unique = unique
        self.instance = instance

    def __repr__(self):
        return ('<fields.{ClassName}(default={self.default!r}, '
                'attribute={self.attribute!r}, '
                'validate={self.validate}, required={self.required}, '
                'load_only={self.load_only}, dump_only={self.dump_only}, '
                'marshmallow_missing={self.marshmallow_missing}, '
                'marshmallow_default={self.marshmallow_default}, '
                'allow_none={self.allow_none}, '
                'error_messages={self.error_messages}, '
                'io_validate={self.io_validate}, '
                'io_validate_recursive={self.io_validate_recursive}, '
                'unique={self.unique}, '
                'instance={self.instance})>'
                .format(ClassName=self.__class__.__name__, self=self))

    def _validate_missing(self, value):
        # Overwrite marshmallow.Field._validate_missing given it also checks
        # for missing required fields (this is done at commit time in umongo
        # using `DataProxy.required_validate`).
        if value is None and getattr(self, 'allow_none', False) is False:
            self.fail('null')

    def serialize_to_mongo(self, obj):
        if obj is None and getattr(self, 'allow_none', False) is True:
            return None
        if obj is missing:
            return missing
        return self._serialize_to_mongo(obj)

    # def serialize_to_mongo_update(self, path, obj):
    #     return self._serialize_to_mongo(attr, obj=obj, update=update)

    def deserialize_from_mongo(self, value):
        if value is None and getattr(self, 'allow_none', False) is True:
            return None
        return self._deserialize_from_mongo(value)

    def _serialize_to_mongo(self, obj):
        return obj

    def _deserialize_from_mongo(self, value):
        return value

    def translate_query(self, key, query):
        return {self.attribute or key: query}

    def _extract_marshmallow_field_params(self, mongo_world):
        params = {
            attribute: getattr(self, attribute)
            for attribute in (
                'validate', 'required', 'allow_none',
                'load_only', 'dump_only', 'error_messages'
            )
        }
        if mongo_world and self.attribute:
            params['attribute'] = self.attribute

        # Override uMongo attributes with marshmallow_ prefixed attributes
        params.update(self._ma_kwargs)

        params.update(self.metadata)
        return params

    def as_marshmallow_field(self, params=None, mongo_world=False, **kwargs):
        """
        Return a pure-marshmallow version of this field.

        :param params: Additional parameters passed to the marshmallow field
            class constructor.
        :param mongo_world: If True the field will work against the mongo world
            instead of the OO world (default: False)
        """
        field_kwargs = self._extract_marshmallow_field_params(mongo_world)
        if params:
            field_kwargs.update(params)
        # Retrieve the marshmallow class we inherit from
        for m_class in type(self).mro():
            if (not issubclass(m_class, BaseField) and
                    issubclass(m_class, ma_fields.Field)):
                m_field = m_class(**field_kwargs)
                # Add i18n support to the field
                m_field.error_messages = I18nErrorDict(m_field.error_messages)
                return m_field
        # Cannot escape the loop given BaseField itself inherits marshmallow's Field


class BaseValidator(ma_validate.Validator):
    """
    All validators in umongo should inherit from this base validator.
    """

    def __init__(self, *args, **kwargs):
        self._error = None
        super().__init__(*args, **kwargs)

    @property
    def error(self):
        return _(self._error)

    @error.setter
    def error(self, value):
        self._error = value


class BaseDataObject:
    """
    All data objects in umongo should inherit from this base data object.
    """

    def is_modified(self):
        raise NotImplementedError()

    def clear_modified(self):
        raise NotImplementedError()

    @classmethod
    def build_from_mongo(cls, data):
        doc = cls()
        doc.from_mongo(data)
        return doc

    def from_mongo(self, data):
        return self(data)

    def to_mongo(self, update=False):
        return self

    def dump(self):
        return self
