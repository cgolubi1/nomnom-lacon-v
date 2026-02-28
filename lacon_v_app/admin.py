from django.conf import settings
from django.contrib import admin
from django.http import HttpRequest


class LaconVAdminSite(admin.AdminSite):
    site_header = "Lacon V Administration"
    site_title = "Lacon V Admin"
    index_title = "Welcome to Lacon V Admin"
    login_template = "laconv/admin/login.html"

    def login(self, request: HttpRequest, extra_context=None):
        # if we're already authenticated, use the default behaviour
        if request.user.is_authenticated:
            return super().login(request, extra_context)

        from django.contrib.auth import REDIRECT_FIELD_NAME

        next_url = request.GET.get(REDIRECT_FIELD_NAME, request.get_full_path())

        if not settings.NOMNOM_ALLOW_USERNAME_LOGIN_FOR_MEMBERS:
            from django.shortcuts import redirect
            from django.urls import reverse

            social_login_url = reverse("social:begin", args=["lacon"])
            return redirect(f"{social_login_url}?redirect_uri={next_url}")

        # otherwise show the custom login template
        from django.contrib.auth.forms import AuthenticationForm
        from django.template.response import TemplateResponse

        context = {
            "title": "Log in to Lacon V Admin",
            REDIRECT_FIELD_NAME: next_url,
            "USERNAME_LOGIN": True,
            "login_form": AuthenticationForm(request),
            **self.each_context(request),
            **(extra_context or {}),
        }

        return TemplateResponse(request, self.login_template, context)
