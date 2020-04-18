import collections
import datetime as dt

from bson import DBRef, ObjectId, Decimal128
from marshmallow import ValidationError, missing
from marshmallow import fields as ma_fields

# from .registerer import retrieve_document
from .document import DocumentImplementation
from .exceptions import NotRegisteredDocumentError
from .template import get_template
from .data_objects import Reference, List, Dict
from . import marshmallow_bonus as ma_bonus_fields
from .abstract import BaseField
from .i18n import gettext as _


__all__ = (
    # 'RawField',
    # 'MappingField',
    # 'TupleField',
    'StringField',
    'UUIDField',
    'NumberField',
    'IntegerField',
    'DecimalField',
    'BooleanField',
    'FloatField',
    'DateTimeField',
    'NaiveDateTimeField',
    'AwareDateTimeField',
    # 'TimeField',
    'DateField',
    # 'TimeDeltaField',
    'UrlField',
    'URLField',
    'EmailField',
    'StrField',
    'BoolField',
    'IntField',
    'DictField',
    'ListField',
    'ConstantField',
    # 'PluckField'
    'ObjectIdField',
    'ReferenceField',
    'GenericReferenceField',
    'EmbeddedField'
)


# Republish supported marshmallow fields


# class RawField(BaseField, ma_fields.Raw):
#     pass


class StringField(BaseField, ma_fields.String):
    pass


class UUIDField(BaseField, ma_fields.UUID):
    pass


class NumberField(BaseField, ma_fields.Number):
    pass


class IntegerField(BaseField, ma_fields.Integer):
    pass


class DecimalField(BaseField, ma_fields.Decimal):
    """
    .. warning::

        This field is only supported on MongoDB 3.4+.
        Using it on older versions will result in uncaught errors.
    """
    def _serialize_to_mongo(self, obj):
        return Decimal128(obj)

    def _deserialize_from_mongo(self, value):
        return value.to_decimal()


class BooleanField(BaseField, ma_fields.Boolean):
    pass


class FloatField(BaseField, ma_fields.Float):
    pass


def _round_to_millisecond(datetime):
    """Round a datetime to millisecond precision

    MongoDB stores datetimes with a millisecond precision.
    For consistency, use the same precision in the object representation.
    """
    microseconds = round(datetime.microsecond, -3)
    if microseconds == 1000000:
        return datetime.replace(microsecond=0) + dt.timedelta(seconds=1)
    return datetime.replace(microsecond=microseconds)


class DateTimeField(BaseField, ma_fields.DateTime):

    def _deserialize(self, value, attr, data, **kwargs):
        if isinstance(value, dt.datetime):
            ret = value
        else:
            ret = super()._deserialize(value, attr, data, **kwargs)
        return _round_to_millisecond(ret)


class NaiveDateTimeField(BaseField, ma_fields.NaiveDateTime):

    def _deserialize(self, value, attr, data, **kwargs):
        if isinstance(value, dt.datetime):
            ret = value
        else:
            ret = super()._deserialize(value, attr, data, **kwargs)
        return _round_to_millisecond(ret)


class AwareDateTimeField(BaseField, ma_fields.AwareDateTime):

    def _deserialize(self, value, attr, data, **kwargs):
        if isinstance(value, dt.datetime):
            ret = value
        else:
            ret = super()._deserialize(value, attr, data, **kwargs)
        return _round_to_millisecond(ret)

    def _deserialize_from_mongo(self, value):
        value = value.replace(tzinfo=dt.timezone.utc)
        if self.default_timezone is not None:
            value = value.astimezone(self.default_timezone)
        return value


# class TimeField(BaseField, ma_fields.Time):
#     pass


class DateField(BaseField, ma_fields.Date):
    """This field converts a date to a datetime to store it as a BSON Date"""

    def _deserialize(self, value, attr, data, **kwargs):
        if isinstance(value, dt.date):
            return value
        return super()._deserialize(value, attr, data)

    def _serialize_to_mongo(self, obj):
        return dt.datetime(obj.year, obj.month, obj.day)

    def _deserialize_from_mongo(self, value):
        return value.date()


# class TimeDeltaField(BaseField, ma_fields.TimeDelta):
#     pass


class UrlField(BaseField, ma_fields.Url):
    pass


class EmailField(BaseField, ma_fields.Email):
    pass


class ConstantField(BaseField, ma_fields.Constant):
    pass


class DictField(BaseField, ma_fields.Dict):

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        def cast_value_or_callable(key_field, value_field, value):
            if value is missing:
                return missing
            if callable(value):
                return lambda: Dict(key_field, value_field, value())
            return Dict(key_field, value_field, value)

        self.default = cast_value_or_callable(self.key_field, self.value_field, self.default)
        self.missing = cast_value_or_callable(self.key_field, self.value_field, self.missing)

    def _deserialize(self, value, attr, data, **kwargs):
        value = super()._deserialize(value, attr, data, **kwargs)
        return Dict(self.key_field, self.value_field, value)

    def _serialize_to_mongo(self, obj):
        if obj is None:
            return missing
        return {
            self.key_field.serialize_to_mongo(k) if self.key_field else k:
            self.value_field.serialize_to_mongo(v) if self.value_field else v
            for k, v in obj.items()
        }

    def _deserialize_from_mongo(self, value):
        if value:
            return Dict(
                self.key_field,
                self.value_field,
                {
                    self.key_field.deserialize_from_mongo(k) if self.key_field else k:
                    self.value_field.deserialize_from_mongo(v) if self.value_field else v
                    for k, v in value.items()
                }
            )
        return Dict(self.key_field, self.value_field)

    def as_marshmallow_field(self, params=None, mongo_world=False, **kwargs):
        # Overwrite default `as_marshmallow_field` to handle deserialization
        # difference (`_id` vs `id`)
        field_kwargs = self._extract_marshmallow_field_params(mongo_world)
        if params:
            inner_params = params.pop('params', None)
            field_kwargs.update(params)
        else:
            inner_params = None
        if self.value_field:
            inner_ma_schema = self.value_field.as_marshmallow_field(
                mongo_world=mongo_world, params=inner_params, **kwargs)
        else:
            inner_ma_schema = None
        return ma_fields.Dict(self.key_field, inner_ma_schema, **field_kwargs)

    def _required_validate(self, value):
        if value is missing or not hasattr(self.value_field, '_required_validate'):
            return
        required_validate = self.value_field._required_validate
        errors = collections.defaultdict(dict)
        for key, val in value.items():
            try:
                required_validate(val)
            except ValidationError as exc:
                errors[key]["value"] = exc.messages
        if errors:
            raise ValidationError(errors)


class ListField(BaseField, ma_fields.List):

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        def cast_value_or_callable(inner, value):
            if value is missing:
                return missing
            if callable(value):
                return lambda: List(inner, value())
            return List(inner, value)

        self.default = cast_value_or_callable(self.inner, self.default)
        self.missing = cast_value_or_callable(self.inner, self.missing)

    def _deserialize(self, value, attr, data, **kwargs):
        value = super()._deserialize(value, attr, data, **kwargs)
        return List(self.inner, value)

    def _serialize_to_mongo(self, obj):
        if obj is None:
            return missing
        return [self.inner.serialize_to_mongo(each) for each in obj]

    def _deserialize_from_mongo(self, value):
        if value:
            return List(
                self.inner,
                [self.inner.deserialize_from_mongo(each) for each in value]
            )
        return List(self.inner)

    def map_to_field(self, mongo_path, path, func):
        """Apply a function to every field in the schema
        """
        func(mongo_path, path, self.inner)
        if hasattr(self.inner, 'map_to_field'):
            self.inner.map_to_field(mongo_path, path, func)

    def as_marshmallow_field(self, params=None, mongo_world=False, **kwargs):
        # Overwrite default `as_marshmallow_field` to handle deserialization
        # difference (`_id` vs `id`)
        field_kwargs = self._extract_marshmallow_field_params(mongo_world)
        if params:
            inner_params = params.pop('params', None)
            field_kwargs.update(params)
        else:
            inner_params = None
        inner_ma_schema = self.inner.as_marshmallow_field(
            mongo_world=mongo_world, params=inner_params, **kwargs)
        return ma_fields.List(inner_ma_schema, **field_kwargs)

    def _required_validate(self, value):
        if value is missing or not hasattr(self.inner, '_required_validate'):
            return
        required_validate = self.inner._required_validate
        errors = {}
        for i, sub_value in enumerate(value):
            try:
                required_validate(sub_value)
            except ValidationError as exc:
                errors[i] = exc.messages
        if errors:
            raise ValidationError(errors)


# Aliases
URLField = UrlField
StrField = StringField
BoolField = BooleanField
IntField = IntegerField


class ObjectIdField(BaseField, ma_bonus_fields.ObjectId):
    pass


class ReferenceField(BaseField, ma_bonus_fields.Reference):

    def __init__(self, document, *args, reference_cls=Reference, **kwargs):
        """
        :param document: Can be a :class:`umongo.embedded_document.DocumentTemplate`,
            another instance's :class:`umongo.embedded_document.DocumentImplementation` or
            the embedded document class name.
        """
        super().__init__(*args, **kwargs)
        # TODO : check document_cls is implementation or string
        self.reference_cls = reference_cls
        # Can be the Template, Template's name or another Implementation
        if not isinstance(document, str):
            self.document = get_template(document)
        else:
            self.document = document
        self._document_cls = None
        # Avoid importing multiple times
        from .document import DocumentImplementation
        self._document_implementation_cls = DocumentImplementation

    @property
    def document_cls(self):
        """
        Return the instance's :class:`umongo.embedded_document.DocumentImplementation`
        implementing the `document` attribute.
        """
        if not self._document_cls:
            self._document_cls = self.instance.retrieve_document(self.document)
        return self._document_cls

    def _deserialize(self, value, attr, data, **kwargs):
        if value is None:
            return None
        if isinstance(value, DBRef):
            if self._document_cls.collection.name != value.collection:
                raise ValidationError(_("DBRef must be on collection `{collection}`.").format(
                    self._document_cls.collection.name))
            value = value.id
        elif isinstance(value, Reference):
            if value.document_cls != self.document_cls:
                raise ValidationError(_("`{document}` reference expected.").format(
                    document=self.document_cls.__name__))
            if not isinstance(value, self.reference_cls):
                value = self.reference_cls(value.document_cls, value.pk)
            return value
        elif isinstance(value, self.document_cls):
            if not value.is_created:
                raise ValidationError(
                    _("Cannot reference a document that has not been created yet."))
            value = value.pk
        elif isinstance(value, self._document_implementation_cls):
            raise ValidationError(_("`{document}` reference expected.").format(
                document=self.document_cls.__name__))
        value = super()._deserialize(value, attr, data, **kwargs)
        return self.reference_cls(self.document_cls, value)

    def _serialize_to_mongo(self, obj):
        return obj.pk

    def _deserialize_from_mongo(self, value):
        return self.reference_cls(self.document_cls, value)

    def as_marshmallow_field(self, params=None, mongo_world=False, **kwargs):
        # Overwrite default `as_marshmallow_field` to handle deserialization
        # difference (`_id` vs `id`)
        field_kwargs = self._extract_marshmallow_field_params(mongo_world)
        if params:
            field_kwargs.update(params)
        return ma_bonus_fields.Reference(mongo_world=mongo_world, **field_kwargs)


class GenericReferenceField(BaseField, ma_bonus_fields.GenericReference):

    def __init__(self, *args, reference_cls=Reference, **kwargs):
        super().__init__(*args, **kwargs)
        self.reference_cls = reference_cls
        self._document_implementation_cls = DocumentImplementation

    def _document_cls(self, class_name):
        try:
            return self.instance.retrieve_document(class_name)
        except NotRegisteredDocumentError:
            raise ValidationError(_('Unknown document `{document}`.').format(
                document=class_name))

    def _serialize(self, value, attr, obj):
        if value is None:
            return None
        return {'id': str(value.pk), 'cls': value.document_cls.__name__}

    def _deserialize(self, value, attr, data, **kwargs):
        if value is None:
            return None
        if isinstance(value, Reference):
            if not isinstance(value, self.reference_cls):
                value = self.reference_cls(value.document_cls, value.pk)
            return value
        if isinstance(value, self._document_implementation_cls):
            if not value.is_created:
                raise ValidationError(
                    _("Cannot reference a document that has not been created yet."))
            return self.reference_cls(value.__class__, value.pk)
        if isinstance(value, dict):
            if value.keys() != {'cls', 'id'}:
                raise ValidationError(_("Generic reference must have `id` and `cls` fields."))
            try:
                _id = ObjectId(value['id'])
            except ValueError:
                raise ValidationError(_("Invalid `id` field."))
            document_cls = self._document_cls(value['cls'])
            return self.reference_cls(document_cls, _id)
        raise ValidationError(_("Invalid value for generic reference field."))

    def _serialize_to_mongo(self, obj):
        return {'_id': obj.pk, '_cls': obj.document_cls.__name__}

    def _deserialize_from_mongo(self, value):
        document_cls = self._document_cls(value['_cls'])
        return self.reference_cls(document_cls, value['_id'])

    def as_marshmallow_field(self, params=None, mongo_world=False, **kwargs):
        # Overwrite default `as_marshmallow_field` to handle deserialization
        # difference (`_id` vs `id`)
        field_kwargs = self._extract_marshmallow_field_params(mongo_world)
        if params:
            field_kwargs.update(params)
        return ma_bonus_fields.GenericReference(mongo_world=mongo_world, **field_kwargs)


class EmbeddedField(BaseField, ma_fields.Nested):

    def __init__(self, embedded_document, *args, **kwargs):
        """
        :param embedded_document: Can be a
            :class:`umongo.embedded_document.EmbeddedDocumentTemplate`,
            another instance's :class:`umongo.embedded_document.EmbeddedDocumentImplementation`
            or the embedded document class name.
        """
        # Don't need to pass `nested` attribute given it is overloaded
        super().__init__(None, *args, **kwargs)
        # Try to retrieve the template if possible for consistency
        if not isinstance(embedded_document, str):
            self.embedded_document = get_template(embedded_document)
        else:
            self.embedded_document = embedded_document
        self._embedded_document_cls = None

    @property
    def nested(self):
        # Overload `nested` attribute to be able to fetch it lazily
        return self.embedded_document_cls.Schema

    @nested.setter
    def nested(self, value):
        pass

    @property
    def embedded_document_cls(self):
        """
        Return the instance's :class:`umongo.embedded_document.EmbeddedDocumentImplementation`
        implementing the `embedded_document` attribute.
        """
        if not self._embedded_document_cls:
            self._embedded_document_cls = self.instance.retrieve_embedded_document(
                self.embedded_document)
        return self._embedded_document_cls

    def _serialize(self, value, attr, obj):
        if value is None:
            return None
        return value.dump()

    def _deserialize(self, value, attr, data, **kwargs):
        embedded_document_cls = self.embedded_document_cls
        if isinstance(value, embedded_document_cls):
            return value
        if not isinstance(value, dict):
            raise ValidationError({'_schema': ['Invalid input type.']})
        # Handle inheritance deserialization here using `cls` field as hint
        if embedded_document_cls.opts.offspring and 'cls' in value:
            to_use_cls_name = value.pop('cls')
            if not any(o for o in embedded_document_cls.opts.offspring
                       if o.__name__ == to_use_cls_name):
                raise ValidationError(_('Unknown document `{document}`.').format(
                    document=to_use_cls_name))
            try:
                to_use_cls = embedded_document_cls.opts.instance.retrieve_embedded_document(
                    to_use_cls_name)
            except NotRegisteredDocumentError as exc:
                raise ValidationError(str(exc))
            return to_use_cls(**value)
        return embedded_document_cls(**value)

    def _serialize_to_mongo(self, obj):
        return obj.to_mongo()

    def _deserialize_from_mongo(self, value):
        return self.embedded_document_cls.build_from_mongo(value)

    def _validate_missing(self, value):
        # Overload default to handle recursive check
        super()._validate_missing(value)
        errors = {}
        if value is missing:
            def get_sub_value(_):
                return missing
        elif isinstance(value, dict):
            # value is a dict for deserialization
            def get_sub_value(key):
                return value.get(key, missing)
        elif isinstance(value, self.embedded_document_cls):
            # value is a valid EmbeddedDocument
            def get_sub_value(key):
                return value._data.get(key)
        else:
            # value is invalid, just return and let `_deserialize`
            # raises an error about this
            return
        for name, field in self.embedded_document_cls.schema.fields.items():
            sub_value = get_sub_value(name)
            # `_validate_missing` doesn't check for required fields here, so we
            # can safely skip missing values
            if sub_value is missing:
                continue
            try:
                field._validate_missing(sub_value)
            except ValidationError as exc:
                errors[name] = exc.messages
        if errors:
            raise ValidationError(errors)

    def map_to_field(self, mongo_path, path, func):
        """Apply a function to every field in the schema"""
        for name, field in self.embedded_document_cls.schema.fields.items():
            cur_path = '%s.%s' % (path, name)
            cur_mongo_path = '%s.%s' % (mongo_path, field.attribute or name)
            func(cur_mongo_path, cur_path, field)
            if hasattr(field, 'map_to_field'):
                field.map_to_field(cur_mongo_path, cur_path, func)

    def as_marshmallow_field(self, params=None, mongo_world=False, **kwargs):
        # Overwrite default `as_marshmallow_field` to handle nesting
        field_kwargs = self._extract_marshmallow_field_params(mongo_world)
        if params:
            nested_params = params.pop('params', None)
            nested_meta = params.pop('meta', None)
            field_kwargs.update(params)
        else:
            nested_params = None
            nested_meta = None
        schema_kwargs = {k: v for k, v in kwargs.items()
                         if k in ('base_schema_cls', 'check_unknown_fields')}
        nested_ma_schema = self._embedded_document_cls.schema.as_marshmallow_schema(
            params=nested_params, mongo_world=mongo_world, meta=nested_meta, **schema_kwargs)
        return ma_fields.Nested(nested_ma_schema, **field_kwargs)

    def _required_validate(self, value):
        if value is not missing:
            value.required_validate()
