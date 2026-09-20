from django.shortcuts import redirect
from django.contrib.auth.decorators import login_required

@login_required
def home(request):
    if request.user.is_superuser or request.user.groups.filter(name__in=['Admin', 'Operator']).exists():
        return redirect('/instances')
    return redirect('/results/')
