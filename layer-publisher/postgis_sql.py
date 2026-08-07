MULTIPOLYGON_EXPRESSION = (
    "ST_Multi(ST_CollectionExtract(ST_MakeValid("
    "ST_SetSRID(ST_GeomFromGeoJSON(%s),4326)),3))"
)


def values_template(scalar_value_count: int) -> str:
    """Build one execute_values row with an explicitly balanced geometry expression."""
    if scalar_value_count < 1:
        raise ValueError("scalar_value_count must be positive")
    scalar_placeholders = ",".join(["%s"] * scalar_value_count)
    return f"({scalar_placeholders},{MULTIPOLYGON_EXPRESSION})"
