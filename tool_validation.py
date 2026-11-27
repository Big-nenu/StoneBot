"""Validación de argumentos antes de tocar permisos, diario o ejecutores."""
import re

from jsonschema import SchemaError, ValidationError, validators
from referencing import Registry
from referencing.exceptions import Unresolvable


class InvalidToolArguments(ValueError):
    def __init__(self, field, expected, *, unavailable=False):
        self.field, self.expected, self.unavailable = field, expected, unavailable
        super().__init__(expected)


def validate_arguments(schema, arguments, *, decimal_fields=()):
    if not isinstance(arguments, dict):
        raise InvalidToolArguments("argumentos", "Se espera un objeto JSON.")
    normalized = arguments
    properties = schema.get("properties", {})
    try:
        validator = validators.validator_for(schema)
        validator.check_schema(schema)
        for field in decimal_fields:
            value = arguments.get(field)
            definition = properties.get(field)
            if (isinstance(definition, dict) and definition.get("type") == "integer" and isinstance(value, str)
                    and re.fullmatch(r"[0-9]{1,15}", value)):
                normalized = {**normalized, field: int(value)}
        validator(schema, registry=Registry()).validate(normalized)
    except ValidationError as exc:
        path = tuple(exc.absolute_path)
        field = path[0] if path else None
        if exc.validator == "required" and isinstance(exc.instance, dict):
            field = next((key for key in exc.validator_value if key not in exc.instance), field)
        if not isinstance(field, str) or field not in properties or not re.fullmatch(r"[A-Za-z_][\w-]{0,63}", field):
            field = "argumentos"
        constraint = str(exc.validator) if isinstance(exc.validator, str) else "esquema"
        allowed = ", ".join(key for key in list(properties)[:12] if re.fullmatch(r"[A-Za-z_][\w-]{0,63}", key))
        suggestion = f"Corrige '{field}' según la restricción {constraint} del esquema ofrecido."
        if allowed:
            suggestion += f" Campos del esquema: {allowed}."
        raise InvalidToolArguments(field, suggestion) from None
    except (SchemaError, TypeError, ValueError, Unresolvable, RecursionError) as exc:
        raise InvalidToolArguments("argumentos", "El esquema no se puede verificar localmente.", unavailable=True) from exc
    return normalized
