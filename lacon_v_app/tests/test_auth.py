import pytest
from django.contrib.auth import get_user_model
from faker import Faker
from social_core.tests.models import TestStorage
from social_core.tests.strategy import TestStrategy

from lacon_v_app.auth import (
    adapt_personal_information,
    adapt_regid_to_username,
    create_user,
    get_wsfs_permissions,
    set_member_details,
    store_full_membership_data,
    update_user_details,
)

User = get_user_model()
fake = Faker()


@pytest.fixture
def mock_strategy():
    """Mock social auth strategy"""
    return TestStrategy(storage=TestStorage())


@pytest.fixture
def test_user(db):
    """Create a test user using the actual Django User model"""
    return User.objects.create_user(
        username=fake.user_name(),
        email=fake.email(),
        first_name=fake.first_name(),
        last_name=fake.last_name(),
    )


def generate_auth_response(
    has_admin_group=False,
    can_nominate=False,
    can_vote=False,
    can_site_selection_vote=False,
    membership_type="Unknown",
    is_in_person=False,
    reg_id_format="standard",  # standard, hyphenated, dots, short
    use_badge_name=True,
    use_name=True,
    use_given_name=True,
    use_nickname=True,
):
    """Generate a fake auth response with the specified parameters"""
    base_response = {
        "access_token": fake.uuid4(),
        "email_verified": fake.boolean(),
        "expires_in": fake.random_int(min=300, max=3600),
        "id_token": fake.uuid4(),
        "nonce": fake.uuid4(),
        "scope": "profile email membership openid",
        "sub": fake.uuid4(),
        "token_type": "Bearer",
        "email": fake.email(),
        "hugos-can-nominate": can_nominate,
        "hugos-can-vote": can_vote,
        "site-selection-can-vote": can_site_selection_vote,
        "membership-type": membership_type,
        "is-in-person": is_in_person,
    }

    # Generate groups
    groups = []
    if has_admin_group:
        groups.append("NomNom Admin")
    # Add some random groups for variation
    for _ in range(fake.random_int(min=0, max=3)):
        groups.append(fake.word().title() + " Group")
    base_response["groups"] = groups

    # Generate reg-id in various formats
    base_name = fake.user_name()
    if reg_id_format == "standard":
        base_response["reg-id"] = f"member-{fake.random_int(min=1000, max=99999)}"
    elif reg_id_format == "hyphenated":
        base_response["reg-id"] = f"test-{base_name}.staging.id"
    elif reg_id_format == "dots":
        base_response["reg-id"] = f"{base_name}.{fake.random_int(min=100, max=999)}.id"
    elif reg_id_format == "short":
        base_response["reg-id"] = f"{fake.random_int(min=100, max=999)}"

    # Generate names - priority is badge-name > name > given_name > nickname
    first_name = fake.first_name()
    last_name = fake.last_name()

    if use_badge_name:
        base_response["badge-name"] = fake.name_nonbinary()

    if use_name:
        base_response["name"] = f"{first_name} {last_name}"

    if use_given_name:
        base_response["given_name"] = f"{first_name} {last_name}"

    if use_nickname:
        base_response["nickname"] = fake.user_name()
        base_response["preferred_username"] = base_response["nickname"]

    return base_response


# Test parameter combinations
ADMIN_PERMISSIONS = [True, False]
admin_permissions_param = pytest.mark.parametrize(
    "has_admin_group", ADMIN_PERMISSIONS, ids=["admin", "non_admin"]
)

HUGO_PERMISSIONS = [
    (False, False),  # can't nominate, can't vote
    (True, False),  # can nominate, can't vote
    (False, True),  # can't nominate, can vote
    (True, True),  # can nominate and vote
]
hugo_permissions_param = pytest.mark.parametrize(
    "can_nominate,can_vote",
    HUGO_PERMISSIONS,
    ids=["none", "nominate_only", "vote_only", "both"],
)

MEMBERSHIP_TYPES = ["Unknown", "Adult", "Supporting", "Youth", "Child"]
membership_type_param = pytest.mark.parametrize("membership_type", MEMBERSHIP_TYPES)

REG_ID_FORMATS = ["standard", "hyphenated", "dots", "short"]
reg_id_format_param = pytest.mark.parametrize("reg_id_format", REG_ID_FORMATS)

NAME_VARIATIONS = [
    (True, True, True, True),  # has badge (highest priority), name, given, nickname
    (True, False, True, True),  # has badge, no name, has given, has nickname
    (True, False, False, True),  # has badge, no name, no given, has nickname
    (False, True, True, True),  # no badge, has name (next priority), given, nickname
    (False, True, False, True),  # no badge, has name, no given, has nickname
    (
        False,
        False,
        True,
        True,
    ),  # no badge, no name, has given (next priority), has nickname
    (False, False, True, False),  # no badge, no name, has given, no nickname
    (
        False,
        False,
        False,
        True,
    ),  # no badge, no name, no given, only nickname (lowest priority)
]
name_variations_param = pytest.mark.parametrize(
    "use_badge,use_name,use_given,use_nickname",
    NAME_VARIATIONS,
    ids=[
        "badge_priority",
        "badge_no_name",
        "badge_minimal",
        "name_priority",
        "name_no_given",
        "given_priority",
        "given_no_nickname",
        "nickname_only",
    ],
)
in_person_param = pytest.mark.parametrize(
    "is_in_person", [True, False], ids=["in_person", "virtual"]
)

site_selection_param = pytest.mark.parametrize(
    "can_site_vote", [True, False], ids=["can_site_vote", "cannot_site_vote"]
)


class TestAdaptRegidToUsername:
    @reg_id_format_param
    def test_extracts_regid_as_username_and_member_number(
        self, mock_strategy, test_user, reg_id_format
    ):
        response = generate_auth_response(reg_id_format=reg_id_format)
        details = {}

        adapt_regid_to_username(mock_strategy, details, test_user, response=response)

        assert details["username"] == response["reg-id"]
        assert details["member_number"] == response["reg-id"]

    def test_handles_missing_regid(self, mock_strategy, test_user):
        details = {}
        response = {"email": fake.email()}

        adapt_regid_to_username(mock_strategy, details, test_user, response=response)

        assert "username" not in details
        assert "member_number" not in details

    @reg_id_format_param
    def test_preserves_existing_details(self, mock_strategy, test_user, reg_id_format):
        response = generate_auth_response(reg_id_format=reg_id_format)
        details = {"existing_field": "preserved"}

        adapt_regid_to_username(mock_strategy, details, test_user, response=response)

        assert details["existing_field"] == "preserved"
        assert details["username"] == response["reg-id"]


class TestGetWsfsPermissions:
    @hugo_permissions_param
    def test_extracts_hugo_permissions(
        self, mock_strategy, test_user, can_nominate, can_vote
    ):
        response = generate_auth_response(can_nominate=can_nominate, can_vote=can_vote)
        details = {}

        get_wsfs_permissions(mock_strategy, details, test_user, response=response)

        assert details["can_nominate"] is can_nominate
        assert details["can_vote"] is can_vote

    @site_selection_param
    def test_extracts_site_selection_permissions(
        self, mock_strategy, test_user, can_site_vote
    ):
        response = generate_auth_response(can_site_selection_vote=can_site_vote)
        details = {}

        get_wsfs_permissions(mock_strategy, details, test_user, response=response)

        assert details["site_selection_can_vote"] is can_site_vote

    @admin_permissions_param
    def test_detects_admin_group(self, mock_strategy, test_user, has_admin_group):
        response = generate_auth_response(has_admin_group=has_admin_group)
        details = {}

        get_wsfs_permissions(mock_strategy, details, test_user, response=response)

        assert details["is_admin"] is has_admin_group

    def test_handles_missing_permissions(self, mock_strategy, test_user):
        details = {}
        response = {"email": fake.email()}

        get_wsfs_permissions(mock_strategy, details, test_user, response=response)

        assert details["can_nominate"] is False
        assert details["can_vote"] is False
        assert details["site_selection_can_vote"] is False
        assert details["is_admin"] is False


class TestAdaptPersonalInformation:
    @name_variations_param
    def test_name_handling_variations(
        self,
        mock_strategy,
        test_user,
        use_badge,
        use_name,
        use_given,
        use_nickname,
    ):
        response = generate_auth_response(
            use_badge_name=use_badge,
            use_name=use_name,
            use_given_name=use_given,
            use_nickname=use_nickname,
        )
        details = {}

        adapt_personal_information(mock_strategy, details, test_user, response=response)

        # Test that we get some kind of name - priority: badge-name > name > given_name > nickname
        if use_badge:
            expected_name = response["badge-name"]
            name_parts = expected_name.split()
            assert details["first_name"] == name_parts[0]
            if len(name_parts) > 1:
                assert details["last_name"] == " ".join(name_parts[1:])
            assert details["preferred_name"] == expected_name
        elif use_name:
            expected_name = response["name"]
            name_parts = expected_name.split()
            assert details["first_name"] == name_parts[0]
            if len(name_parts) > 1:
                assert details["last_name"] == " ".join(name_parts[1:])
            assert details["preferred_name"] == expected_name
        elif use_given:
            expected_name = response["given_name"]
            name_parts = expected_name.split()
            assert details["first_name"] == name_parts[0]
            if len(name_parts) > 1:
                assert details["last_name"] == " ".join(name_parts[1:])
            assert details["preferred_name"] == expected_name
        elif use_nickname:
            assert details["first_name"] == response["nickname"]
            assert details["preferred_name"] == response["nickname"]

    @membership_type_param
    @in_person_param
    def test_maps_membership_info(
        self, mock_strategy, test_user, membership_type, is_in_person
    ):
        response = generate_auth_response(
            membership_type=membership_type, is_in_person=is_in_person
        )
        details = {}

        adapt_personal_information(mock_strategy, details, test_user, response=response)

        assert details["membership_type"] == membership_type
        assert details["is_in_person"] is is_in_person

    def test_maps_email(self, mock_strategy, test_user):
        response = generate_auth_response()
        details = {}

        adapt_personal_information(mock_strategy, details, test_user, response=response)

        assert details["email"] == response["email"]

    def test_handles_missing_fields(self, mock_strategy, test_user):
        details = {}
        # the reg-id is required at this point in the pipeline
        response = {"reg-id": "member-12345"}

        adapt_personal_information(mock_strategy, details, test_user, response=response)

        assert details["first_name"] == "WSFS"
        assert "email" not in details
        assert details["membership_type"] is None
        assert details["is_in_person"] is False


class TestStoreFullMembershipData:
    def test_stores_complete_response(self, mock_strategy, test_user):
        response = generate_auth_response()
        details = {}

        store_full_membership_data(mock_strategy, details, test_user, response=response)

        assert details["full_response"] == response
        assert details["full_response"]["reg-id"] == response["reg-id"]
        assert details["full_response"]["email"] == response["email"]

    def test_creates_copy_not_reference(self, mock_strategy, test_user):
        response = generate_auth_response()
        details = {}

        store_full_membership_data(mock_strategy, details, test_user, response=response)

        # Modify original response
        response["new_field"] = "added"

        # Stored copy should not be affected
        assert "new_field" not in details["full_response"]

    def test_handles_empty_response(self, mock_strategy, test_user):
        details = {}
        response = {}

        store_full_membership_data(mock_strategy, details, test_user, response=response)

        assert details["full_response"] == {}


class TestPipelineIntegration:
    @admin_permissions_param
    @hugo_permissions_param
    @membership_type_param
    @reg_id_format_param
    def test_full_pipeline_variations(
        self,
        mock_strategy,
        test_user,
        has_admin_group,
        can_nominate,
        can_vote,
        membership_type,
        reg_id_format,
    ):
        """Test running all pipeline functions with various parameter combinations"""
        response = generate_auth_response(
            has_admin_group=has_admin_group,
            can_nominate=can_nominate,
            can_vote=can_vote,
            membership_type=membership_type,
            reg_id_format=reg_id_format,
        )
        details = {}

        # Run pipeline functions in order
        adapt_regid_to_username(mock_strategy, details, test_user, response=response)
        get_wsfs_permissions(mock_strategy, details, test_user, response=response)
        adapt_personal_information(mock_strategy, details, test_user, response=response)
        store_full_membership_data(mock_strategy, details, test_user, response=response)

        # Verify all expected fields are set
        assert details["username"] == response["reg-id"]
        assert details["member_number"] == response["reg-id"]
        assert details["can_nominate"] is can_nominate
        assert details["can_vote"] is can_vote
        assert details["is_admin"] is has_admin_group
        assert details["membership_type"] == membership_type
        assert details["full_response"] == response

        # Verify name fields are populated
        assert "first_name" in details
        assert "preferred_name" in details
        assert "email" in details

    def test_pipeline_preserves_order_independence(self, mock_strategy, test_user):
        """Test that pipeline functions don't interfere with each other"""
        response = generate_auth_response()
        details1 = {}
        details2 = {}

        # Run in different orders
        adapt_regid_to_username(mock_strategy, details1, test_user, response=response)
        adapt_personal_information(
            mock_strategy, details1, test_user, response=response
        )
        get_wsfs_permissions(mock_strategy, details1, test_user, response=response)

        get_wsfs_permissions(mock_strategy, details2, test_user, response=response)
        adapt_regid_to_username(mock_strategy, details2, test_user, response=response)
        adapt_personal_information(
            mock_strategy, details2, test_user, response=response
        )

        # Results should be identical regardless of order
        for key in ["username", "can_nominate", "first_name", "email"]:
            assert details1[key] == details2[key]


class TestCreateUser:
    @reg_id_format_param
    def test_creates_new_user_with_pipeline_data(
        self, mock_strategy, db, reg_id_format
    ):
        """Test creating a new user with data from pipeline functions"""
        response = generate_auth_response(reg_id_format=reg_id_format)
        details = {}

        # Run pipeline functions to populate details
        adapt_regid_to_username(mock_strategy, details, None, response=response)
        adapt_personal_information(mock_strategy, details, None, response=response)

        # Now create user with pipeline data
        result = create_user(mock_strategy, details, user=None, response=response)

        assert result["is_new"] is True
        user = result["user"]
        assert user.username == response["reg-id"]
        assert user.email == response["email"]
        assert "first_name" in details

    def test_creates_user_with_partial_fields(self, mock_strategy, db):
        """Test creating a user when some fields are missing"""
        details = {
            "username": fake.user_name(),
            "email": fake.email(),
            "first_name": fake.first_name(),
            # last_name is missing
        }
        response = {}

        result = create_user(mock_strategy, details, user=None, response=response)

        assert result["is_new"] is True
        user = result["user"]
        assert user.username == details["username"]
        assert user.email == details["email"]
        assert user.first_name == details["first_name"]
        assert user.last_name == ""  # should default to empty string

    def test_handles_empty_email(self, mock_strategy, db):
        """Test creating a user with empty email"""
        details = {
            "username": fake.user_name(),
            "first_name": fake.first_name(),
            "last_name": fake.last_name(),
        }
        response = {}

        result = create_user(mock_strategy, details, user=None, response=response)

        assert result["is_new"] is True
        user = result["user"]
        assert user.username == details["username"]
        assert user.email == ""

    def test_returns_existing_user_without_creating_new_one(
        self, mock_strategy, test_user
    ):
        """Test that if user already exists, it returns the existing user"""
        details = {
            "username": fake.user_name(),
            "email": fake.email(),
        }
        response = {}

        result = create_user(mock_strategy, details, user=test_user, response=response)

        assert result["user"] == test_user
        assert "is_new" not in result

    def test_filters_out_none_values(self, mock_strategy, db):
        """Test that None values are filtered out to avoid validation errors"""
        details = {
            "username": fake.user_name(),
            "email": None,  # This should be filtered out
            "first_name": fake.first_name(),
            "last_name": None,  # This should be filtered out
        }
        response = {}

        result = create_user(mock_strategy, details, user=None, response=response)

        assert result["is_new"] is True
        user = result["user"]
        assert user.username == details["username"]
        assert user.first_name == details["first_name"]
        # None values should not cause issues

    def test_with_missing_username(self, mock_strategy, db):
        """Test behavior when username is missing"""
        email = fake.email()
        details = {
            "email": email,
            "first_name": fake.first_name(),
            "last_name": fake.last_name(),
        }
        response = {"email": email}

        result = create_user(mock_strategy, details, user=None, response=response)

        assert result["is_new"] is True
        user = result["user"]
        # Username should be generated from email when missing
        assert user.username == f"user_{email}"
        assert user.email == email

    def test_with_missing_username_and_email(self, mock_strategy, db):
        """Test behavior when both username and email are missing"""
        details = {
            "first_name": fake.first_name(),
            "last_name": fake.last_name(),
        }
        response = {}

        result = create_user(mock_strategy, details, user=None, response=response)

        assert result["is_new"] is True
        user = result["user"]
        # Username should fallback to anonymous when no email available
        assert user.username == "user_anonymous"
        assert user.email == ""


class TestUpdateUserDetails:
    def test_updates_email_when_provider_gives_different_email(
        self, mock_strategy, test_user, db
    ):
        """Test that user's email is updated when auth provider returns different email"""
        # Setup: User has original email
        original_email = test_user.email
        new_email = fake.email()

        # Details with different email
        details = {
            "email": new_email,
            "first_name": test_user.first_name,
            "last_name": test_user.last_name,
        }
        response = {}

        # Update user details
        update_user_details(mock_strategy, details, test_user, response=response)
        test_user.refresh_from_db()

        # Verify email was updated
        assert test_user.email == new_email
        assert test_user.email != original_email

    def test_updates_first_name_when_changed(self, mock_strategy, test_user, db):
        """Test that user's first name is updated when changed"""
        original_first_name = test_user.first_name
        new_first_name = fake.first_name()

        details = {
            "email": test_user.email,
            "first_name": new_first_name,
            "last_name": test_user.last_name,
        }
        response = {}

        update_user_details(mock_strategy, details, test_user, response=response)
        test_user.refresh_from_db()

        assert test_user.first_name == new_first_name
        assert test_user.first_name != original_first_name

    def test_updates_last_name_when_changed(self, mock_strategy, test_user, db):
        """Test that user's last name is updated when changed"""
        original_last_name = test_user.last_name
        new_last_name = fake.last_name()

        details = {
            "email": test_user.email,
            "first_name": test_user.first_name,
            "last_name": new_last_name,
        }
        response = {}

        update_user_details(mock_strategy, details, test_user, response=response)
        test_user.refresh_from_db()

        assert test_user.last_name == new_last_name
        assert test_user.last_name != original_last_name

    def test_updates_multiple_fields_at_once(self, mock_strategy, test_user, db):
        """Test that multiple fields can be updated simultaneously"""
        new_email = fake.email()
        new_first_name = fake.first_name()
        new_last_name = fake.last_name()

        details = {
            "email": new_email,
            "first_name": new_first_name,
            "last_name": new_last_name,
        }
        response = {}

        update_user_details(mock_strategy, details, test_user, response=response)
        test_user.refresh_from_db()

        assert test_user.email == new_email
        assert test_user.first_name == new_first_name
        assert test_user.last_name == new_last_name

    def test_does_not_update_when_values_unchanged(self, mock_strategy, test_user, db):
        """Test that user is not saved when values are unchanged"""
        original_email = test_user.email
        original_first_name = test_user.first_name
        original_last_name = test_user.last_name

        details = {
            "email": original_email,
            "first_name": original_first_name,
            "last_name": original_last_name,
        }
        response = {}

        # Track the updated_at field if it exists, or just verify values don't change
        update_user_details(mock_strategy, details, test_user, response=response)
        test_user.refresh_from_db()

        # Values should remain the same
        assert test_user.email == original_email
        assert test_user.first_name == original_first_name
        assert test_user.last_name == original_last_name

    def test_handles_missing_user(self, mock_strategy, db):
        """Test that function returns early when user is None"""
        details = {
            "email": fake.email(),
            "first_name": fake.first_name(),
            "last_name": fake.last_name(),
        }
        response = {}

        # Should not raise any errors
        result = update_user_details(
            mock_strategy, details, user=None, response=response
        )
        assert result is None

    def test_handles_missing_fields_in_details(self, mock_strategy, test_user, db):
        """Test that function handles missing fields in details gracefully"""
        original_email = test_user.email
        original_first_name = test_user.first_name
        original_last_name = test_user.last_name

        # Empty details
        details = {}
        response = {}

        update_user_details(mock_strategy, details, test_user, response=response)
        test_user.refresh_from_db()

        # Values should remain unchanged
        assert test_user.email == original_email
        assert test_user.first_name == original_first_name
        assert test_user.last_name == original_last_name

    def test_integration_with_full_pipeline(self, mock_strategy, test_user, db):
        """Test update_user_details with full pipeline data"""
        # Setup: User has original values
        original_email = test_user.email

        # Auth response with different email
        response = generate_auth_response()
        new_email = fake.email()
        response["email"] = new_email

        details = {}

        # Run pipeline functions to populate details
        adapt_regid_to_username(mock_strategy, details, test_user, response=response)
        adapt_personal_information(mock_strategy, details, test_user, response=response)

        # Update user with new details
        update_user_details(mock_strategy, details, test_user, response=response)
        test_user.refresh_from_db()

        # Email should be updated
        assert test_user.email == new_email
        assert test_user.email != original_email


class TestEmailUpdate:
    def test_user_email_updated_when_provider_gives_different_email(
        self, mock_strategy, test_user, db
    ):
        """Test that user's email is updated when auth provider returns different email"""
        # Setup: User has original email
        original_email = test_user.email
        new_email = fake.email()

        # Auth response with different email
        response = generate_auth_response()
        response["email"] = new_email

        details = {}

        # Run through the pipeline
        adapt_regid_to_username(mock_strategy, details, test_user, response=response)
        adapt_personal_information(mock_strategy, details, test_user, response=response)

        # Email should be in details with new value
        assert details["email"] == new_email
        assert details["email"] != original_email

        # Now update the user with the new details
        update_user_details(mock_strategy, details, test_user, response=response)
        test_user.refresh_from_db()

        # Verify email was updated
        assert test_user.email == new_email
        assert test_user.email != original_email

    def test_user_email_updated_for_existing_user_on_login(self, mock_strategy, db):
        """Test that existing user's email gets updated when they log in with new email"""
        # Create an existing user with an email
        username = fake.user_name()
        original_email = fake.email()
        user = User.objects.create_user(
            username=username,
            email=original_email,
            first_name=fake.first_name(),
            last_name=fake.last_name(),
        )

        # Auth provider returns different email
        new_email = fake.email()
        response = generate_auth_response()
        response["email"] = new_email
        response["reg-id"] = username  # Same user

        details = {}

        # Run pipeline for existing user
        adapt_regid_to_username(mock_strategy, details, user, response=response)
        adapt_personal_information(mock_strategy, details, user, response=response)

        # Email in details should be the new one
        assert details["email"] == new_email

        # Update user details
        update_user_details(mock_strategy, details, user, response=response)
        user.refresh_from_db()

        # Verify update
        assert user.email == new_email
        assert user.email != original_email


class TestSessionDuration:
    def test_default_session_duration_is_six_months(self, client, settings):
        """Test that the default session duration is 6 months (approximately 180 days)"""
        # Django's default SESSION_COOKIE_AGE is 2 weeks (1209600 seconds)
        # 6 months is approximately 15552000 seconds (180 days * 24 hours * 60 minutes * 60 seconds)
        six_months_in_seconds = 180 * 24 * 60 * 60

        # Check the configured session cookie age
        session_age = getattr(settings, "SESSION_COOKIE_AGE", 1209600)

        # Assert that the session age is set to 6 months
        assert session_age == six_months_in_seconds, (
            f"Expected SESSION_COOKIE_AGE to be {six_months_in_seconds} seconds (6 months), "
            f"but got {session_age} seconds"
        )


class TestSetMemberDetails:
    def test_does_nothing_when_user_is_none(self, mock_strategy):
        """Test that function returns early when user is None"""
        details = {"preferred_name": fake.name()}
        response = {}

        # Should not raise any errors
        result = set_member_details(
            mock_strategy, details, user=None, response=response
        )
        assert result is None

    @admin_permissions_param
    def test_sets_admin_permissions(self, mock_strategy, test_user, has_admin_group):
        """Test setting admin permissions on user"""
        details = {
            "is_admin": has_admin_group,
            "member_number": fake.random_int(min=1000, max=9999),
        }
        response = {}

        set_member_details(mock_strategy, details, user=test_user, response=response)

        assert test_user.is_staff is has_admin_group

    def test_handles_missing_admin_flag(self, mock_strategy, test_user):
        """Test behavior when is_admin is not in details"""
        details = {
            "preferred_name": fake.name(),
            "member_number": fake.random_int(min=1000, max=9999),
        }
        response = {}

        # Store original values
        original_staff = test_user.is_staff

        set_member_details(mock_strategy, details, user=test_user, response=response)

        # Values should remain unchanged
        assert test_user.is_staff == original_staff

    @admin_permissions_param
    @hugo_permissions_param
    def test_integration_with_full_pipeline(
        self, mock_strategy, test_user, has_admin_group, can_nominate, can_vote
    ):
        """Test set_member_details with full pipeline data"""
        response = generate_auth_response(
            has_admin_group=has_admin_group,
            can_nominate=can_nominate,
            can_vote=can_vote,
        )
        details = {}

        # Run pipeline functions to populate details
        adapt_regid_to_username(mock_strategy, details, test_user, response=response)
        get_wsfs_permissions(mock_strategy, details, test_user, response=response)
        adapt_personal_information(mock_strategy, details, test_user, response=response)

        # Now set member details
        set_member_details(mock_strategy, details, user=test_user, response=response)

        # Should set admin permissions based on response data
        assert test_user.is_staff is has_admin_group

        # Verify that user details include the voting/nominating permissions
        assert details["can_nominate"] is can_nominate
        assert details["can_vote"] is can_vote

    def test_ignores_fields_not_on_user_model(self, mock_strategy, test_user):
        """Test that fields not on user model are safely ignored"""
        details = {
            "preferred_name": fake.name(),
            "member_number": fake.random_int(min=1000, max=9999),
            "is_admin": True,  # This should still work for standard fields
        }
        response = {}

        # Should not raise AttributeError even if user doesn't have custom fields
        set_member_details(mock_strategy, details, user=test_user, response=response)

        # Standard fields should still be set
        assert test_user.is_staff is True
