import logging

import waffle
from django.dispatch import receiver
from oscar.core.loading import get_class

from ecommerce.courses.utils import mode_for_seat
from ecommerce.extensions.analytics.utils import silence_exceptions, track_segment_event
from ecommerce.extensions.checkout.utils import get_credit_provider_details, get_receipt_page_url
from ecommerce.notifications.notifications import send_notification

logger = logging.getLogger(__name__)
post_checkout = get_class('checkout.signals', 'post_checkout')

# Number of orders currently supported for the email notifications
ORDER_LINE_COUNT = 1


@receiver(post_checkout, dispatch_uid='tracking.post_checkout_callback')
@silence_exceptions('Failed to emit tracking event upon order completion.')
def track_completed_order(sender, order=None, **kwargs):  # pylint: disable=unused-argument
    """Emit a tracking event when an order is placed."""
    if order.total_excl_tax <= 0:
        return

    for line in order.lines.all():
        if line.product.is_coupon_product or line.product.is_enrollment_code_product:
            return

    voucher = order.basket_discounts.filter(voucher_id__isnull=False).first()
    coupon = voucher.voucher_code if voucher else None

    properties = {
        'orderId': order.number,
        'total': str(order.total_excl_tax),
        'currency': order.currency,
        'coupon': coupon,
        'discount': str(order.total_discount_incl_tax),
        'products': [
            {
                # For backwards-compatibility with older events the `sku` field is (ab)used to
                # store the product's `certificate_type`, while the `id` field holds the product's
                # SKU. Marketing is aware that this approach will not scale once we start selling
                # products other than courses, and will need to change in the future.
                'id': line.partner_sku,
                'sku': mode_for_seat(line.product),
                'name': line.product.course.id if line.product.course else line.product.title,
                'price': str(line.line_price_excl_tax),
                'quantity': line.quantity,
                'category': line.product.get_product_class().name,
            } for line in order.lines.all()
        ],
    }
    track_segment_event(order.site, order.user, 'Order Completed', properties)


@receiver(post_checkout, dispatch_uid='send_completed_order_email')
@silence_exceptions("Failed to send order completion email.")
def send_course_purchase_email(sender, order=None, **kwargs):  # pylint: disable=unused-argument
    """Send course purchase notification email when a course is purchased."""
    if waffle.switch_is_active('ENABLE_NOTIFICATIONS'):
        # We do not currently support email sending for orders with more than one item.
        if len(order.lines.all()) == ORDER_LINE_COUNT:
            product = order.lines.first().product
            credit_provider_id = getattr(product.attr, 'credit_provider', None)
            if not credit_provider_id:
                logger.error(
                    'Failed to send credit receipt notification. Credit seat product [%s] has no provider.', product.id
                )
                return
            elif product.is_seat_product:
                provider_data = get_credit_provider_details(
                    access_token=order.site.siteconfiguration.access_token,
                    credit_provider_id=credit_provider_id,
                    site_configuration=order.site.siteconfiguration
                )

                receipt_page_url = get_receipt_page_url(
                    order_number=order.number,
                    site_configuration=order.site.siteconfiguration
                )

                if provider_data:
                    send_notification(
                        order.user,
                        'CREDIT_RECEIPT',
                        {
                            'course_title': product.title,
                            'receipt_page_url': receipt_page_url,
                            'credit_hours': product.attr.credit_hours,
                            'credit_provider': provider_data['display_name'],
                        },
                        order.site
                    )

        else:
            logger.info('Currently support receipt emails for order with one item.')
