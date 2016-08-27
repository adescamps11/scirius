"""
Copyright(C) 2014, Stamus Networks
Written by Eric Leblond <eleblond@stamus-networks.com>

This file is part of Scirius.

Scirius is free software: you can redistribute it and/or modify
it under the terms of the GNU General Public License as published by
the Free Software Foundation, either version 3 of the License, or
(at your option) any later version.

Scirius is distributed in the hope that it will be useful,
but WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
GNU General Public License for more details.

You should have received a copy of the GNU General Public License
along with Scirius.  If not, see <http://www.gnu.org/licenses/>.
"""

from django.shortcuts import render, get_object_or_404, redirect
from django.utils import timezone
from django.http import HttpResponse
from django.db import IntegrityError
from django.conf import settings
from elasticsearch.exceptions import ConnectionError
from django.core.exceptions import SuspiciousOperation

from scirius.utils import scirius_render, scirius_listing

from rules.es_data import ESData
from rules.models import Ruleset, Source, SourceUpdate, Category, Rule, dependencies_check, get_system_settings, Threshold
from rules.tables import UpdateRuleTable, DeletedRuleTable, ThresholdTable

from rules.es_graphs import *
from rules.influx import *

import json
import re
import os

from time import time
import django_tables2 as tables
from tables import *
from forms import *
from suripyg import SuriHTMLFormat

Probe = __import__(settings.RULESET_MIDDLEWARE)

def complete_context(request, context):
    if get_system_settings().use_elasticsearch:
        if request.GET.__contains__('duration'):
            duration = int(request.GET.get('duration', '24'))
            if duration > 24 * 7:
                duration = 24 * 7
            request.session['duration'] = duration
        else:
            duration = int(request.session.get('duration', '24'))
        from_date = int((time() - (duration * 3600)) * 1000) # last 24 hours
        if duration <= 24:
            date = str(duration) + "h"
        else:
            date = str(duration / 24) + "d"
        if request.GET.__contains__('graph'):
            graph = request.GET.get('graph', 'sunburst')
            if not graph in ['sunburst', 'circles']:
                graph = 'sunburst'
            request.session['graph'] = graph
        else:
            graph = 'sunburst'
        if graph == 'sunburst':
            context['draw_func'] = 'draw_sunburst'
            context['draw_elt'] = 'path'
        else:
            context['draw_func'] = 'draw_circle'
            context['draw_elt'] = 'circle'
        context['date'] = date
        context['from_date'] = from_date
        context['time_range'] = duration * 3600

# Create your views here.
def index(request):
    ruleset_list = Ruleset.objects.all().order_by('-created_date')[:5]
    source_list = Source.objects.all().order_by('-created_date')[:5]
    context = {'ruleset_list': ruleset_list,
                'source_list': source_list}
    try:
        context['probes'] = map(lambda x: '"' +  x + '"', Probe.models.get_probe_hostnames())
    except:
        pass
    complete_context(request, context)
    return scirius_render(request, 'rules/index.html', context)

def about(request):
    context = {}
    try:
        from suricata.models import Suricata
        suricata = Suricata.objects.all()
        if suricata != None:
            context['suricata'] = suricata[0]
    except:
        pass
    return scirius_render(request, 'rules/about.html', context)

def search(request):
    context = {}
    length = 0
    rules_width = 4
    search = None
    if request.method == 'POST':
        if request.POST.has_key('search'):
            search = request.POST['search']
            request.GET = request.GET.copy()
            request.GET.update({'search': search})
    elif request.method == 'GET':
        if request.GET.has_key('search'):
            search = request.GET['search']
    if search:
        rules = Rule.objects.filter(content__icontains=search)
        if len(rules) > 0:
            length += len(rules)
            rules = RuleTable(rules)
            tables.RequestConfig(request).configure(rules)
        else:
            rules = None
        categories = Category.objects.filter(name__icontains=search)
        if len(categories) > 0:
            length += len(categories)
            categories = CategoryTable(categories)
            tables.RequestConfig(request).configure(categories)
        else:
            rules_width += 4
            categories = None
        rulesets = Ruleset.objects.filter(name__icontains=search)
        if len(rulesets) > 0:
            length += len(rulesets)
            rulesets = RulesetTable(rulesets)
            tables.RequestConfig(request).configure(rulesets)
        else:
            rules_width += 4
            rulesets = None
    else:
        rules = None
        categories = None
        rulesets = None
    context = { 'rules': rules, 'rules_width': rules_width, 'categories': categories, 'rulesets': rulesets, 'motif': search, 'length': length }
    return scirius_render(request, 'rules/search.html', context)

def sources(request):
    return scirius_listing(request, Source, 'Sources')

def source(request, source_id, error=None, update = False, activate = False, rulesets = None):
    source = get_object_or_404(Source, pk=source_id)
    cats = CategoryTable(Category.objects.filter(source = source))
    tables.RequestConfig(request).configure(cats)
    context = {'source': source, 'categories': cats,
               'update': update, 'activate': activate, 'rulesets': rulesets}
    if error:
        context['error'] = error
    return scirius_render(request, 'rules/source.html', context)

def categories(request):
    return scirius_listing(request, Category, 'Categories')

def category(request, cat_id):
    cat = get_object_or_404(Category, pk=cat_id)
    rules = RuleTable(Rule.objects.filter(category = cat, state = True))
    tables.RequestConfig(request).configure(rules)
    commented_rules = RuleTable(Rule.objects.filter(category = cat, state = False))
    tables.RequestConfig(request).configure(commented_rules)
    category_path = [ cat.source ]
    # build table of rulesets and display if category is active
    rulesets = Ruleset.objects.all()
    rulesets_status = []
    for ruleset in rulesets:
        status = 'Inactive'
        if cat in ruleset.categories.all():
            status = 'Active'

        rulesets_status.append({'name': ruleset.name, 'pk':ruleset.pk, 'status':status})
    rulesets_status = StatusRulesetTable(rulesets_status)
    tables.RequestConfig(request).configure(rulesets_status)
    context = {'category': cat, 'rules': rules, 'commented_rules': commented_rules, 'object_path': category_path, 'rulesets': rulesets_status}
    return scirius_render(request, 'rules/category.html', context)

class Reference:
    def __init__(self, key, value):
        self.value = value
        self.key = key
        self.url = None

def elasticsearch(request):
    data = None
    if request.GET.__contains__('query'):
        query = request.GET.get('query', 'dashboards')
        if query == 'dashboards':
            data = es_get_dashboard(count=settings.KIBANA_DASHBOARDS_COUNT)
        elif query == 'rules':
            host = request.GET.get('host', None)
            from_date = request.GET.get('from_date', None)
            qfilter = request.GET.get('filter', None)
            if host != None and from_date != None:
                rules = es_get_rules_stats(request, host, from_date = from_date, qfilter = qfilter)
                if rules == None:
                    return HttpResponse(json.dumps(rules), content_type="application/json")
                context = {'table': rules}
                return scirius_render(request, 'rules/table.html', context)
        elif query == 'rule':
            sid = request.GET.get('sid', None)
            from_date = request.GET.get('from_date', None)
            if from_date != None and sid != None:
                hosts = es_get_sid_by_hosts(request, sid, from_date = from_date)
                context = {'table': hosts}
                return scirius_render(request, 'rules/table.html', context)
        elif query == 'rule_src':
            sid = int(request.GET.get('sid', None))
            from_date = request.GET.get('from_date', None)
            if from_date != None and sid != None:
                hosts = es_get_field_stats(request, 'src_ip.raw', RuleHostTable, '*', from_date = from_date,
                    qfilter = 'alert.signature_id:%d' % sid)
                context = {'table': hosts}
                return scirius_render(request, 'rules/table.html', context)
        elif query == 'rule_dest':
            sid = int(request.GET.get('sid', None))
            from_date = request.GET.get('from_date', None)
            if from_date != None and sid != None:
                hosts = es_get_field_stats(request, 'dest_ip.raw', RuleHostTable, '*', from_date = from_date,
                    qfilter = 'alert.signature_id:%d' % sid)
                context = {'table': hosts}
                return scirius_render(request, 'rules/table.html', context)
        elif query == 'timeline':
            from_date = request.GET.get('from_date', None)
            cshosts = request.GET.get('hosts', None)
            hosts = cshosts.split(',')
            qfilter = request.GET.get('filter', None)
            data = es_get_timeline(from_date = from_date, hosts = hosts, qfilter = qfilter)
        elif query == 'logstash_eve':
            from_date = request.GET.get('from_date', None)
            value = request.GET.get('value', None)
            cshosts = request.GET.get('hosts', None)
            if cshosts:
                hosts = cshosts.split(',')
            else:
                hosts = None
            data = es_get_metrics_timeline(from_date = from_date, value = value, hosts = hosts)
        elif query == 'health':
            data = es_get_health()
        elif query == 'stats':
            data = es_get_stats()
        elif query == 'indices':
            if request.is_ajax():
                indices = ESIndexessTable(es_get_indices())
                tables.RequestConfig(request).configure(indices)
                context = { 'table': indices }
                return scirius_render(request, 'rules/table.html', context)
            else:
                context = {}
                complete_context(request, context)
                return scirius_render(request, 'rules/elasticsearch.html', context)
        elif query == 'rules_per_category':
            from_date = request.GET.get('from_date', None)
            cshosts = request.GET.get('hosts', None)
            if cshosts:
                hosts = cshosts.split(',')
            else:
                hosts = None
            qfilter = request.GET.get('filter', None)
            data = es_get_rules_per_category(from_date = from_date, hosts = hosts, qfilter = qfilter)
        elif query == 'alerts_count':
            from_date = request.GET.get('from_date', None)
            cshosts = request.GET.get('hosts', None)
            if cshosts:
                hosts = cshosts.split(',')
            else:
                hosts = None
            qfilter = request.GET.get('filter', None)
            prev = request.GET.get('prev', 0)
            data = es_get_alerts_count(from_date = from_date, hosts = hosts, qfilter = qfilter, prev=prev)
        elif query == 'latest_stats':
            from_date = request.GET.get('from_date', None)
            cshosts = request.GET.get('hosts', None)
            if cshosts:
                hosts = cshosts.split(',')
            else:
                hosts = None
            qfilter = request.GET.get('filter', None)
            data = es_get_latest_stats(from_date = from_date, hosts = hosts, qfilter = qfilter)
        else:
            data = None
        return HttpResponse(json.dumps(data), content_type="application/json")
    else:
        if request.is_ajax():
            data = es_get_dashboard(count=settings.KIBANA_DASHBOARDS_COUNT)
            return HttpResponse(json.dumps(data), content_type="application/json")
        else:
            context = {}
            complete_context(request, context)
            return scirius_render(request, 'rules/elasticsearch.html', context)

def influxdb(request):
    time_range = int(request.GET.get('time_range', 3600))
    request = request.GET.get('request', 'eve_rate')
    data = influx_get_timeline(time_range, request = request)
    return HttpResponse(json.dumps(data), content_type="application/json")

def rule(request, rule_id, key = 'pk'):
    if request.is_ajax():
        rule = get_object_or_404(Rule, sid=rule_id)
        #TODO Check transformation and use function content_updated
        rule.highlight_content = SuriHTMLFormat(rule.content)
        data = { 'msg': rule.msg, 'sid': rule.sid, 'content': rule.content,
                 'highlight_content': rule.highlight_content}
        return HttpResponse(json.dumps(data),
                            content_type="application/json")
    if key == 'pk':
        rule = get_object_or_404(Rule, pk=rule_id)
    else:
        rule = get_object_or_404(Rule, sid=rule_id)
    rule_path = [rule.category.source, rule.category]

    rule.highlight_content = SuriHTMLFormat(rule.content)
    references = []
    for ref in re.findall("reference:(\w+),(\S+);", rule.content):
        refer = Reference(ref[0], ref[1])
        if refer.key == 'url':
            if not refer.value.startswith("http"):
                refer.url = "http://" + refer.value
            else:
                refer.url = refer.value
        elif refer.key == 'cve':
            refer.url = "http://web.nvd.nist.gov/view/vuln/detail?vulnId=CVE-" + refer.value
            refer.key = refer.key.upper()
        elif refer.key == 'bugtraq':
            refer.url = "http://www.securityfocus.com/bid/" + refer.value
        references.append(refer)
    # build table of rulesets and display if rule is active
    rulesets = Ruleset.objects.all()
    rulesets_status = []
    for ruleset in rulesets:
        status = 'Inactive'
        if rule.state and rule.category in ruleset.categories.all() and rule not in ruleset.suppressed_rules.all():
            status = 'Active'
        threshold = 'No'
        if Threshold.objects.filter(rule = rule, ruleset = ruleset):
            threshold = 'Yes'
        rulesets_status.append({'name': ruleset.name, 'pk': ruleset.pk, 'status': status, 'validity': 'Unknown', 'threshold': threshold, 'action': rule.transformation_type(ruleset)})
    rulesets_status = StatusRulesetTable(rulesets_status)
    tables.RequestConfig(request).configure(rulesets_status)

    context = {'rule': rule, 'references': references, 'object_path': rule_path, 'rulesets': rulesets_status }
    thresholds = Threshold.objects.filter(rule = rule, threshold_type = 'threshold')
    if thresholds:
        thresholds = RuleThresholdTable(thresholds)
        tables.RequestConfig(request).configure(thresholds)
        context['thresholds'] = thresholds
    suppress = Threshold.objects.filter(rule = rule, threshold_type = 'suppress')
    if suppress:
        suppress = RuleSuppressTable(suppress)
        tables.RequestConfig(request).configure(suppress)
        context['suppress'] = suppress
    try:
        context['probes'] = map(lambda x: '"' +  x + '"', Probe.models.get_probe_hostnames())
    except:
        pass
    complete_context(request, context)

    return scirius_render(request, 'rules/rule.html', context)


def switch_rule(request, rule_id, operation = 'suppress'):
    rule_object = get_object_or_404(Rule, sid=rule_id)

    if not request.user.is_staff:
        context = { 'rule': rule_object, 'operation': operation, 'error': 'Unsufficient permissions' }
        return scirius_render(request, 'rules/suppress_rule.html', context)
        
    if request.method == 'POST': # If the form has been submitted...
        form = RulesetSuppressForm(request.POST)
        if form.is_valid(): # All validation rules pass
            rulesets = form.cleaned_data['rulesets']
            for ruleset_pk in rulesets:
                ruleset = get_object_or_404(Ruleset, pk=ruleset_pk)
                if operation == 'suppress':
                    rule_object.disable(ruleset)
                elif operation == 'enable':
                    rule_object.enable(ruleset)
                elif operation == 'alert' or operation == 'allow' or operation == 'drop':
                    rule_object.transform(operation, ruleset)
                ruleset.save()
        return redirect(rule_object)
    form = RulesetSuppressForm()
    rules = rule_object.get_flowbits_group()
    context = { 'rule': rule_object, 'form': form }
    if len(rules):
        rules = RuleTable(rules)
        tables.RequestConfig(request).configure(rules)
        context['rules'] = rules
    context['operation'] = operation
    return scirius_render(request, 'rules/suppress_rule.html', context)

def suppress_rule(request, rule_id):
    return switch_rule(request, rule_id)

def enable_rule(request, rule_id):
    return switch_rule(request, rule_id, operation='enable')

def alert_rule(request, rule_id):
    return switch_rule(request, rule_id, operation='alert')

def allow_rule(request, rule_id):
    return switch_rule(request, rule_id, operation='allow')

def drop_rule(request, rule_id):
    return switch_rule(request, rule_id, operation='drop')

def test_rule(request, rule_id, ruleset_id, key = 'pk'):
    rule_object = get_object_or_404(Rule, pk=rule_id)
    ruleset = get_object_or_404(Ruleset, pk=ruleset_id)
    ret = rule_object.test(ruleset)
    return HttpResponse(json.dumps(ret), content_type="application/json")

def delete_alerts(request, rule_id):
    rule_object = get_object_or_404(Rule, sid=rule_id)

    if not request.user.is_staff:
        context = { 'object': rule, 'error': 'Unsufficient permissions' }
        return scirius_render(request, 'rules/delete_alerts.html', context)

    if request.method == 'POST': # If the form has been submitted...
        es_delete_alerts_by_sid(rule_id)
        return redirect(rule_object)
    else:
        context = {'object': rule_object }
        try:
            context['probes'] = map(lambda x: '"' +  x + '"', Probe.models.get_probe_hostnames())
        except:
            pass
        complete_context(request, context)
        return scirius_render(request, 'rules/delete_alerts.html', context)

def toggle_availability(request, rule_id):
    rule_object = get_object_or_404(Rule, sid=rule_id)

    if not request.user.is_staff:
        context = { 'object': rule, 'error': 'Unsufficient permissions' }
        return scirius_render(request, 'rules/rule.html', context)

    rule_object.toggle_availability()

    return redirect(rule_object)

def threshold_rule(request, rule_id):
    rule_object = get_object_or_404(Rule, sid=rule_id)

    if not request.user.is_staff:
        context = { 'object': rule, 'error': 'Unsufficient permissions' }
        return scirius_render(request, 'rules/rule.html', context)

    if request.method == 'POST': # If the form has been submitted...
        if request.POST.has_key('threshold_type'):
            if request.POST['threshold_type'] == 'threshold':
                form = AddRuleThresholdForm(request.POST)
            else:
                form = AddRuleSuppressForm(request.POST)
        else:
            context = {'rule': rule_object, 'form': form, 'error': 'Invalid form, threshold type is missing'}
            if request.POST['threshold_type'] == 'suppress':
                context['type'] = 'suppress'
            else:
                context['type'] = 'threshold'
            return scirius_render(request, 'rules/add_threshold.html', context)
        if form.is_valid():
            rulesets = form.cleaned_data['rulesets']
            for ruleset in rulesets:
                threshold = form.save(commit=False)
                threshold.rule = rule_object
                threshold.ruleset = ruleset
                threshold.pk = None
                threshold.save()
            return redirect(rule_object)
        else:
            context = {'rule': rule_object, 'form': form, 'error': 'Could not create threshold'}
            if request.POST['threshold_type'] == 'suppress':
                context['type'] = 'suppress'
            else:
                context['type'] = 'threshold'
            return scirius_render(request, 'rules/add_threshold.html', context)
    data = { 'gid': 1, 'count': 1, 'seconds': 60, 'type': 'limit', 'rule': rule_object, 'ruleset': 1 }
    if request.GET.__contains__('action'):
        data['threshold_type'] = request.GET.get('action', 'suppress')
    if request.GET.__contains__('net'):
        data['net'] = request.GET.get('net', None)
    if request.GET.__contains__('dir'):
        direction = request.GET.get('dir', 'both')
        if direction == 'src':
            direction = 'by_src'
        elif direction == 'dest':
            direction = 'by_dst'
        data['track_by'] = direction

    if data.has_key('track_by'):
        containers = []
        pth = Threshold(rule = rule_object, track_by = data['track_by'], threshold_type = data['threshold_type'])
        if data.has_key('net'):
            pth.net = data['net']
        thresholds = Threshold.objects.filter(rule = rule_object)
        for threshold in thresholds:
            if threshold.contain(pth):
                containers.append(threshold)
                break
        if len(containers) == 0:
            containers = None
        else:
            if data['threshold_type'] == 'threshold':
                containers = RuleThresholdTable(containers)
            else:
                containers = RuleSuppressTable(containers)
            tables.RequestConfig(request).configure(containers)
        if thresholds:
            thresholds = ThresholdTable(thresholds)
            tables.RequestConfig(request).configure(thresholds)
    else:
        containers = None
        thresholds = None
        
    context = {'rule': rule_object, 'thresholds': thresholds, 'containers': containers }
    if data['threshold_type'] == 'suppress':
        context['form'] = AddRuleSuppressForm(data)
        context['type'] = 'suppress'
    else:
        context['form'] = AddRuleThresholdForm(data)
        context['type'] = 'threshold'
    return scirius_render(request, 'rules/add_threshold.html', context)

def suppress_category(request, cat_id, operation = 'suppress'):
    cat_object = get_object_or_404(Category, id=cat_id)

    if not request.user.is_staff:
        context = { 'category': cat_object, 'error': 'Unsufficient permissions', 'operation': operation }
        return scirius_render(request, 'rules/suppress_category.html', context)

    if request.method == 'POST': # If the form has been submitted...
        form = RulesetSuppressForm(request.POST)
        if form.is_valid(): # All validation rules pass
            rulesets = form.cleaned_data['rulesets']
            for ruleset_pk in rulesets:
                ruleset = get_object_or_404(Ruleset, pk=ruleset_pk)
                if operation == 'suppress':
                    ruleset.categories.remove(cat_object)
                elif operation == 'enable':
                    ruleset.categories.add(cat_object)
                elif operation == 'alert' or operation == 'allow' or operation == 'drop':
                    for rule_obj in Rule.objects.filter(category=cat_object):
                        rule_obj.transform(operation, ruleset)
                ruleset.needs_test()
                ruleset.save()
        return redirect(cat_object)
    form = RulesetSuppressForm()
    context = { 'category': cat_object, 'form': form, 'operation': operation }
    return scirius_render(request, 'rules/suppress_category.html', context)

def enable_category(request, cat_id):
    return suppress_category(request, cat_id, operation='enable')

def alert_category(request, cat_id):
    return suppress_category(request, cat_id, operation='alert')

def allow_category(request, cat_id):
    return suppress_category(request, cat_id, operation='allow')

def drop_category(request, cat_id):
    return suppress_category(request, cat_id, operation='drop')

def edit_rules(request, cat_id):
    category = get_object_or_404(Category, id=cat_id)

    if not request.user.is_staff:
        return scirius_render(request, 'rules/edit_rules.html', {'category': category, 'error': 'Unsufficient permissions'})

    if request.method == 'POST': # If the form has been submitted...
        form = RulesetSuppressForm(request.POST)
        if form.is_valid(): # All validation rules pass
            rulesets = form.cleaned_data['rulesets']
            for ruleset_pk in rulesets:
                ruleset = get_object_or_404(Ruleset, pk=ruleset_pk)
                if 'alert' in request.POST:
                    print ruleset.name
                    for rule_ob in request.POST.getlist('rule_selection'):
                        rule = Rule.objects.get(pk=rule_ob)
                        rule.transform('alert', ruleset=ruleset)
                elif 'allow' in request.POST:
                    for rule_ob in request.POST.getlist('rule_selection'):
                        rule = Rule.objects.get(pk=rule_ob)
                        rule.transform('allow', ruleset=ruleset)
                elif 'drop' in request.POST:
                    for rule_ob in request.POST.getlist('rule_selection'):
                        rule = Rule.objects.get(pk=rule_ob)
                        rule.transform('drop', ruleset=ruleset)
        return redirect(category)
    else:
        rules_selection = []
        rules = EditRuleTable(Rule.objects.filter(category=category))
        tables.RequestConfig(request, paginate=True).configure(rules)
        form = RulesetSuppressForm()
        context = {'category': category, 'rules': rules, 'rules_selection': ", ".join(rules_selection), 'form': form}
        for rule in Rule.objects.filter(category=category):
            rules_selection.append(rule.pk)
        context['rules'] = rules
        context['rules_selection'] = rules_selection
        return scirius_render(request, 'rules/edit_rules.html', context)

def update_source(request, source_id):
    src = get_object_or_404(Source, pk=source_id)

    if not request.user.is_staff:
        return redirect(src)

    try:
        src.update()
    except (IOError, OSError), errors:
        if request.is_ajax():
            data = {}
            data['status'] = False
            data['errors'] = str(errors)
            return HttpResponse(json.dumps(data), content_type="application/json")
        return source(request, source_id, error="Can not fetch data: %s" % (errors))

    if request.is_ajax():
        data = {}
        data['status'] = True
        return HttpResponse(json.dumps(data), content_type="application/json")

    supdate = SourceUpdate.objects.filter(source = src).order_by('-created_date')
    if len(supdate) == 0:
        return redirect(src)
    return redirect('changelog_source', source_id = source_id)

def activate_source(request, source_id, ruleset_id):

    if not request.user.is_staff:
        return HttpResponse(json.dumps(False), content_type="application/json")

    src = get_object_or_404(Source, pk=source_id)
    ruleset = get_object_or_404(Ruleset, pk=ruleset_id)

    sversions  = SourceAtVersion.objects.filter(source = src, version = 'HEAD')
    if not sversions:
        return HttpResponse(json.dumps(False), content_type="application/json")

    ruleset.sources.add(sversions[0])
    for cat in Category.objects.filter(source = src):
        ruleset.categories.add(cat)

    ruleset.needs_test()
    ruleset.save()
    return HttpResponse(json.dumps(True), content_type="application/json")

def test_source(request, source_id):
    source = get_object_or_404(Source, pk=source_id)
    sourceatversion = get_object_or_404(SourceAtVersion, source=source, version = 'HEAD')
    return HttpResponse(json.dumps(sourceatversion.test()), content_type="application/json")

def build_source_diff(request, diff):
    for field in ["added", "deleted", "updated"]:
        if field == "deleted":
            diff[field] = DeletedRuleTable(diff[field])
        else:
            diff[field] = UpdateRuleTable(diff[field])
        tables.RequestConfig(request).configure(diff[field])

def changelog_source(request, source_id):
    source = get_object_or_404(Source, pk=source_id)
    supdate = SourceUpdate.objects.filter(source = source).order_by('-created_date')
    # get last for now 
    if len(supdate) == 0:
        return scirius_render(request, 'rules/source.html', { 'source': source, 'error': "No changelog" })
    changelogs = SourceUpdateTable(supdate)
    tables.RequestConfig(request).configure(changelogs)
    diff = supdate[0].diff()
    build_source_diff(request, diff)
    return scirius_render(request, 'rules/source.html', { 'source': source, 'diff': diff, 'changelogs': changelogs , 'src_update': supdate[0]})

def diff_source(request, source_id):
    source = get_object_or_404(Source, pk=source_id)
    diff = source.diff()
    return scirius_render(request, 'rules/source.html', { 'source': source, 'diff': diff })

def add_source(request):

    if not request.user.is_staff:
        return scirius_render(request, 'rules/add_source.html', { 'error': 'Unsufficient permissions' })

    if request.method == 'POST': # If the form has been submitted...
        form = AddSourceForm(request.POST, request.FILES) # A form bound to the POST data
        if form.is_valid(): # All validation rules pass
            try:
                src = Source.objects.create(name = form.cleaned_data['name'],
                        uri = form.cleaned_data['uri'],
                        authkey = form.cleaned_data['authkey'],
                        method = form.cleaned_data['method'],
                        created_date = timezone.now(),
                        datatype = form.cleaned_data['datatype'],
                        cert_verif = form.cleaned_data['cert_verif'],
                        )
                if src.method == 'local' and request.FILES.has_key('file'):
                    try:
                        src.handle_uploaded_file(request.FILES['file'])
                    except Exception, error:
                        src.delete()
                        return scirius_render(request, 'rules/add_source.html', { 'form': form, 'error': error })
            except IntegrityError, error:
                return scirius_render(request, 'rules/add_source.html', { 'form': form, 'error': error })
            try:
                ruleset_list = form.cleaned_data['rulesets']
            except:
                ruleset_list = []
            rulesets = [ ruleset.pk for ruleset in ruleset_list ]
            ruleset_list = [ '"' + ruleset.name + '"' for ruleset in ruleset_list ]
            return scirius_render(request, 'rules/add_source.html', { 'source': src,  'update': True, 'rulesets': rulesets, 'ruleset_list': ruleset_list})
    else:
        form = AddSourceForm() # An unbound form

    return scirius_render(request, 'rules/add_source.html', { 'form': form, })

def edit_source(request, source_id):
    source = get_object_or_404(Source, pk=source_id)

    if not request.user.is_staff:
        return scirius_render(request, 'rules/add_source.html', { 'error': 'Unsufficient permissions' })

    if request.method == 'POST': # If the form has been submitted...
        form = SourceForm(request.POST, request.FILES, instance=source)
        try:
            if source.method == 'local' and request.FILES.has_key('file'):
                categories = Category.objects.filter(source = source)
                firstimport = False
                if not categories:
                    firstimport = True
                source.new_uploaded_file(request.FILES['file'], firstimport)
            form.save()
            return redirect(source)
        except ValueError:
            pass
    else:
        form = SourceForm(instance = source)

    return scirius_render(request, 'rules/add_source.html', { 'form': form, 'source': source})

def delete_source(request, source_id):
    source = get_object_or_404(Source, pk=source_id)

    if not request.user.is_staff:
        return scirius_render(request, 'rules/delete.html', { 'error': 'Unsufficient permissions' })

    if request.method == 'POST': # If the form has been submitted...
        source.delete()
        return redirect("/rules/source/")
    else:
        context = {'object': source, 'delfn': 'delete_source' }
        return scirius_render(request, 'rules/delete.html', context)

def sourceupdate(request, update_id):
    sourceupdate = get_object_or_404(SourceUpdate, pk=update_id)
    source = sourceupdate.source
    diff = sourceupdate.diff()
    build_source_diff(request, diff)
    return scirius_render(request, 'rules/source.html', { 'source': source, 'diff': diff, 'src_update': sourceupdate })

def rulesets(request):
    return scirius_listing(request, Ruleset, 'Rulesets')

def ruleset(request, ruleset_id, mode = 'struct', error = None):
    ruleset = get_object_or_404(Ruleset, pk=ruleset_id)
    if mode == 'struct':
        categories_list = {}
        sources = ruleset.sources.all()
        for sourceatversion in sources:
            cats = CategoryTable(ruleset.categories.filter(source = sourceatversion.source))
            tables.RequestConfig(request,  paginate={"per_page": 15}).configure(cats)
            categories_list[sourceatversion.source.name] = cats
        context = {'ruleset': ruleset, 'categories_list': categories_list, 'sources': sources, 'mode': mode}
        disabled_rules = ruleset.suppressed_rules.all()
        if disabled_rules:
            disabled_rules = RuleTable(disabled_rules)
            tables.RequestConfig(request).configure(disabled_rules)
            context['disabled_rules'] = disabled_rules

        thresholds = Threshold.objects.filter(ruleset = ruleset, threshold_type = 'threshold')
        if thresholds:
            thresholds = RulesetThresholdTable(thresholds)
            tables.RequestConfig(request).configure(thresholds)
            context['thresholds'] = thresholds
        suppress = Threshold.objects.filter(ruleset = ruleset, threshold_type = 'suppress')
        if suppress:
            suppress = RulesetSuppressTable(suppress)
            tables.RequestConfig(request).configure(suppress)
            context['suppress'] = suppress
        if error:
            context['error'] = error
    elif mode == 'display':
        rules = RuleTable(ruleset.generate())
        tables.RequestConfig(request).configure(rules)
        context = {'ruleset': ruleset, 'rules': rules, 'mode': mode}
        if error:
            context['error'] = error
    elif mode == 'export':
        file_content = ruleset.to_buffer()
        response = HttpResponse(file_content, content_type="text/plain")
        response['Content-Disposition'] = 'attachment; filename=scirius.rules'
        return response
    return scirius_render(request, 'rules/ruleset.html', context)

def add_ruleset(request):
    if not request.user.is_staff:
        return scirius_render(request, 'rules/add_ruleset.html', { 'error': 'Unsufficient permissions' })

    context = {}
    if request.method == 'POST': # If the form has been submitted...
        form = RulesetForm(request.POST) # A form bound to the POST data
        if form.is_valid(): # All validation rules pass
            # Process the data in form.cleaned_data
            # ...
            try:
                ruleset = form.create_ruleset()
            except IntegrityError, error:
                return scirius_render(request, 'rules/add_ruleset.html', { 'form': form, 'error': error })
            return redirect(ruleset)
    else:
        form = RulesetForm() # An unbound form
        missing = dependencies_check(Ruleset)
        if missing:
            context['missing'] = missing
    context['form'] = form

    return scirius_render(request, 'rules/add_ruleset.html', context)

def update_ruleset(request, ruleset_id):
    rset = get_object_or_404(Ruleset, pk=ruleset_id)

    if not request.user.is_staff:
        return redirect(rset)

    try:
        rset.update()
    except IOError, errors:
        error="Can not fetch data: %s" % (errors)
        if request.is_ajax():
            return HttpResponse(json.dumps({'status': False, 'errors': error}), content_type="application/json")
        return ruleset(request, ruleset_id, error)
    if request.is_ajax():
        return HttpResponse(json.dumps({'status': True}), content_type="application/json")
    return redirect('changelog_ruleset', ruleset_id = ruleset_id)

def changelog_ruleset(request, ruleset_id):
    ruleset = get_object_or_404(Ruleset, pk=ruleset_id)
    diff = ruleset.diff()
    for key in diff:
        cdiff = diff[key]
        build_source_diff(request, cdiff)
        diff[key] = cdiff
    return scirius_render(request, 'rules/ruleset.html', { 'ruleset': ruleset, 'diff': diff, 'mode': 'changelog'})

def test_ruleset(request, ruleset_id):
    ruleset = get_object_or_404(Ruleset, pk=ruleset_id)
    return HttpResponse(json.dumps(ruleset.test()), content_type="application/json")

def edit_ruleset(request, ruleset_id):
    ruleset = get_object_or_404(Ruleset, pk=ruleset_id)

    if not request.user.is_staff:
        return scirius_render(request, 'rules/edit_ruleset.html', {'ruleset': ruleset, 'error': 'Unsufficient permissions'})

    if request.method == 'POST': # If the form has been submitted...
        # check if this is a categories edit
        # ID is unique so we can just look by indice and add
        if request.POST.has_key('category'):
            # clean ruleset
            ruleset.categories.clear()
            # add updated entries
            for cat in request.POST.getlist('category_selection'):
                category = get_object_or_404(Category, pk=cat)
                ruleset.categories.add(category)
            ruleset.needs_test()
        elif request.POST.has_key('rules'):
            for rule in request.POST.getlist('rule_selection'):
                rule_object = get_object_or_404(Rule, pk=rule)
                rule_object.enable(ruleset)
            ruleset.needs_test()
        elif request.POST.has_key('sources'):
            # clean ruleset
            ruleset.sources.clear()
            # add updated entries
            for src in request.POST.getlist('source_selection'):
                source = get_object_or_404(SourceAtVersion, pk=src)
                ruleset.sources.add(source)
            ruleset.needs_test()
        else:
            form = RulesetEditForm(request.POST, instance=ruleset)
            if form.is_valid():
                form.save()
        return redirect(ruleset)
    else:
        cats_selection = []
        categories_list = {}
        sources = ruleset.sources.all()
        ruleset_cats = ruleset.categories.all()
        for sourceatversion in sources:
            src_cats = Category.objects.filter(source = sourceatversion.source)
            for pcats in src_cats:
                if pcats in ruleset_cats:
                    cats_selection.append(str(pcats.id))
            cats = EditCategoryTable(src_cats)
            tables.RequestConfig(request,paginate = False).configure(cats)
            categories_list[sourceatversion.source.name] = cats
        rules = EditRuleTable(ruleset.suppressed_rules.all())
        tables.RequestConfig(request, paginate = False).configure(rules)

        context = {'ruleset': ruleset,  'categories_list': categories_list, 'sources': sources, 'rules': rules, 'cats_selection': ", ".join(cats_selection) }
        if request.GET.has_key('mode'):
            context['mode'] = request.GET['mode']
            if context['mode'] == 'sources':
                all_sources = SourceAtVersion.objects.all()
                sources_selection = []
                for source in sources:
                    sources_selection.append(source.pk)
                sources_list = EditSourceAtVersionTable(all_sources)
                tables.RequestConfig(request, paginate = False).configure(sources_list)
                context['sources_list'] = sources_list
                context['sources_selection'] = sources_selection
        else:
            context['form'] = RulesetEditForm(instance=ruleset)
        return scirius_render(request, 'rules/edit_ruleset.html', context)

def ruleset_add_supprule(request, ruleset_id):
    ruleset = get_object_or_404(Ruleset, pk=ruleset_id)

    if not request.user.is_staff:
        context = { 'ruleset': ruleset, 'error': 'Unsufficient permissions' }
        return scirius_render(request, 'rules/search_rule.html', context)

    if request.method == 'POST': # If the form has been submitted...
        if request.POST.has_key('search'):
            #FIXME Protection on SQL injection ?
            rules = EditRuleTable(Rule.objects.filter(content__icontains=request.POST['search']))
            tables.RequestConfig(request).configure(rules)
            context = { 'ruleset': ruleset, 'rules': rules }
            return scirius_render(request, 'rules/search_rule.html', context)
        elif request.POST.has_key('rule_selection'):
            for rule in request.POST.getlist('rule_selection'):
                rule_object = get_object_or_404(Rule, pk=rule)
                rule_object.disable(ruleset)
            ruleset.save()
        return redirect(ruleset)
    context = { 'ruleset': ruleset }
    return scirius_render(request, 'rules/search_rule.html', context)

def delete_ruleset(request, ruleset_id):
    ruleset = get_object_or_404(Ruleset, pk=ruleset_id)

    if not request.user.is_staff:
        context = { 'object': ruleset, 'error': 'Unsufficient permissions' }
        return scirius_render(request, 'rules/delete.html', context)

    if request.method == 'POST': # If the form has been submitted...
        ruleset.delete()
        return redirect("/rules/ruleset/")
    else:
        context = {'object': ruleset, 'delfn': 'delete_ruleset' }
        return scirius_render(request, 'rules/delete.html', context)

def copy_ruleset(request, ruleset_id):
    ruleset = get_object_or_404(Ruleset, pk=ruleset_id)

    if not request.user.is_staff:
        context = { 'object': ruleset, 'error': 'Unsufficient permissions' }
        return scirius_render(request, 'rules/copy_ruleset.html', context)

    if request.method == 'POST': # If the form has been submitted...
        form = RulesetCopyForm(request.POST) # A form bound to the POST data
        if form.is_valid(): # All validation rules pass
            copy = ruleset.copy(form.cleaned_data['name'])
            return redirect(copy)
    else:
        form = RulesetCopyForm()
    context = {'object': ruleset , 'form': form}
    return scirius_render(request, 'rules/copy_ruleset.html', context)

def system_settings(request):
    if not request.user.is_staff:
        context = { 'error': 'Unsufficient permissions' }
        return scirius_render(request, 'rules/system_settings.html', context)

    main_form = SystemSettingsForm(instance = get_system_settings())
    kibana_form = KibanaDataForm()
    context = {
        'form_id': 'main',
        'main_form': main_form,
        'kibana_form': kibana_form,
    }

    if request.method == 'POST':
        form_id = request.POST.get('form_id', None)

        if form_id == 'main':
            main_form = SystemSettingsForm(request.POST, instance = get_system_settings())
            context['main_form'] = main_form
            if main_form.is_valid():
                main_form.save()
                context['success'] = "All changes saved."
            else:
                context['error'] = "Invalid form."

        elif form_id == 'es':
            es_data = ESData()
            try:
                es_data.es_clear()
                context['success'] = 'Done'
            except ConnectionError as e:
                context['error'] = 'Could not connect to Elasticsearch'
            except Exception as e:
                context['error'] = 'Clearing failed: %s' % e

        elif form_id == 'kibana':
            es_data = ESData()
            if 'export' in request.POST:
                tar_name, tar_file = es_data.kibana_export()

                with open(tar_file, 'rb') as f:
                    content = f.read()

                os.unlink(tar_file)
                response = HttpResponse(content, content_type='application/x-bzip2')
                response['Content-Disposition'] = 'attachment; filename="%s"' % tar_name
                return response
            elif 'import' in request.POST:
                form = KibanaDataForm(request.POST, request.FILES)
                if form.is_valid() and 'file' in request.FILES:
                    try:
                        count = es_data.kibana_import_fileobj(request.FILES['file'])
                        context['success'] = 'Successfully imported %i dashboards' % count
                    except Exception, e:
                        context['error'] = 'Import failed: %s' % e
                else:
                    context['error'] = 'Please provide a dashboard archive'
            elif 'clear' in request.POST:
                try:
                    es_data.kibana_clear()
                    context['success'] = 'Done'
                except Exception, e:
                    context['error'] = 'Clearing failed: %s' % e
            elif 'reset' in request.POST:
                try:
                    es_data.kibana_reset()
                    context['success'] = 'Done'
                except Exception, e:
                    context['error'] = 'Reset failed: %s' % e
            else:
                context['error'] = 'Invalid operation'
        else:
            context['error'] = "Invalid form id."

        if form_id is not None:
            context['form_id'] = form_id
    return scirius_render(request, 'rules/system_settings.html', context)

def info(request):
    data = {'status': 'green'}
    if request.GET.__contains__('query'):
        info = Probe.common.Info()
        query = request.GET.get('query', 'status')
        if query == 'status':
            data = { 'running': info.status() }
        elif query == 'disk':
            data = info.disk()
        elif query == 'memory':
            data = info.memory()
    return HttpResponse(json.dumps(data),
                        content_type="application/json")

def threshold(request, threshold_id):
    threshold = get_object_or_404(Threshold, pk=threshold_id)
    threshold.rule.highlight_content = SuriHTMLFormat(threshold.rule.content)
    threshold.highlight_content = SuriHTMLFormat(str(threshold))
    context = { 'threshold': threshold }
    return scirius_render(request, 'rules/threshold.html', context)

def edit_threshold(request, threshold_id):
    threshold = get_object_or_404(Threshold, pk=threshold_id)
    rule = threshold.rule

    if not request.user.is_staff:
        return redirect(threshold)

    if request.method == 'POST': # If the form has been submitted...
        form = EditThresholdForm(request.POST, instance=threshold) # A form bound to the POST data
        if form.is_valid(): # All validation rules pass
            form.save()
            return redirect(threshold)
        else:
            context = {'threshold': threshold, 'form': form, 'error': 'Invalid form'}            
            return scirius_render(request, 'rules/edit_threshold.html', context)
    else:
        form = EditThresholdForm(instance=threshold)
        context = { 'threshold': threshold, 'form': form }
        return scirius_render(request, 'rules/edit_threshold.html', context)

def delete_threshold(request, threshold_id):
    threshold = get_object_or_404(Threshold, pk=threshold_id)
    ruleset = threshold.ruleset
    if not request.user.is_staff:
        context = { 'object': threshold, 'error': 'Unsufficient permissions' }
        return scirius_render(request, 'rules/delete.html', context)

    if request.method == 'POST': # If the form has been submitted...
        threshold.delete()
        return redirect(ruleset)
    else:
        context = {'object': threshold, 'delfn': 'delete_threshold' }
        return scirius_render(request, 'rules/delete.html', context)
