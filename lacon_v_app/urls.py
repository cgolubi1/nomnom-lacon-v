from django.urls import path

from . import logout
from . import views  # noqa: F401,E402

app_name = "lacon_v_app"

urlpatterns = [
    path("landing/", views.landing, name="landing"),
    path("oidc/backchannel-logout/", logout.backchannel_logout, name="backchannel_logout"),
]
