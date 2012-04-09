from djangorestframework.mixins import PaginatorMixin
from djangorestframework.views import View as DRFView
from djangorestframework.renderers import DEFAULT_RENDERERS
from djangorestframework.response import Response, ErrorResponse
from djangorestframework import status

from django.views.generic import View
from django.core.urlresolvers import reverse
from django.conf import settings

import pyes
from query_parse import parse_query

from collections import defaultdict

ALLOWED_FILTERS = ['agency', 'docket']

class SearchResultsView(PaginatorMixin, DRFView):
    aggregation_level = None

    def get(self, request, query):
        self.set_query(query)
        return self.get_results()

    def set_query(self, query):
        parsed = parse_query(query)
        self.text_query = parsed['text']
        self.filters = parsed['filters']

    def serialize_page_info(self, page):
        # force recomputation of page numbers because of lazy loading
        page.paginator._num_pages = None
        page.paginator._count = int(page.paginator._count)

        # proceed as per usual
        out = super(SearchResultsView, self).serialize_page_info(page)
        out['search'] = {
            'text_query': self.text_query,
            'filters': [{
                'category': f[0],
                'id': f[1],
                'name': f[2] if len(f) > 2 else f[1]
            } for f in self.filters if f[0] in ALLOWED_FILTERS],
            'aggregation_level': self.aggregation_level
        }

        return out

    def get_es_filters(self):
        terms = defaultdict(list)
        for f in self.filters:
            if f[0] == 'agency':
                terms['agency'] += [f[1]]
            elif f[0] == 'docket':
                terms['docket_id'] += [f[1]]
        return {'terms': terms} if len(terms.values()) else None

    def get_es_text_query(self):
        return {'text': {'files.text': self.text_query}} if self.text_query else None

class DeferredInt(int):
    def __init__(self):
        super(DeferredInt, self).__init__()
        self._real = False

    def __int__(self):
        return self._real if self._real else 0

    def __str__(self):
        if self._real is False:
            return str(0)
        else:
            return str(self._real)

    def __cmp__(self, val):
        if self._real is False:
            return 1
        else:
            return self._real.__cmp__(val)

    def resolve(self, val):
        self._real = val

class DocumentSearchResults(object):
    def __init__(self, query):
        self.query = query
        self._results = None
        # paginator wants the count before we know what slice we want, so add some indirection hackery to avoid having to do two queries
        self._count = DeferredInt()

    def __getslice__(self, start, end):
        if not self._results:
            self.query['from'] = start
            self.query['size'] = end - start
            
            es = pyes.ES(settings.ES_SETTINGS)
            self._results = es.search_raw(self.query)
            self._count.resolve(self._results['hits']['total'])
        return self._results['hits']['hits']

    def count(self):
        return self._count



class DocumentSearchResultsView(SearchResultsView):
    aggregation_level = 'document'

    def get_results(self):
        query = {}
        
        filters = self.get_es_filters()
        text_query = self.get_es_text_query()

        if filters:
            query['filter'] = filters

        if text_query:
            query['query'] = text_query
        
        return DocumentSearchResults(query)