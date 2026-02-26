from typing import Any

from django.contrib.auth import get_user_model
from social_core.backends.open_id_connect import OpenIdConnectAuth
from social_core.strategy import BaseStrategy

UserModel = get_user_model()


class LaconMemberBackend(OpenIdConnectAuth):
    name = "lacon"

    DEFAULT_SCOPE = ["openid", "profile", "email", "membership"]


def adapt_regid_to_username(
    strategy: BaseStrategy,
    details: dict[str, Any],
    user=UserModel,
    *args,
    response: dict[str, Any],
    **kwargs,
) -> None:
    """Extract the reg-id if provided and make it available as a username and member_number"""
    try:
        member_id = response["reg-id"]
    except KeyError:
        return

    details["username"] = member_id
    details["member_number"] = member_id

    # nomnom's social auth integration uses this key.
    wsfs_status_key = strategy.setting("WSFS_STATUS_KEY", default="wsfs_status")
    if wsfs_status_key:
        details[wsfs_status_key] = response.get(
            "membership_type", "Unknown Member Type"
        )
    return


def get_wsfs_permissions(
    strategy: BaseStrategy,
    details: dict[str, Any],
    user=UserModel,
    *args,
    response: dict[str, Any],
    **kwargs,
) -> None:
    """Extract WSFS permissions from response"""
    details["can_nominate"] = response.get("hugos-can-nominate", False)
    details["can_vote"] = response.get("hugos-can-vote", False)
    details["site_selection_can_vote"] = response.get("site-selection-can-vote", False)

    # Map groups to Django permissions
    groups = response.get("groups", [])
    details["is_admin"] = "NomNom Admin" in groups

    return


def adapt_personal_information(
    strategy: BaseStrategy,
    details: dict[str, Any],
    user=UserModel,
    *args,
    response: dict[str, Any],
    **kwargs,
) -> None:
    """Adapt personal information from response using field priority rules"""
    # Name priority: preferred_name > given_name > nickname
    preferred_name = response.get("badge-name")
    name = response.get("name")
    given_name = response.get("given_name")
    nickname = response.get("nickname")

    if preferred_name:
        name_to_use = preferred_name
    elif name:
        name_to_use = name
    elif given_name:
        name_to_use = given_name
    else:
        name_to_use = nickname

    if name_to_use:
        # Split name for first/last if possible
        name_parts = name_to_use.split()
        details["first_name"] = name_parts[0]
        if len(name_parts) > 1:
            details["last_name"] = " ".join(name_parts[1:])

        # Store preferred name separately
        details["preferred_name"] = name_to_use
    else:
        details["first_name"] = "WSFS"
        details["last_name"] = "Member"
        details["preferred_name"] = f"WSFS Member {response['reg-id']}"

    # Map email
    email = response.get("email")
    if email:
        details["email"] = email

    # Map membership information
    details["membership_type"] = response.get("membership-type")
    details["is_in_person"] = response.get("is-in-person", False)
    return


def store_full_membership_data(
    strategy: BaseStrategy,
    details: dict[str, Any],
    user=UserModel,
    *args,
    response: dict[str, Any],
    **kwargs,
) -> None:
    """Store full membership response data for reference"""
    details["full_response"] = response.copy()
    return


def create_user(
    strategy: BaseStrategy,
    details: dict[str, Any],
    user=None,
    *args,
    response: dict[str, Any],
    **kwargs,
) -> dict[str, Any]:
    """Create user with fields extracted by adapt_personal_information"""
    if user:
        # User already exists, return early
        return {"user": user}

    # Extract user creation fields from details
    username = details.get("username")
    if not username:
        # Username is required for user creation, generate one if missing
        # This could happen if reg-id is not provided in the response
        username = f"user_{response.get('email', 'anonymous')}"

    # Check if user already exists by username before attempting creation
    try:
        existing_user = UserModel.objects.get(username=username)
        return {"user": existing_user, "is_new": False}
    except UserModel.DoesNotExist:
        pass

    user_fields = {
        "username": username,
        "email": details.get("email", ""),
        "first_name": details.get("first_name", ""),
        "last_name": details.get("last_name", ""),
    }

    # Remove None values to avoid validation errors, but keep username
    user_fields = {k: v for k, v in user_fields.items() if v is not None}

    # Create the user
    created_user = UserModel.objects.create_user(**user_fields)

    return {"user": created_user, "is_new": True}


def update_user_details(
    strategy: BaseStrategy,
    details: dict[str, Any],
    user=None,
    *args,
    response: dict[str, Any],
    **kwargs,
) -> None:
    """Update user details including email if changed by the auth provider"""
    if not user:
        return

    changed = False

    # Update email if it differs from what the provider says
    if details.get("email") and user.email != details["email"]:
        user.email = details["email"]
        changed = True

    # Update first name if provided and different
    if details.get("first_name") and user.first_name != details["first_name"]:
        user.first_name = details["first_name"]
        changed = True

    # Update last name if provided and different
    if details.get("last_name") and user.last_name != details["last_name"]:
        user.last_name = details["last_name"]
        changed = True

    if changed:
        user.save()

    return


def set_member_details(
    strategy: BaseStrategy,
    details: dict[str, Any],
    user=None,
    *args,
    response: dict[str, Any],
    **kwargs,
) -> None:
    """Set additional member details on the user object"""
    if not user:
        return

    # set the ticket number used by the WSFS membership associator.
    details["ticket_number"] = details["member_number"]

    # Set admin status
    if details.get("is_admin") is not None:
        user.is_staff = details["is_admin"]

    # Save the user with updated fields
    user.save()

    return


def store_oidc_session_mapping(
    strategy: BaseStrategy,
    details: dict[str, Any],
    user=UserModel,
    backend=None,
    *args,
    response: dict[str, Any],
    **kwargs,
) -> None:
    """Stash OIDC `sid` in the user's session for post-login mapping.

    The actual mapping from `sid -> session_key` should be created after login,
    in a `user_logged_in` signal handler, to ensure we capture the final (rotated)
    session key that exists in `django_session`.
    """
    # Only process for OIDC backends
    if not hasattr(backend, "id_token"):
        return

    # Get the sid from the validated id_token claims
    id_token_claims = getattr(backend, "id_token", {})
    sid = id_token_claims.get("sid")

    if not sid:
        return

    # Stash the sid in the session for use by the post-login signal
    strategy.session["oidc_sid"] = sid

    strategy.session.save()
