import glob
import itertools
import ntpath

from django.http import HttpResponse, Http404
from django.shortcuts import render

import os, json

from django.utils.html import format_html
from django_tables2 import tables, Column, TemplateColumn, RequestConfig

from accservermanager.settings import CAR_MODEL_TYPES, DATA_DIR
from core.decorators import role_required
from results.parser import parse_session_name


class LeaderBoard(tables.Table):
    position = Column(empty_values=())
    raceNumber = Column(accessor='car.raceNumber')
    carModel = Column(accessor='car.carModel')
    teamName = Column(accessor='car.teamName')
    drivers = Column(accessor='car.drivers')
    bestLap = Column(accessor='timing')
    laps = Column(accessor='timing.lapCount')
    totaltime = Column(accessor='timing.totalTime')

    def __init__(self, *args, **kwargs):
        super(LeaderBoard, self).__init__(*args, **kwargs)
        self.counter = itertools.count(start=1)

    def render_position(self):
        return '%d' % next(self.counter)

    def render_carModel(self, value):
        for model in CAR_MODEL_TYPES:
            if model[0]==value: return model[1]
        return 'Unknown model %i'%value

    def render_drivers(self, value):
        short = ' / '.join([d['shortName'] for d in value])
        long = ' / '.join(['%s %s'%(d['firstName'],d['lastName']) for d in value])
        return format_html('<p>({}) {}</p>', short, long)

    def render_time(self, value):
        if(value == 2147483647):
            return '---'
        s = value//1000
        m = s//60
        s %=60
        if m==0: return '%02i.%03i'%(s, value%1000)
        return '%i:%02i.%03i'%(m, s, value%1000)

    def render_bestLap(self, value):
        return format_html('<p title="{}">{}</p>',
                           ' | '.join(list(map(self.render_time, value['bestSplits']))),
                           self.render_time(value['bestLap']))

    def render_totaltime(self, value):
        return self.render_time(value)


class Results(tables.Table):
    display_name = Column(verbose_name="Session")
    type = Column(verbose_name="Type")
    track = Column()
    date = Column(verbose_name="Date")
    time = Column(verbose_name="Time")
    entries = Column()
    wetSession = Column(verbose_name="Wet")
    view = TemplateColumn(template_name='results/table/results_view_column.html')
    download = TemplateColumn(template_name='results/table/results_download_column.html')
    simresults = TemplateColumn(template_name='results/table/results_simresults_column.html')


class ResultsGlobal(tables.Table):
    instance = Column(verbose_name="Instance")
    display_name = Column(verbose_name="Session")
    type = Column(verbose_name="Type")
    track = Column()
    date = Column(verbose_name="Date")
    time = Column(verbose_name="Time")
    entries = Column()
    wetSession = Column(verbose_name="Wet")
    view = TemplateColumn(template_name='results/table/results_view_column.html')
    download = TemplateColumn(template_name='results/table/results_download_column.html')
    simresults = TemplateColumn(template_name='results/table/results_simresults_column.html')


def parse_url(args, kwargs):
    """ Read the select results file and display the selected portion of the json object """
    instance = kwargs['instance']
    result = args[0]
    results_path = os.path.join(DATA_DIR, 'instances', instance, 'results')
    return os.path.join(results_path, result+'.json')


@role_required('Admin', 'Operator', 'Viewer')
def results(request, *args, **kwargs):
    """ Read the select results file and display the selected portion of the json object """
    results = json.load(open(parse_url(args, kwargs), 'rb'))
    path = request.path
    if path[0] == '/': path = path[1:]
    if path[-1] == '/': path = path[:-1]
    path = path.split('/')

    context = {
        'path': [(j, '/'+'/'.join(path[:i+1])) for i,j in enumerate(path)],
        'table': LeaderBoard(results['sessionResult']['leaderBoardLines']),
        'instance': kwargs['instance'],
        'title': args[0] if args else 'Result',
        'is_detail': True,
    }
    return render(request, 'results/results.html', context)


@role_required('Admin', 'Operator', 'Viewer')
def download(request, *args, **kwargs):
    _f = parse_url(args, kwargs)
    print(_f, os.path.basename(_f))
    if _f is not None and os.path.isfile(_f):
        with open(_f, 'rb') as fh:
            response = HttpResponse(fh.read(), content_type="text/plain")
            response['Content-Disposition'] = 'inline; filename=' + os.path.basename(_f)
            return response
    raise Http404


@role_required('Admin', 'Operator', 'Viewer')
def resultSelect(request, instance):
    """ Show available results """
    results_path = os.path.join(DATA_DIR, 'instances', instance, 'results')
    files = sorted(glob.glob('%s/*.json'%(results_path)), reverse=True)
    files = filter(lambda x: not x.endswith('entrylist.json') , files)

    results = []
    for f in files:
        r = json.load(open(f, 'rb'))
        parsed = parse_session_name(os.path.splitext(ntpath.basename(f))[0])
        results.append(dict(
            name=os.path.splitext(ntpath.basename(f))[0],
            display_name=parsed['display'],
            date=parsed['date_str'],
            time=parsed['time_str'],
            type=r['sessionType'],
            entries=len(r['sessionResult']['leaderBoardLines']),
            wetSession=r['sessionResult']['isWetSession'],
            track=r['trackName'],
        ))

    path = request.path
    if path[0] == '/': path = path[1:]
    if path[-1] == '/':path = path[:-1]
    path = path.split('/')

    table = Results(results)
    RequestConfig(request).configure(table)

    context = {
        'path' : [(j, '/'+'/'.join(path[:i+1])) for i,j in enumerate(path)],
        'table' : table,
        'instance': instance,
        'title': 'Results',
        'is_detail': False,
    }
    return render(request, 'results/results.html', context)


@role_required('Admin', 'Operator', 'Viewer')
def all_results(request):
    from accservermanager.settings import DATA_DIR
    instances_dir = os.path.join(DATA_DIR, 'instances')
    all_items = []
    for inst_dir in sorted(glob.glob(os.path.join(instances_dir, '*'))):
        if not os.path.isdir(inst_dir):
            continue
        inst_name = os.path.basename(inst_dir)
        results_path = os.path.join(inst_dir, 'results')
        if not os.path.isdir(results_path):
            continue
        files = sorted(glob.glob(os.path.join(results_path, '*.json')), reverse=True)
        files = [f for f in files if not f.endswith('entrylist.json')]
        for f in files:
            try:
                r = json.load(open(f, 'rb'))
                parsed = parse_session_name(os.path.splitext(ntpath.basename(f))[0])
                all_items.append(dict(
                    instance=inst_name,
                    name=os.path.splitext(ntpath.basename(f))[0],
                    display_name=parsed['display'],
                    date=parsed['date_str'],
                    time=parsed['time_str'],
                    type=r['sessionType'],
                    entries=len(r['sessionResult']['leaderBoardLines']),
                    wetSession=r['sessionResult']['isWetSession'],
                    track=r['trackName'],
                ))
            except (json.JSONDecodeError, KeyError):
                continue

    all_items.sort(key=lambda x: x.get('name', ''), reverse=True)
    table = ResultsGlobal(all_items)
    RequestConfig(request).configure(table)
    context = {
        'path': [('Results', '/results/')],
        'table': table,
        'instance': None,
        'title': 'Results',
        'is_detail': False,
        'is_global': True,
    }
    return render(request, 'results/results.html', context)
