import json

from django import template
from decouple import config

register = template.Library()

CURRENCY = config('MTN_CURRENCY', default='')


@register.filter
def money(value):
    try:
        amount = f"{float(value or 0):,.2f}"
    except (TypeError, ValueError):
        return value
    return f"{CURRENCY} {amount}".strip()


@register.filter
def status_class(status):
    return {
        'SUCCESSFUL': 'success',
        'FAILED': 'failed',
        'PENDING': 'pending',
    }.get(status, 'unknown')


@register.filter
def pretty_json(value):
    """Indent a JSON string for display; return it unchanged if it isn't JSON."""
    try:
        return json.dumps(json.loads(value), indent=2)
    except (TypeError, ValueError):
        return value
