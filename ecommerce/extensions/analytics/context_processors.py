from ecommerce.extensions.analytics.utils import prepare_analytics_data


def analytics(request):
    analytics_data = prepare_analytics_data(request.user, request.site.siteconfiguration)

    return {
        'analytics_data': analytics_data,
    }
