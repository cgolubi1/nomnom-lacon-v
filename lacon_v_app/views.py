from urllib.parse import urlencode

from django.contrib import messages
from django.http import HttpRequest, HttpResponse
from django.shortcuts import redirect, reverse


def landing(request: HttpRequest) -> HttpResponse:
    """LACon landing page view.

    If the member is logged in, redirect to the index.

    If the member is not, redirect immediately to the login page on Authentik"""

    if request.user.is_authenticated:
        messages.info(
            request,
            "You are already logged in. Redirecting to the main page.",
        )
        return redirect("index")

    # with Authentik, this pops up even if they are logged in inside authentik
    # leading it to pop up after they are already logged in
    # messages.info(
    #     request,
    #     "You are not logged in. Redirecting to the login page.",
    # )
    # after login, redirect to the index
    next_url = reverse("index")
    login_url = reverse("social:begin", kwargs={"backend": "lacon"})
    query_params = urlencode({"next": next_url})
    return redirect(f"{login_url}?{query_params}")
