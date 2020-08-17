

import logging
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.core.validators import MinLengthValidator
from django.db import models
from django.db.transaction import atomic
from django.utils.encoding import python_2_unicode_compatible
from django.utils.translation import ugettext_lazy as _
from django_extensions.db.models import TimeStampedModel
from jsonfield import JSONField
from oscar.apps.payment.abstract_models import AbstractSource
from solo.models import SingletonModel

from ecommerce.extensions.payment.constants import CARD_TYPE_CHOICES


class PaymentProcessorResponse(models.Model):
    """ Auditing model used to save all responses received from payment processors. """

    processor_name = models.CharField(max_length=255, verbose_name=_('Payment Processor'))
    transaction_id = models.CharField(max_length=255, verbose_name=_('Transaction ID'), null=True, blank=True)
    basket = models.ForeignKey('basket.Basket', verbose_name=_('Basket'), null=True, blank=True,
                               on_delete=models.SET_NULL)
    response = JSONField()
    created = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        get_latest_by = 'created'
        index_together = ('processor_name', 'transaction_id')
        verbose_name = _('Payment Processor Response')
        verbose_name_plural = _('Payment Processor Responses')


class Source(AbstractSource):
    card_type = models.CharField(max_length=255, choices=CARD_TYPE_CHOICES, null=True, blank=True)


class PaypalWebProfile(models.Model):
    id = models.CharField(max_length=255, primary_key=True)
    name = models.CharField(max_length=255, unique=True)


class PaypalProcessorConfiguration(SingletonModel):
    """ This is a configuration model for PayPal Payment Processor"""
    retry_attempts = models.PositiveSmallIntegerField(
        default=0,
        verbose_name=_(
            'Number of times to retry failing Paypal client actions (e.g., payment creation, payment execution)'
        )
    )

    class Meta:
        verbose_name = "Paypal Processor Configuration"


@python_2_unicode_compatible
class SDNCheckFailure(TimeStampedModel):
    """ Record of SDN check failure. """
    full_name = models.CharField(max_length=255)
    username = models.CharField(max_length=255)
    city = models.CharField(max_length=32, default='')
    country = models.CharField(max_length=2)
    site = models.ForeignKey('sites.Site', verbose_name=_('Site'), null=True, blank=True, on_delete=models.SET_NULL)
    products = models.ManyToManyField('catalogue.Product', related_name='sdn_failures')
    sdn_check_response = JSONField()

    def __str__(self):
        return 'SDN check failure [{username}]'.format(
            username=self.username
        )

    class Meta:
        verbose_name = 'SDN Check Failure'


class EnterpriseContractMetadata(TimeStampedModel):
    """ Record of contract details for a particular customer transaction """
    PERCENTAGE = 'Percentage'
    FIXED = 'Absolute'
    DISCOUNT_TYPE_CHOICES = [
        (PERCENTAGE, _('Percentage')),
        (FIXED, _('Absolute')),
    ]
    amount_paid = models.DecimalField(null=True, decimal_places=2, max_digits=12)
    discount_value = models.DecimalField(null=True, decimal_places=5, max_digits=15)
    discount_type = models.CharField(max_length=255, choices=DISCOUNT_TYPE_CHOICES, default=PERCENTAGE)

    def clean(self):
        """
        discount_value can hold two types of things conceptually: percentages
        and fixed amounts. We want to add extra validation here on top of the
        normal field validation DecimalField gives us.
        """
        super(EnterpriseContractMetadata, self).clean()

        if self.discount_value is not None:
            if self.discount_type == self.FIXED:
                self._validate_fixed_value()
            else:
                self._validate_percentage_value()

    def _validate_fixed_value(self):
        before_decimal, __, after_decimal = str(self.discount_value).partition('.')

        if len(before_decimal) > 10:
            raise ValidationError(_(
                "More than 10 digits before the decimal "
                "not allowed for fixed value."
            ))

        if len(after_decimal) > 2:
            raise ValidationError(_(
                "More than 2 digits after the decimal "
                "not allowed for fixed value."
            ))

    def _validate_percentage_value(self):

        if Decimal(self.discount_value) > Decimal('100.00000'):
            raise ValidationError(_(
                "Percentage greater than 100 not allowed."
            ))


class SDNFallbackMetadata(TimeStampedModel):
    """
    Record metadata about the SDN fallback CSV file download, as detailed in docs/decisions/0007-sdn-fallback.rst
    and JIRA ticket REV-1278. This table is used to track the state of the SDN csv file data that are currently
    being used or about to be updated/deprecated. This table does not keep track of the SDN files over time.
    """
    logger = logging.getLogger("SDNFallbackMetadataLogger")

    file_checksum = models.CharField(max_length=255, validators=[MinLengthValidator(1)])
    download_timestamp = models.DateTimeField()
    import_timestamp = models.DateTimeField(null=True, blank=True)

    IMPORT_STATES = [
        ('New', 'New'),
        ('Current', 'Current'),
        ('Discard', 'Discard'),
    ]

    import_state = models.CharField(
        max_length=255,
        validators=[MinLengthValidator(1)],
        unique=True,
        choices=IMPORT_STATES,
        default='New',
    )

    @classmethod
    @atomic
    def swap_all_states(cls):
        """
        Shifts all of the existing metadata table rows to the next import_state
        in the row's lifecycle (see _swap_state).

        This method is done in a transaction to gurantee that existing metadata rows are
        shifted into their next states in sync and tries to ensure that there is always a row
        in the 'Current' state. Rollbacks of all row's import_state changes will happen if:
        1) There are multiple rows & none of them are 'Current', or
        2) There are any issues with the existing rows + updating them (e.g. a row with a
        duplicate import_state is manually inserted into the table during the transaction)
        """
        SDNFallbackMetadata._swap_state('Discard')
        SDNFallbackMetadata._swap_state('Current')
        SDNFallbackMetadata._swap_state('New')
        if len(SDNFallbackMetadata.objects.all()) > 1:
            try:
                SDNFallbackMetadata.objects.get(import_state='Current')
            except SDNFallbackMetadata.DoesNotExist:
                SDNFallbackMetadata.logger.info(
                    "Expected a row in the 'Current' import_state after swapping, but there are none",
                )
                raise

    @classmethod
    def _swap_state(cls, import_state):
        """
        Update the row in the given import_state parameter to the next import_state.
        Rows in this table should progress from New -> Current -> Discard -> (row deleted).
        There can be at most one row in each import_state at a given time.
        """
        try:
            existing_metadata = SDNFallbackMetadata.objects.get(import_state=import_state)
            if import_state == 'Discard':
                existing_metadata.delete()
            else:
                if import_state == 'New':
                    existing_metadata.import_state = 'Current'
                elif import_state == 'Current':
                    existing_metadata.import_state = 'Discard'
                existing_metadata.full_clean()
                existing_metadata.save()
        except SDNFallbackMetadata.DoesNotExist:
            SDNFallbackMetadata.logger.info(
                "Cannot update import_state of %s row if there is no row in this state.",
                import_state
            )


# noinspection PyUnresolvedReferences
from oscar.apps.payment.models import *  # noqa isort:skip pylint: disable=ungrouped-imports, wildcard-import,unused-wildcard-import,wrong-import-position,wrong-import-order
