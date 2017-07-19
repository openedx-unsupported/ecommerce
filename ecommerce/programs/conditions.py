from __future__ import unicode_literals

import logging
import operator

import requests
from oscar.apps.offer import utils as oscar_utils
from oscar.core.loading import get_model
from slumber.exceptions import HttpNotFoundError, SlumberBaseException

from ecommerce.programs.api import ProgramsApiClient

Condition = get_model('offer', 'Condition')
logger = logging.getLogger(__name__)


class ProgramCourseRunSeatsCondition(Condition):
    class Meta(object):
        app_label = 'programs'
        proxy = True

    @property
    def name(self):
        return 'Basket contains a seat for every course in program {}'.format(self.program_uuid)

    def get_program(self, site_configuration):
        """
        Returns details for the program associated with this condition.

        Data is retrieved from the Discovery Service, and cached for ``settings.PROGRAM_CACHE_TIMEOUT`` seconds.

        Args:
            site_configuration (SiteConfiguration): Configuration containing the requisite parameters
             to connect to the Discovery Service.

        Returns:
            dict
        """
        program_uuid = str(self.program_uuid)
        client = ProgramsApiClient(site_configuration.discovery_api_client, site_configuration.site.domain)
        return client.get_program(program_uuid)

    def get_applicable_skus(self, site_configuration):
        """ SKUs to which this condition applies. """
        program_course_run_skus = set()
        program = self.get_program(site_configuration)
        applicable_seat_types = program['applicable_seat_types']

        for course in program['courses']:
            for course_run in course['course_runs']:
                program_course_run_skus.update(
                    set([seat['sku'] for seat in course_run['seats'] if seat['type'] in applicable_seat_types]))

        return program_course_run_skus

    def is_satisfied(self, offer, basket):  # pylint: disable=unused-argument
        """
        Determines if a user is eligible for a program offer based on products in their basket
        and their existing course enrollments.

        Args:
            basket : contains information on line items for order, associated siteconfiguration
                        for retrieving program details, and associated user for retrieving enrollments
        Returns:
            bool
        """

        if basket.is_empty:
            return False

        basket_skus = set([line.stockrecord.partner_sku for line in basket.all_lines()])
        try:
            program = self.get_program(basket.site.siteconfiguration)
        except (HttpNotFoundError, SlumberBaseException, requests.Timeout):
            return False

        applicable_seat_types = program['applicable_seat_types']
        enrollments = basket.site.siteconfiguration.enrollment_api_client.enrollment.get(user=basket.owner.username)

        for course in program['courses']:
            # If the user is already enrolled in a course, we do not need to check their basket for it
            if any(course['key'] in enrollment['course_details']['course_id'] and
                   enrollment['mode'] in applicable_seat_types for enrollment in enrollments):
                continue

            # If the  basket has no SKUs left, but we still have courses over which
            # to iterate, the user cannot meet the condition that all courses be represented.
            if not basket_skus:
                return False

            # Get all of the SKUs that can satisfy this course
            skus = set()
            for course_run in course['course_runs']:
                skus.update(set([seat['sku'] for seat in course_run['seats'] if seat['type'] in applicable_seat_types]))

            # The lack of a difference in the set of SKUs in the basket and the course indicates that
            # that there is no intersection. Therefore, the basket contains no SKUs for the current course.
            # Because the user is also not enrolled in the course, it follows that the program condition is not met.
            diff = basket_skus.difference(skus)
            if diff == basket_skus:
                return False

            # If there is a difference between the basket SKUs and course SKUs, it represents the basket SKUs
            # minus the SKUs for the current course. Since we have already verified the course is represented,
            # its SKUs can be safely removed from the set of SKUs in the basket being checked. Note that this
            # does NOT affect the actual basket, just our copy of its SKUs.
            basket_skus = diff

        return True

    def can_apply_condition(self, line):
        """ Determines whether the condition can be applied to a given basket line. """
        if not line.stockrecord_id:
            return False

        product = line.product
        return line.stockrecord.partner_sku in self.get_applicable_skus(
            line.basket.site.siteconfiguration) and product.get_is_discountable()

    def get_applicable_lines(self, offer, basket, most_expensive_first=True):
        """ Return line data for the lines that can be consumed by this condition. """
        line_tuples = []
        for line in basket.all_lines():
            if not self.can_apply_condition(line):
                continue

            price = oscar_utils.unit_price(offer, line)
            if not price:
                continue
            line_tuples.append((price, line))

        return sorted(line_tuples, reverse=most_expensive_first, key=operator.itemgetter(0))

    def consume_items(self, offer, basket, affected_lines):  # pylint: disable=unused-argument
        """ Marks items within the basket lines as consumed so they can't be reused in other offers.

        This offer will consume only 1 unit of quantity for each affected line.

        Args:
            offer (AbstractConditionalOffer)
            basket (AbstractBasket)
            affected_lines (tuple[]): The lines that have been affected by the discount.
                This should be list of tuples (line, discount, qty)
        """
        for line, __, __ in affected_lines:
            quantity_to_consume = min(line.quantity_without_discount, 1)
            line.consume(quantity_to_consume)
