import os, shutil, json, time, string, glob

from django.contrib.auth.decorators import login_required
from django.http import HttpResponse, HttpResponseRedirect, Http404
from django.template import loader
from django.contrib import messages

from random_word import RandomWords

from pathlib import Path

from instances.Executor import Executor
from instances.InstanceForm import InstanceForm

try: r = RandomWords()
except: r = None

from accservermanager import settings


# the server process execution threads
executors = {}


# resources a running instance uses and can be viewed/downloaded
# format is (path,label,text), see instance.html
resources = [
    ('stdout',  "Latest stdout", "Download full"),
    ('stderr',  "Latest stderr", "Download full"),
    ('serverlog',  "Server log", "Download full"),
    ('configuration',  "configuration.json", "Download"),
    ('event',  "event.json", "Download"),
    ('settings',  "settings.json", "Download"),
    ('assistRules',  "assistRules.json", "Download"),
    ('eventRules',  "eventRules.json", "Download"),
]

@login_required
def instance(request, name):
    if name not in executors: return HttpResponseRedirect('/instances')
    template = loader.get_template('instances/instance.html')

    path = request.path
    if path[0] == '/': path = path[1:]
    if path[-1] == '/':path = path[:-1]
    path = path.split('/')

    live = [dict(path=r[0], label=r[1], text=r[2], update=True)
            for r in resources if r[0] in ('stdout', 'stderr', 'serverlog')]
    configs = [dict(path=r[0], label=r[1], text=r[2], update=False)
               for r in resources if r[0] not in ('stdout', 'stderr', 'serverlog')]

    return HttpResponse(template.render(
        {'path': [(j, '/'+'/'.join(path[:i+1])) for i,j in enumerate(path)],
         'name': name,
         'executor': executors[name],
         'live': live,
         'configs': configs,
         'resources': [dict(path=r[0], label=r[1], text=r[2], update=r[0] in ['stdout','stderr','serverlog']) for r in resources]},
        request))


@login_required
def stdout(request, name):
    if 'lines' not in request.POST:
        return download(executors[name].stdout)
    return log(executors[name].stdout, int(request.POST['lines']))


@login_required
def stderr(request, name):
    if 'lines' not in request.POST:
        return download(executors[name].stderr)
    return log(executors[name].stderr, int(request.POST['lines']))


@login_required
def serverlog(request, name):
    if 'lines' not in request.POST:
        return download(executors[name].serverlog)
    return log(executors[name].serverlog, int(request.POST['lines']))


@login_required
def download_configuration_file(request, name):
    f = os.path.join(settings.INSTANCES, name, 'cfg', 'configuration.json')
    return download(f, content_type='text/json')


@login_required
def download_event_file(request, name):
    f = os.path.join(settings.INSTANCES, name, 'cfg', 'event.json')
    return download(f, content_type='text/json')


@login_required
def download_settings_file(request, name):
    f = os.path.join(settings.INSTANCES, name, 'cfg', 'settings.json')
    return download(f, content_type='text/json')


@login_required
def download_assistRules_file(request, name):
    f = os.path.join(settings.INSTANCES, name, 'cfg', 'assistRules.json')
    return download(f, content_type='text/json')


@login_required
def download_eventRules_file(request, name):
    f = os.path.join(settings.INSTANCES, name, 'cfg', 'eventRules.json')
    return download(f, content_type='text/json')


# https://stackoverflow.com/questions/136168/get-last-n-lines-of-a-file-with-python-similar-to-tail
def tail(f, n=10):
    assert n >= 0
    pos, lines = n+1, []
    while len(lines) <= n:
        try:
            f.seek(-pos, 2)
        except IOError:
            f.seek(0)
            break
        finally:
            lines = list(f)
        pos *= 2
    return lines[-n:]


def log(_f, n):
    if _f is not None and os.path.isfile(_f):
        with open(_f, 'r', encoding='latin-1') as fh:
            return HttpResponse(tail(fh, n))
    raise Http404


def download(_f, content_type="text/plain"):
    if _f is not None and os.path.isfile(_f):
        with open(_f, 'r', encoding='utf-16') as fh:
            response = HttpResponse(fh.read(), content_type=content_type)
            response['Content-Disposition'] = 'inline; filename=' + os.path.basename(_f)
            return response
    raise Http404


@login_required
def delete(request, name):
    if name in executors:
        if not executors[name].is_alive():
            shutil.rmtree(executors[name].instanceDir)
            executors.pop(name)

    return HttpResponse(json.dumps({'success': True}),
                        content_type='application/json')


@login_required
def stop(request, name):
    """ handle stop request from client """
    global executors
    if name in executors and executors[name].stop.value != 1:
        executors[name].stop.value = 1

        i = 0
        # wait max 2 seconds for the instance to stop
        while executors[name].is_alive() and i<10:
            time.sleep(.2)
            i+=1

    # return HttpResponseRedirect('/instances')
    return HttpResponse(json.dumps({'success': True, 'retval':executors[name].retval}),
                        content_type='application/json')


@login_required
def start(request, name):
    """ handle (re)start request from client """
    global executors

    # create the Executor for the instance
    # - if it does not exist yet
    # - if the executor thread was alive and exited
    if name not in executors or  \
        (not executors[name].is_alive() and executors[name].retval is not None):
        inst_dir = os.path.join(settings.INSTANCES, name)
        executors[name] = Executor(inst_dir)

    # don't try to start running instances
    if not executors[name].is_alive():
        executors[name].start()
        i = 0
        # wait max 2 seconds for the instance to start
        while (not executors[name].is_alive() or executors[name].p is None) and i<10:
            time.sleep(.2)
            i+=1

    return HttpResponse(json.dumps({'success': True, 'pid':executors[name].p.pid}),
                        content_type='application/json')


def render_from(request, form):
    template = loader.get_template('instances/instances.html')
    context = {
        'form': form,
        'executors': executors,
    }
    return HttpResponse(template.render(context, request))


def _load_utf16_json(path, default=None):
    if default is None:
        default = {}
    if not os.path.isfile(path):
        return dict(default)
    with open(path, 'r', encoding='utf-16') as fh:
        return json.load(fh)


def load_instance_cfg(inst_dir):
    """Merge instance cfg/*.json into a dict suitable for InstanceForm."""
    cfg = {}
    for fname in ('configuration.json', 'settings.json', 'assistRules.json', 'eventRules.json'):
        cfg.update(_load_utf16_json(os.path.join(inst_dir, 'cfg', fname)))

    cfg['instanceName'] = os.path.basename(inst_dir.rstrip(os.sep))

    event_path = os.path.join(inst_dir, 'cfg', 'event.json')
    if os.path.exists(event_path):
        cfg['event'] = os.path.splitext(Path(event_path).resolve().name)[0]

    return cfg


def write_config(name, inst_dir, form):
    """Write a cfg json using ACCSERVER defaults, else existing instance file, else {}."""
    base = os.path.join(settings.ACCSERVER, 'cfg', name)
    inst = os.path.join(inst_dir, 'cfg', name)
    if os.path.isfile(base):
        cfg = _load_utf16_json(base)
    elif os.path.isfile(inst):
        cfg = _load_utf16_json(inst)
    else:
        cfg = {}

    for key in form.cleaned_data.keys():
        if key == 'csrfmiddlewaretoken': continue
        value = form.cleaned_data[key]
        if isinstance(value, bool): value = int(value)
        if value is not None: cfg[key] = value

    with open(inst, 'w', encoding='utf-16') as fh:
        json.dump(cfg, fh)


def set_event_symlink(inst_dir, event_name):
    cfg = os.path.join(settings.CONFIGS, event_name + '.json')
    link = os.path.join(inst_dir, 'cfg', 'event.json')
    if os.path.lexists(link):
        os.remove(link)
    os.symlink(cfg, link)


def _render_edit(request, form, name):
    template = loader.get_template('instances/instance_edit.html')
    return HttpResponse(template.render(
        {'form': form, 'name': name,
         'running': name in executors and executors[name].is_alive()},
        request))


@login_required
def edit(request, name):
    """Edit an existing instance configuration."""
    inst_dir = os.path.join(settings.INSTANCES, name)
    if not os.path.isdir(inst_dir):
        messages.error(request, "Instance not found")
        return HttpResponseRedirect('/instances')

    if request.method != 'POST':
        form = InstanceForm(load_instance_cfg(inst_dir))
        form.fields['instanceName'].widget.attrs['readonly'] = True
        return _render_edit(request, form, name)

    form = InstanceForm(request.POST)
    form.fields['instanceName'].widget.attrs['readonly'] = True

    if not form.is_valid():
        messages.error(request, "Form is not valid")
        return _render_edit(request, form, name)

    udp = form.configuration['udpPort'].value()
    tcp = form.configuration['tcpPort'].value()

    if not settings.ALLOW_SAME_PORTS and udp == tcp:
        messages.error(request, 'UDP and TCP port have to be different')
        return _render_edit(request, form, name)

    conflict = [x for key, x in executors.items()
                if key != name and x.is_alive()
                and (udp in [x.udpPort, x.tcpPort] or tcp in [x.udpPort, x.tcpPort])]
    if conflict:
        messages.error(request, "The ports are already in use")
        return _render_edit(request, form, name)

    event_name = form['event'].value()
    if not event_name:
        messages.error(request, "Event config is required")
        return _render_edit(request, form, name)

    set_event_symlink(inst_dir, event_name)
    write_config('configuration.json', inst_dir, form.configuration)
    write_config('settings.json', inst_dir, form.settings)
    write_config('assistRules.json', inst_dir, form.assistRules)
    write_config('eventRules.json', inst_dir, form.eventRules)

    running = name in executors and executors[name].is_alive()
    if running:
        for key, val in load_instance_cfg(inst_dir).items():
            if key in ('instanceName', 'event'):
                continue
            setattr(executors[name], key, val)
        executors[name].config = event_name + '.json'
        messages.warning(request, "Saved. Restart the instance for changes to take effect.")
    else:
        executors[name] = Executor(inst_dir)
        messages.info(request, "Instance updated")

    return HttpResponseRedirect('/instances')


@login_required
def create(request):
    """ handle create/start request from client """

    # this function should only be entered via POST request
    if request.method != 'POST':
        return HttpResponseRedirect('/instances')

    form = InstanceForm(request.POST)
    name = request.POST['instanceName']

    # form is invalid...
    if not form.is_valid():
        messages.error(request, "Form is not valid")
        return render_from(request, form)

    # instance with similar name already exists
    if name in executors:
        messages.error(request, "Instance with similar name already exists")
        return render_from(request, form)

    if not settings.ALLOW_SAME_PORTS and form.configuration['udpPort'].value() == form.configuration['tcpPort'].value():
        messages.error(request, 'UDP and TCP port have to be different')
        return render_from(request, form)

    # check if a running instance already uses the same ports
    if len(list(filter(lambda x: x.is_alive() and
                                  (form.configuration['udpPort'].value() in [x.udpPort, x.tcpPort] or
                                   form.configuration['tcpPort'].value() in [x.udpPort, x.tcpPort]),
                        executors.values()))) > 0:
        messages.error(request, "The ports are already in use")
        return render_from(request, form)

    # create instance environment
    inst_dir = os.path.join(settings.INSTANCES, name)
    if os.path.isdir(inst_dir):
        messages.error(request, "The instance directory exists already")
        return render_from(request, form)

    # create the directory for the instance, copy necessary files
    os.makedirs(os.path.join(inst_dir, 'cfg'))
    os.makedirs(os.path.join(inst_dir, 'log'))
    for f in settings.SERVER_FILES:
        shutil.copy(os.path.join(settings.ACCSERVER, f), os.path.join(inst_dir, f))

    # symlink the accServer.exe file. When you update the server bin you don't have to recreate all your instances
    os.remove(os.path.join(inst_dir, 'accServer.exe'))
    os.symlink(os.path.join(settings.ACCSERVER, 'accServer.exe'), os.path.join(inst_dir, 'accServer.exe'))

    # link the requested config into the instance environment
    set_event_symlink(inst_dir, form['event'].value())

    # write the json files
    write_config('configuration.json', inst_dir, form.configuration)
    write_config('settings.json', inst_dir, form.settings)
    write_config('assistRules.json', inst_dir, form.assistRules)
    write_config('eventRules.json', inst_dir, form.eventRules)

    # start the instance
    start(request, name)

    messages.info(request, "Successfully started the instance")
    return HttpResponseRedirect('/instances')


def random_word():
    s = 'somename'
    try:
        while s is None or any(c for c in s if c not in string.ascii_letters):
            s = r.get_random_word(hasDictionaryDef="true",
                              minLength=5,
                              maxLength=10)
    except: pass
    return s


def index(request):
    # read defaults from files
    cfg = json.load(open(os.path.join(
        settings.ACCSERVER, 'cfg', 'configuration.json'), 'r', encoding='utf-16'))
    cfg.update(json.load(open(os.path.join(
        settings.ACCSERVER, 'cfg', 'settings.json'), 'r', encoding='utf-16')))
    cfg.update(json.load(open(os.path.join(
        settings.ACCSERVER, 'cfg', 'assistRules.json'), 'r', encoding='utf-16')))

    # some static defaults
    cfg['instanceName'] = random_word()
    cfg['serverName'] = 'ACC server'
    cfg['dumpLeaderboards'] = 1
    cfg['registerToLobby'] = 1
    cfg['dumpLeaderboards'] = 1
    cfg['ignorePrematureDisconnects'] = 0
    cfg['formationLapType'] = 3

    # overwrite nonsense trackMedalsRequirement default value
    if cfg['trackMedalsRequirement'] == -1:
        cfg['trackMedalsRequirement'] = 0

    for inst_dir in glob.glob(os.path.join(settings.INSTANCES, '*')):
        inst_name = os.path.split(inst_dir)[-1]
        if inst_name not in executors:
            executors[inst_name] = Executor(inst_dir)

    return render_from(request, InstanceForm(cfg))

