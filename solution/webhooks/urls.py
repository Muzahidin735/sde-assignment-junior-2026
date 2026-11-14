from django.urls import path

from webhooks.views import call_result_webhook


urlpatterns = [
    path(
        "call-result/",
        call_result_webhook,
        name="call_result_webhook",
    ),
]