import logging

from django.conf import settings
from django.dispatch import receiver
from oscar.core.loading import get_class

from ecommerce_worker.sailthru.v1.tasks import update_course_enrollment
from ecommerce.extensions.analytics.utils import silence_exceptions
from ecommerce.core.url_utils import get_lms_url


logger = logging.getLogger(__name__)
post_checkout = get_class('checkout.signals', 'post_checkout')
basket_addition = get_class('basket.signals', 'basket_addition')


@receiver(post_checkout)
@silence_exceptions("Failed to call Sailthru upon order completion.")
def process_checkout_complete(sender, order=None, request=None, user=None, **kwargs):  # pylint: disable=unused-argument
    """Tell Sailthru when payment done.

    Parameters described at http://django-oscar.readthedocs.io/en/releases-1.1/ref/signals.html
    """

    if not settings.SAILTHRU_ENABLE:
        return

    # get product (should only be 1)
    product = order.lines.first().product

    # return if no price, since enrolls are handled by lms
    price = order.total_excl_tax
    if not price or price == 0:
        return

    course_id = product.course_id

    # figure out course url
    course_url = _build_course_url(course_id)

    # pass event to ecommerce_worker.sailthru.v1.tasks to handle asynchronously
    update_course_enrollment.delay(user.email, course_url, False, product.attr.certificate_type,
                                   unit_cost=price, course_id=course_id, currency=order.currency,
                                   site_code=request.site.siteconfiguration.partner.short_code,
                                   message_id=request.COOKIES.get('sailthru_bid'))


@receiver(basket_addition)
@silence_exceptions("Failed to call Sailthru upon backet addition.")
def process_basket_addition(sender, product=None, request=None, user=None, **kwargs):  # pylint: disable=unused-argument
    """Tell Sailthru when payment started.

    Parameters described at http://django-oscar.readthedocs.io/en/releases-1.1/ref/signals.html
    """

    if not settings.SAILTHRU_ENABLE:
        return

    course_id = product.course_id

    # figure out course url
    course_url = _build_course_url(course_id)

    # get price & currency
    stock_record = product.stockrecords.first()
    if stock_record:
        price = stock_record.price_excl_tax
        currency = stock_record.price_currency

    # return if no price, since enrolls are handled by lms
    if not price or price == 0:
        return

    # pass event to ecommerce_worker.sailthru.v1.tasks to handle asynchronously
    update_course_enrollment.delay(user.email, course_url, True, product.attr.certificate_type,
                                   unit_cost=price, course_id=course_id, currency=currency,
                                   site_code=request.site.siteconfiguration.partner.short_code,
                                   message_id=request.COOKIES.get('sailthru_bid'))


def _build_course_url(course_id):
    """Build a course url from a course id and the host

    :param request:
    :param course_id:
    :return:
    """
    host = get_lms_url()
    # hack for integration testing since Sailthru rejects urls without a valid domain
    if host.startswith('http://127.0.0.1'):
        host = 'http://courses.edx.org'
    return '{host}/courses/{course}/info'.format(
        host=host,
        course=course_id
    )
