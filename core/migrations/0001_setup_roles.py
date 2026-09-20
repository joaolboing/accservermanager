from django.db import migrations


def create_roles(apps, schema_editor):
    Group = apps.get_model('auth', 'Group')
    User = apps.get_model('auth', 'User')
    Permission = apps.get_model('auth', 'Permission')

    admin_group, _ = Group.objects.get_or_create(name='Admin')
    Group.objects.get_or_create(name='Operator')
    Group.objects.get_or_create(name='Viewer')

    admin_group.permissions.set(Permission.objects.all())

    for user in User.objects.filter(is_superuser=True):
        user.groups.add(admin_group)


def remove_roles(apps, schema_editor):
    Group = apps.get_model('auth', 'Group')
    Group.objects.filter(name__in=['Admin', 'Operator', 'Viewer']).delete()


class Migration(migrations.Migration):

    dependencies = [
        ('auth', '0001_initial'),
    ]

    operations = [
        migrations.RunPython(create_roles, remove_roles),
    ]
