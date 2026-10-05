"""Experimental schema annotation trimming; does not modify evidence or constraints."""
from copy import deepcopy


def without_titles(schema):
    """Remove only JSON Schema title annotations, preserving property names.

    Do not recursively strip arbitrary dictionaries: a property, enum value or
    default object can itself have a meaningful key named ``title``.
    """
    result = deepcopy(schema)
    if isinstance(result, bool):
        return result
    result.pop('title', None)
    for key in ('$defs', 'definitions', 'properties', 'patternProperties', 'dependentSchemas'):
        if isinstance(result.get(key), dict):
            result[key] = {name: without_titles(value) for name, value in result[key].items()}
    for key in ('items', 'additionalProperties', 'unevaluatedProperties', 'contains',
                'propertyNames', 'not', 'if', 'then', 'else'):
        if isinstance(result.get(key), (dict, bool)):
            result[key] = without_titles(result[key])
    for key in ('allOf', 'anyOf', 'oneOf', 'prefixItems'):
        if isinstance(result.get(key), list):
            result[key] = [without_titles(value) for value in result[key]]
    return result


def trim_tool_schema_titles(context):
    result = dict(context)
    if 'available_tools' in context:
        result['available_tools'] = [
            {**tool, 'input_schema': without_titles(tool['input_schema'])}
            if 'input_schema' in tool else deepcopy(tool)
            for tool in context['available_tools']
        ]
    return result
