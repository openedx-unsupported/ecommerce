import json

import ddt
import httpretty
from django.conf import settings
from django.core.urlresolvers import reverse
from testfixtures import LogCapture

from ecommerce.core.constants import ENROLLMENT_CODE_SWITCH
from ecommerce.core.tests import toggle_switch
from ecommerce.core.url_utils import get_lms_url
from ecommerce.tests.testcases import TestCase

LOGGER_NAME = 'ecommerce.courses.views'


class ManagementCommandViewMixin(object):
    def test_superuser_required(self):
        """ Verify the view is only accessible to superusers. """
        response = self.client.get(self.path)
        self.assertEqual(response.status_code, 404)

        user = self.create_user(is_superuser=False)
        self.client.login(username=user.username, password=self.password)
        response = self.client.get(self.path)
        self.assertEqual(response.status_code, 404)

        user = self.create_user(is_superuser=True)
        self.client.login(username=user.username, password=self.password)
        response = self.client.get(self.path + '?course_ids=foo')
        self.assertEqual(response.status_code, 200)

    def test_course_ids_required(self):
        """ The view should return HTTP status 400 if no course IDs are provided. """
        user = self.create_user(is_superuser=True)
        self.client.login(username=user.username, password=self.password)
        response = self.client.get(self.path)
        self.assertEqual(response.status_code, 400)

        response = self.client.get(self.path + '?course_ids=')
        self.assertEqual(response.status_code, 400)

        response = self.client.get(self.path + '?course_ids=foo')
        self.assertEqual(response.status_code, 200)


class CourseMigrationViewTests(ManagementCommandViewMixin, TestCase):
    path = reverse('courses:migrate')


class ConvertCourseViewTests(ManagementCommandViewMixin, TestCase):
    path = reverse('courses:convert_course')


@ddt.ddt
class CourseAppViewTests(TestCase):
    path = reverse('courses:app', args=[''])

    def mock_credit_api_providers(self):
        """
        Mock GET requests to the Credit API's provider endpoint.

        /api/credit/v1/providers
        """
        self.assertTrue(httpretty.is_enabled())

        providers = [
            {
                'id': 'shk',
                'display_name': 'School of Hard Knocks'
            },
            {
                'id': 'acme',
                'display_name': 'Acme University'
            }
        ]
        providers.sort(key=lambda provider: provider['display_name'])
        provider_json = json.dumps(providers)
        url = get_lms_url('/api/credit/v1/providers/')
        httpretty.register_uri(httpretty.GET, url, body=provider_json, content_type='application/json')

        return providers, provider_json

    def mock_credit_api_error(self):
        """ Mock an error response when calling the Credit API providers endpoint. """

        def callback(request, uri, headers):  # pylint: disable=unused-argument
            return 500, headers, 'Failure!'

        url = get_lms_url('/api/credit/v1/providers/')
        httpretty.register_uri(httpretty.GET, url, body=callback, content_type='application/json')

    def test_login_required(self):
        """ Users are required to login before accessing the view. """
        self.client.logout()
        response = self.client.get(self.path)
        self.assertEqual(response.status_code, 302)
        self.assertIn(settings.LOGIN_URL, response.url)

    def _create_and_login_staff_user(self):
        """Setup staff user with an OAuth2 access token and log the user in."""
        user = self.create_user(is_staff=True)
        self.create_access_token(user)
        self.assertIsNotNone(user.access_token)
        self.client.login(username=user.username, password=self.password)

    @httpretty.activate
    def test_staff_user_required(self):
        """ Verify the view is only accessible to staff users. """
        self.mock_credit_api_providers()

        user = self.create_user(is_staff=False)
        self.client.login(username=user.username, password=self.password)
        response = self.client.get(self.path)
        self.assertEqual(response.status_code, 404)

        self._create_and_login_staff_user()
        response = self.client.get(self.path)
        self.assertEqual(response.status_code, 200)

    @httpretty.activate
    def test_credit_providers_in_context(self):
        """ Verify the context data includes a list of credit providers. """
        self._create_and_login_staff_user()

        # Mock Credit API
        __, provider_json = self.mock_credit_api_providers()

        response = self.client.get(self.path)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context['credit_providers'], provider_json)

    @ddt.data(True, False)
    @httpretty.activate
    def test_bulk_enrollment_code_flag_is_context(self, enabled):
        """Verify the context data includes a bulk enrollment code flag."""
        self._create_and_login_staff_user()
        self.mock_credit_api_providers()

        toggle_switch(ENROLLMENT_CODE_SWITCH, enabled)
        site_config = self.site.siteconfiguration
        site_config.enable_enrollment_codes = enabled
        site_config.save()

        response = self.client.get(self.path)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context['bulk_enrollment_codes_enabled'], enabled)

    @httpretty.activate
    def test_credit_api_failure(self):
        """ Verify the view logs an error if it fails to retrieve credit providers. """
        # Setup staff user with an OAuth 2 access token
        self._create_and_login_staff_user()
        self.mock_credit_api_error()

        with LogCapture(LOGGER_NAME) as l:
            response = self.client.get(self.path)

            self.assertEqual(response.status_code, 200)
            expected = 'Failed to retrieve credit providers!'
            l.check((LOGGER_NAME, 'ERROR', expected))

    @httpretty.activate
    def test_missing_access_token(self):
        """ Verify the view logs a warning if the user has no access token. """
        user = self.create_user(is_staff=True)
        self.client.login(username=user.username, password=self.password)
        self.mock_credit_api_providers()

        with LogCapture(LOGGER_NAME) as l:
            response = self.client.get(self.path)

            self.assertEqual(response.status_code, 200)
            expected = 'User [{}] has no access token, and will not be able to edit courses.'.format(user.username)
            l.check((LOGGER_NAME, 'WARNING', expected))
