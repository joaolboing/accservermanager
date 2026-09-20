from django.contrib.auth.models import Group, User
from django.db.models.signals import post_save
from django.dispatch import receiver


@receiver(post_save, sender=User)
def assign_admin_group(sender, instance, **kwargs):
    if instance.is_superuser:
        group, _ = Group.objects.get_or_create(name='Admin')
        instance.groups.add(group)
