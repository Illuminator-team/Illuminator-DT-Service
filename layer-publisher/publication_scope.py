MODEL_PUBLICATION_ORDER = (
    "pc6",
    "pv",
    "grid",
    "wind",
    "heat",
    "ev",
    "consumption",
)


def parse_publish_models(raw_value: str | None) -> tuple[str, ...]:
    """Return a validated startup publication scope in canonical order."""
    if raw_value is None or not raw_value.strip():
        return MODEL_PUBLICATION_ORDER

    requested = [
        value.strip().lower() for value in raw_value.split(",") if value.strip()
    ]
    if not requested:
        raise ValueError("PUBLISH_MODELS must name at least one model or 'all'")

    if "all" in requested:
        if len(requested) != 1:
            raise ValueError("PUBLISH_MODELS cannot combine 'all' with model names")
        return MODEL_PUBLICATION_ORDER

    unknown = sorted(set(requested) - set(MODEL_PUBLICATION_ORDER))
    if unknown:
        valid_values = ", ".join((*MODEL_PUBLICATION_ORDER, "all"))
        raise ValueError(
            "PUBLISH_MODELS contains unknown model(s): "
            f"{', '.join(unknown)}. Valid values: {valid_values}"
        )

    requested_set = set(requested)
    return tuple(
        model for model in MODEL_PUBLICATION_ORDER if model in requested_set
    )
