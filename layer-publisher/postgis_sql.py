MULTIPOLYGON_EXPRESSION = (
    "ST_Multi(ST_CollectionExtract(ST_MakeValid("
    "ST_SetSRID(ST_GeomFromGeoJSON(%s),4326)),3))"
)

MULTILINESTRING_EXPRESSION = (
    "ST_Multi(ST_CollectionExtract(ST_MakeValid("
    "ST_SetSRID(ST_GeomFromGeoJSON(%s),4326)),2))"
)

POINT_EXPRESSION = (
    "ST_CollectionExtract(ST_MakeValid("
    "ST_SetSRID(ST_GeomFromGeoJSON(%s),4326)),1)"
)


def geometry_values_template(scalar_value_count: int, geometry_expression: str) -> str:
    if scalar_value_count < 1:
        raise ValueError("scalar_value_count must be positive")
    scalar_placeholders = ",".join(["%s"] * scalar_value_count)
    return f"({scalar_placeholders},{geometry_expression})"


def values_template(scalar_value_count: int) -> str:
    """Build one execute_values row with an explicitly balanced geometry expression."""
    return geometry_values_template(scalar_value_count, MULTIPOLYGON_EXPRESSION)


def multiline_values_template(scalar_value_count: int) -> str:
    return geometry_values_template(scalar_value_count, MULTILINESTRING_EXPRESSION)


def point_values_template(scalar_value_count: int) -> str:
    return geometry_values_template(scalar_value_count, POINT_EXPRESSION)
