import datetime
import json

import ddt
from django.conf import settings
from django.test import TestCase, override_settings
from django_dynamic_fixture import G
import httpretty
import mock
from requests import Timeout
from testfixtures import LogCapture

from ecommerce.courses.models import Course
from ecommerce.courses.publishers import LMSPublisher
from ecommerce.extensions.catalogue.tests.mixins import CourseCatalogTestMixin
from ecommerce.settings.base import get_lms_url


EDX_API_KEY = 'edx'
JSON = 'application/json'
LOGGER_NAME = 'ecommerce.courses.publishers'


@ddt.ddt
@override_settings(COMMERCE_API_URL='http://example.com/commerce/api/v1/', EDX_API_KEY=EDX_API_KEY)
class LMSPublisherTests(CourseCatalogTestMixin, TestCase):
    def setUp(self):
        super(LMSPublisherTests, self).setUp()
        self.course = G(Course)
        self.course.create_or_update_seat('honor', False, 0)
        self.course.create_or_update_seat('verified', True, 50)
        self.publisher = LMSPublisher()
        self.error_message = (
            u'Failed to publish commerce data for [{course_id}] to LMS.').format(
                course_id=self.course.id
        )

    def _mock_commerce_api(self, status, body=None):
        self.assertTrue(httpretty.is_enabled, 'httpretty must be enabled to mock Commerce API calls.')

        body = body or {}
        url = '{}/courses/{}/'.format(settings.COMMERCE_API_URL.rstrip('/'), self.course.id)
        httpretty.register_uri(httpretty.PUT, url, status=status, body=json.dumps(body),
                               content_type=JSON)

    def _mock_credit_api(self, creation_status, update_status):
        self.assertTrue(httpretty.is_enabled, 'httpretty must be enabled to mock Credit API calls.')

        url = get_lms_url('api/credit/v1/courses/')
        httpretty.register_uri(
            httpretty.POST,
            url,
            status=creation_status,
            body='{}',
            content_type=JSON
        )

        if update_status is not None:
            url += self.course.id.strip('/') + '/'
            httpretty.register_uri(
                httpretty.PUT,
                url,
                status=update_status,
                body='{}',
                content_type=JSON
            )

    @ddt.data('', None)
    def test_commerce_api_url_not_set(self, setting_value):
        """ If the Commerce API is not setup, the method should log an INFO message and return """
        with override_settings(COMMERCE_API_URL=setting_value):
            with LogCapture(LOGGER_NAME) as l:
                error_message = self.publisher.publish(self.course)
                l.check((LOGGER_NAME, 'ERROR', 'COMMERCE_API_URL is not set. Commerce data will not be published!'))
                self.assertFalse(error_message is None)

    def test_api_exception(self):
        """ If an exception is raised when communicating with the Commerce API, an ERROR message should be logged. """
        error = 'time out error'
        with mock.patch('requests.put', side_effect=Timeout(error)):
            with LogCapture(LOGGER_NAME) as l:
                error_message = self.publisher.publish(self.course)
                l.check(
                    (LOGGER_NAME, 'ERROR', 'Failed to publish commerce data for [{}] to LMS.'.format(self.course.id)))
                self.assertFalse(error_message is None)

    @httpretty.activate
    @ddt.data(401, 403, 404, 500)
    def test_api_bad_status(self, status):
        """ If the Commerce API returns a non-successful status, an ERROR message should be logged. """
        body = {u'error': u'Testing!'}
        self._mock_commerce_api(status, body)

        with LogCapture(LOGGER_NAME) as l:
            error_message = self.publisher.publish(self.course)
            l.check((LOGGER_NAME, 'ERROR',
                     u'Failed to publish commerce data for [{}] to LMS. Status was [{}]. Body was [{}].'.format(
                         self.course.id, status, json.dumps(body))))
            self.assertFalse(error_message is None)

    @httpretty.activate
    @ddt.data(200, 201)
    def test_api_success(self, status):
        """ If the Commerce API returns a successful status, an INFO message should be logged. """
        self._mock_commerce_api(status)

        with LogCapture(LOGGER_NAME) as l:

            error_message = self.publisher.publish(self.course)
            published = (error_message is None)
            l.check((LOGGER_NAME, 'INFO', 'Successfully published commerce data for [{}].'.format(self.course.id)))
            self.assertTrue(published)

        last_request = httpretty.last_request()

        # Verify the headers passed to the API were correct.
        expected = {
            'Content-Type': JSON,
            'X-Edx-Api-Key': EDX_API_KEY
        }
        self.assertDictContainsSubset(expected, last_request.headers)

        # Verify the data passed to the API was correct.
        actual = json.loads(last_request.body)
        expected = {
            'id': self.course.id,
            'name': self.course.name,
            'verification_deadline': self.course.verification_deadline.isoformat(),
            'modes': [self.publisher.serialize_seat_for_commerce_api(seat) for seat in self.course.seat_products]
        }
        self.assertDictEqual(actual, expected)

    def test_serialize_seat_for_commerce_api(self):
        """ The method should convert a seat to a JSON-serializable dict consumable by the Commerce API. """
        # Grab the verified seat
        seat = sorted(self.course.seat_products, key=lambda p: getattr(p.attr, 'certificate_type', ''))[1]
        stock_record = seat.stockrecords.first()

        actual = self.publisher.serialize_seat_for_commerce_api(seat)
        expected = {
            'name': 'verified',
            'currency': 'USD',
            'price': int(stock_record.price_excl_tax),
            'sku': stock_record.partner_sku,
            'expires': None
        }
        self.assertDictEqual(actual, expected)

        # Try with an expiration datetime
        expires = datetime.datetime.utcnow()
        seat.expires = expires
        expected['expires'] = expires.isoformat()
        actual = self.publisher.serialize_seat_for_commerce_api(seat)
        self.assertDictEqual(actual, expected)

    @ddt.unpack
    @ddt.data(
        (True, 'professional'),
        (False, 'no-id-professional'),
    )
    def test_serialize_seat_for_commerce_api_with_professional(self, is_verified, expected_mode):
        """
        Verify that (a) professional seats NEVER have an expiration date and (b) the name/mode is properly set for
        no-id-professional seats.
        """
        seat = self.course.create_or_update_seat('professional', is_verified, 500, expires=datetime.datetime.utcnow())
        stock_record = seat.stockrecords.first()
        actual = self.publisher.serialize_seat_for_commerce_api(seat)
        expected = {
            'name': expected_mode,
            'currency': 'USD',
            'price': int(stock_record.price_excl_tax),
            'sku': stock_record.partner_sku,
            'expires': None
        }
        self.assertDictEqual(actual, expected)

    @httpretty.activate
    @ddt.data(
        (201, None, 201),
        (400, 200, 200)
    )
    @ddt.unpack
    def test_credit_publication_success(self, creation_status, update_status, commerce_status):
        """
        Verify that course publication succeeds if the Credit API responds
        with 2xx status codes when publishing CreditCourse data to the LMS.
        """
        self.course.create_or_update_seat('credit', True, 100, credit_provider='Harvard', credit_hours=1)

        self._mock_credit_api(creation_status, update_status)
        self._mock_commerce_api(commerce_status)

        access_token = 'access_token'
        error_message = self.publisher.publish(self.course, access_token=access_token)
        published = (error_message is None)
        self.assertTrue(published)

        # Retrieve the latest request to the Credit API.
        if creation_status == 400:
            latest_request = httpretty.httpretty.latest_requests[1]
        else:
            latest_request = httpretty.httpretty.latest_requests[0]

        # Verify the headers passed to the Credit API were correct.
        expected = {
            'Content-Type': JSON,
            'Authorization': 'Bearer ' + access_token
        }
        self.assertDictContainsSubset(expected, latest_request.headers)

        # Verify the data passed to the Credit API was correct.
        expected = {
            'course_key': self.course.id,
            'enabled': True
        }
        actual = json.loads(latest_request.body)
        self.assertEqual(expected, actual)

    @httpretty.activate
    def test_credit_publication_failure(self):
        """
        Verify that course publication fails if the Credit API does not respond
        with 2xx status codes when publishing CreditCourse data to the LMS.
        """
        self.course.create_or_update_seat('credit', True, 100, credit_provider='Harvard', credit_hours=1)

        self._mock_credit_api(400, 418)

        error_message = self.publisher.publish(self.course, access_token='access_token')
        self.assertFalse(error_message is None)

    def test_credit_publication_no_access_token(self):
        """
        Verify that course publication fails if no access token is provided
        when publishing CreditCourse data to the LMS.
        """
        self.course.create_or_update_seat('credit', True, 100, credit_provider='Harvard', credit_hours=1)

        error_message = self.publisher.publish(self.course, access_token=None)
        self.assertFalse(error_message is None)

    def test_credit_publication_exception(self):
        """
        Verify that course publication fails if an exception is raised
        while publishing CreditCourse data to the LMS.
        """
        self.course.create_or_update_seat('credit', True, 100, credit_provider='Harvard', credit_hours=1)

        with mock.patch.object(LMSPublisher, '_publish_creditcourse') as mock_publish_creditcourse:
            mock_publish_creditcourse.side_effect = Exception(self.error_message)

            error_message = self.publisher.publish(self.course, access_token='access_token')
            self.assertFalse(error_message is None)

