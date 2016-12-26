import json

import httpretty
from django.conf import settings
from django.core.cache import cache


class CourseDiscoveryMockMixin(object):
    """
    Mocks for the Open edX service 'Course Discovery' responses.
    """
    COURSE_DISCOVERY_CATALOGS_URL = '{}catalogs/'.format(
        settings.COURSE_CATALOG_API_URL,
    )

    def setUp(self):
        super(CourseDiscoveryMockMixin, self).setUp()
        cache.clear()

    def mock_course_discovery_api_for_catalog_by_resource_id(self):
        """
        Helper function to register course catalog API endpoint for a
        single catalog with its resource id.
        """
        catalog_id = 1
        course_discovery_api_response = {
            'count': 1,
            'next': None,
            'previous': None,
            'results': [
                {
                    'id': catalog_id,
                    'name': 'Catalog {}'.format(catalog_id),
                    'query': 'title: *',
                    'courses_count': 0,
                    'viewers': []
                }
            ]
        }
        course_discovery_api_response_json = json.dumps(course_discovery_api_response)
        single_catalog_uri = '{}{}/'.format(self.COURSE_DISCOVERY_CATALOGS_URL, catalog_id)

        httpretty.register_uri(
            method=httpretty.GET,
            uri=single_catalog_uri,
            body=course_discovery_api_response_json,
            content_type='application/json'
        )

    def mock_course_discovery_api_for_catalogs(self, catalog_name_list):
        """
        Helper function to register course catalog API endpoint for a
        single catalog or multiple catalogs response.
        """
        mocked_results = []
        for catalog_index, catalog_name in enumerate(catalog_name_list):
            catalog_id = catalog_index + 1
            mocked_results.append(
                {
                    'id': catalog_id,
                    'name': catalog_name,
                    'query': 'title: *',
                    'courses_count': 0,
                    'viewers': []
                }
            )

        course_discovery_api_response = {
            'count': len(catalog_name_list),
            'next': None,
            'previous': None,
            'results': mocked_results
        }
        course_discovery_api_response_json = json.dumps(course_discovery_api_response)

        httpretty.register_uri(
            method=httpretty.GET,
            uri=self.COURSE_DISCOVERY_CATALOGS_URL,
            body=course_discovery_api_response_json,
            content_type='application/json'
        )

    def mock_course_discovery_api_for_paginated_catalogs(self, catalog_name_list):
        """
        Helper function to register course catalog API endpoint for multiple
        catalogs with paginated response.
        """
        mocked_api_responses = []
        for catalog_index, catalog_name in enumerate(catalog_name_list):
            catalog_id = catalog_index + 1
            mocked_result = {
                'id': catalog_id,
                'name': catalog_name,
                'query': 'title: *',
                'courses_count': 0,
                'viewers': []
            }

            next_page_url = None
            if catalog_id < len(catalog_name_list):
                # Not a last page so there will be more catalogs for another page
                next_page_url = '{}?limit=1&offset={}'.format(
                    self.COURSE_DISCOVERY_CATALOGS_URL,
                    catalog_id
                )

            previous_page_url = None
            if catalog_index != 0:
                # Not a first page so there will always be catalogs on previous page
                previous_page_url = '{}?limit=1&offset={}'.format(
                    self.COURSE_DISCOVERY_CATALOGS_URL,
                    catalog_index
                )

            course_discovery_api_paginated_response = {
                'count': len(catalog_name_list),
                'next': next_page_url,
                'previous': previous_page_url,
                'results': [mocked_result]
            }
            course_discovery_api_paginated_response_json = json.dumps(course_discovery_api_paginated_response)
            mocked_api_responses.append(
                httpretty.Response(body=course_discovery_api_paginated_response_json, content_type='application/json')
            )

        httpretty.register_uri(
            method=httpretty.GET,
            uri=self.COURSE_DISCOVERY_CATALOGS_URL,
            responses=mocked_api_responses
        )

    def mock_course_discovery_api_for_failure(self):
        """
        Helper function to register course catalog API endpoint for a
        failure.
        """
        httpretty.register_uri(
            method=httpretty.GET,
            uri=self.COURSE_DISCOVERY_CATALOGS_URL,
            responses=[
                httpretty.Response(body='Clunk', content_type='application/json', status_code=500)
            ]
        )
