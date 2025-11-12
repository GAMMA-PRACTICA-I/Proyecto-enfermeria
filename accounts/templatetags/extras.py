# accounts/templatetags/extras.py
from django import template

register = template.Library()


@register.filter(name="get_item")
def get_item(d, key):
    """
    Obtiene d[key] de forma segura (para dicts).
    Uso en template: {{ dict|get_item:"clave" }}
    """
    try:
        if isinstance(d, dict):
            return d.get(key)
    except Exception:
        pass
    return None


@register.filter(name="getattr")
def getattr_filter(obj, name):
    """
    getattr(obj, name) seguro, retorna None si no existe.
    Uso en template: {{ objeto|getattr:"campo" }}
    """
    try:
        return getattr(obj, name, None)
    except Exception:
        return None


@register.filter(name="split")
def split(value, sep=","):
    """
    Divide un string por el separador dado.
    Uso en template: {% for parte in "a,b,c"|split:"," %}...{% endfor %}
    """
    if value is None:
        return []
    return str(value).split(sep)
