"""
URL configuration for LAcon V project.

The `urlpatterns` list routes URLs to views. For more information please see:
https://docs.djangoproject.com/en/dev/topics/http/urls/
Examples:
Function views
1. Add an import:  from my_app import views
2. Add a URL to urlpatterns:  path('', views.home, name='home')
Class-based views
1. Add an import:  from other_app.views import Home
2. Add a URL to urlpatterns:  path('', Home.as_view(), name='home')
Including another URLconf
1. Import the include() function: from django.urls import include, path
2. Add a URL to urlpatterns:  path('blog/', include('blog.urls'))
"""

import djp
import nomnom.base.views
from debug_toolbar.toolbar import debug_toolbar_urls
from django.contrib import admin
from django.urls import include, path
from django_svcs.apps import svcs_from
from nomnom.convention import ConventionConfiguration

from lacon_v_app import logout as lacon_logout

convention_configuration = svcs_from().get(ConventionConfiguration)

urlpatterns = (
    [
        path("", nomnom.base.views.index, name="index"),
        path("e/", include("nomnom.nominate.urls", namespace="election")),
        path("e/", include("nomnom.canonicalize.urls", namespace="canonicalize")),
        path("lacon/", include("lacon_v_app.urls", namespace="convention")),
        path("admin/action-forms/", include("django_admin_action_forms.urls")),
        path("admin/", admin.site.urls),
        path("", include("social_django.urls", namespace="social")),
        # Must come before accounts/ because it overrides one of the standard routes
        path("accounts/logout/", lacon_logout.rp_initiated_logout, name="logout"),
        path("accounts/", include("django.contrib.auth.urls")),
        path("watchman/", include("watchman.urls")),
        path("__reload__/", include("django_browser_reload.urls")),
        path("p/", include("nomnom.hugopacket.urls", namespace="hugopacket")),
        path("bm/", include("nomnom.advise.urls", namespace="advise")),
    ]
    + debug_toolbar_urls()
    + djp.urlpatterns()
)

handler403 = "nomnom.nominate.views.access_denied"
