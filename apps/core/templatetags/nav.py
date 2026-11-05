from django import template

register = template.Library()

ACTIVE = (
    'bg-emerald-50 font-medium text-emerald-800 '
    'dark:bg-emerald-950 dark:text-emerald-300'
)
IDLE = (
    'text-stone-600 hover:bg-stone-100 dark:text-stone-300 '
    'dark:hover:bg-stone-800'
)


@register.simple_tag(takes_context=True)
def nav_class(context, prefix):
    path = context['request'].path
    active = path == '/' if prefix == '/' else path.startswith(prefix)
    return ACTIVE if active else IDLE
