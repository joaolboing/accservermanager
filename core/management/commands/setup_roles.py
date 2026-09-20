from django.core.management.base import BaseCommand
from django.contrib.auth.models import Group, Permission


class Command(BaseCommand):
    help = 'Create user role groups (Admin, Operator, Viewer)'

    def handle(self, *args, **options):
        admin_group, _ = Group.objects.get_or_create(name='Admin')
        operator_group, _ = Group.objects.get_or_create(name='Operator')
        viewer_group, _ = Group.objects.get_or_create(name='Viewer')

        admin_group.permissions.set(Permission.objects.all())

        self.stdout.write(self.style.SUCCESS('Roles created: Admin, Operator, Viewer'))
