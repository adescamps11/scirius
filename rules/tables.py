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

from rules.models import Ruleset, Source, Category, Rule, SourceAtVersion, SourceUpdate, Threshold
import django_tables2 as tables

class DefaultMeta:
    attrs = {"class": "paleblue"}

class RuleTable(tables.Table):
    sid = tables.LinkColumn('rule', args=[tables.A('pk')])
    class Meta(DefaultMeta):
        model = Rule
        fields = ("sid", "msg")

class ExtendedRuleTable(tables.Table):
    sid = tables.LinkColumn('rule', args=[tables.A('pk')])
    class Meta(DefaultMeta):
        model = Rule
        fields = ("sid", "msg", "category", "hits")

class UpdateRuleTable(tables.Table):
    sid = tables.LinkColumn('rule', args=[tables.A('pk')])
    class Meta(DefaultMeta):
        model = Rule
        fields = ("sid", "msg", "category")

class DeletedRuleTable(tables.Table):
    class Meta(DefaultMeta):
        model = Rule
        fields = ("sid", "msg", "category")

class EditSourceAtVersionTable(tables.Table):
    source_selection = tables.CheckBoxColumn(accessor="pk", attrs = { "th__input":
                                        {"onclick": "tables2_toggle(this, 'source_selection')"},
                                        },
                                        orderable=False)
    name = tables.LinkColumn('source', args=[tables.A('pk')])
    class Meta(DefaultMeta):
        model = SourceAtVersion
        fields = ("source_selection", "name", "created_date")

class CategoryTable(tables.Table):
    name = tables.LinkColumn('category', args=[tables.A('pk')])
    class Meta(DefaultMeta):
        model = Category
        fields = ("name", "descr", "created_date")

class EditCategoryTable(tables.Table):
    category_selection = tables.CheckBoxColumn(accessor="pk", attrs = { "th__input":
                                        {"onclick": "tables2_toggle(this, 'category_selection')"},
                                        },
                                        orderable=False)
    name = tables.LinkColumn('category', args=[tables.A('pk')])
    class Meta(DefaultMeta):
        model = Category
        fields = ("category_selection", "name", "descr", "created_date")

class EditRuleTable(tables.Table):
    rule_selection = tables.CheckBoxColumn(accessor="pk", attrs = { "th__input":
                                        {"onclick": "tables2_toggle(this, 'rule_selection')"}},
                                        orderable=False)
    sid = tables.LinkColumn('rule', args=[tables.A('pk')])
    class Meta(DefaultMeta):
        model = Rule
        fields = ("rule_selection", "sid", "msg")

class RulesetTable(tables.Table):
    name = tables.LinkColumn('ruleset', args=[tables.A('pk')])
    class Meta(DefaultMeta):
        model = Ruleset
        fields = ("name", "created_date", "updated_date")

class SourceTable(tables.Table):
    name = tables.LinkColumn('source', args=[tables.A('pk')])
    class Meta(DefaultMeta):
        model = Source
        fields = ("name", "created_date", "updated_date")

class SourceUpdateTable(tables.Table):
    created_date = tables.LinkColumn('sourceupdate', args=[tables.A('pk')])
    class Meta(DefaultMeta):
        model = SourceUpdate
        fields = ("created_date", "changed")

class StatusRulesetTable(tables.Table):
    name = tables.LinkColumn('ruleset', args=[tables.A('pk')])
    status = tables.Column(verbose_name='Status in ruleset')
    threshold = tables.Column(verbose_name='Threshold')
    validity = tables.Column(verbose_name='Operational status')
    action = tables.Column(verbose_name='Action in ruleset')
    class Meta(DefaultMeta):
        fields = ("name", "status", "threshold", "validity", "action")
        attrs = { 'id': 'rulesets', 'class': 'paleblue' }

class RuleStatsTable(tables.Table):
    host = tables.Column()
    count = tables.Column()
    class Meta(DefaultMeta):
        fields = ("host", "count")

class RuleHostTable(tables.Table):
    host = tables.Column()
    count = tables.Column()
    actions = tables.Column()
    class Meta(DefaultMeta):
        fields = ("host", "count", "actions")
        attrs = { 'id': 'hosts', 'class': 'paleblue' }

class ESIndexessTable(tables.Table):
    name = tables.Column()
    count = tables.Column()
    deleted = tables.Column()
    class Meta(DefaultMeta):
        fields = ("name", "count", "deleted")

class ThresholdTable(tables.Table):
    pk = tables.LinkColumn('threshold', args=[tables.A('pk')] )
    threshold_type = tables.Column("Type")
    net = tables.Column("Network")
    rule = tables.Column("Rule")
    ruleset = tables.Column("Ruleset")
    class Meta(DefaultMeta):
        model = Threshold
        exclude = ()

class RuleSuppressTable(tables.Table):
    pk = tables.LinkColumn('threshold', args=[tables.A('pk')], verbose_name='ID')
    net = tables.Column("Network")
    ruleset = tables.Column("Ruleset")
    class Meta(DefaultMeta):
        model = Threshold
        fields = ("pk", "track_by", "net", "ruleset")

class RuleThresholdTable(tables.Table):
    pk = tables.LinkColumn('threshold', args=[tables.A('pk')], verbose_name='ID')
    ruleset = tables.Column("Ruleset")
    class Meta(DefaultMeta):
        model = Threshold
        fields = ("pk", "track_by", "type", "count", "seconds", "ruleset")

class RulesetSuppressTable(tables.Table):
    pk = tables.LinkColumn('threshold', args=[tables.A('pk')], verbose_name='ID')
    net = tables.Column("Network")
    class Meta(DefaultMeta):
        model = Threshold
        fields = ("pk", "rule", "track_by", "net")

class RulesetThresholdTable(tables.Table):
    pk = tables.LinkColumn('threshold', args=[tables.A('pk')], verbose_name='ID')
    class Meta(DefaultMeta):
        model = Threshold
        fields = ("pk", "rule", "track_by", "type", "count", "seconds")
