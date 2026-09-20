from django import template

register = template.Library()


@register.simple_tag(takes_context=True)
def user_is_admin(context):
    user = context['request'].user
    return user.is_superuser or user.groups.filter(name='Admin').exists()


@register.simple_tag(takes_context=True)
def user_is_operator(context):
    user = context['request'].user
    return user.groups.filter(name='Operator').exists()


@register.simple_tag(takes_context=True)
def user_is_viewer(context):
    user = context['request'].user
    return user.groups.filter(name='Viewer').exists()


@register.simple_tag(takes_context=True)
def can_edit(context):
    user = context['request'].user
    return user.is_superuser or user.groups.filter(name__in=['Admin', 'Operator']).exists()


@register.simple_tag(takes_context=True)
def can_manage(context):
    user = context['request'].user
    return user.is_superuser or user.groups.filter(name='Admin').exists()
