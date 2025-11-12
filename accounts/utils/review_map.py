def build_prev_map(ficha):
    """
    Retorna un dict plano {field_key: {"status": ..., "notes": ...}}
    a partir de StudentFieldReview de la ficha.
    """
    out = {}
    qs = getattr(ficha, "field_reviews", None)
    if not qs:
        return out
    for fr in qs.all():
        out[fr.field_key] = {"status": fr.status, "notes": fr.notes or ""}
    return out
