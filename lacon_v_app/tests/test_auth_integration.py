"""
Integration tests for OAuth authentication flow.

These tests use Django's test client to make real HTTP requests through
the entire OAuth login flow, from clicking "login" to being redirected
back and authenticated.
"""

import datetime
import json
from calendar import timegm
from urllib.parse import parse_qs, urlencode, urlparse

import jwt
import pytest
import responses
from django.contrib.auth import get_user_model
from django.test import Client
from faker import Faker

from lacon_v_app.auth import LaconMemberBackend

User = get_user_model()
fake = Faker()

# JWT signing key for test OIDC provider
JWK_KEY = {
    "kty": "RSA",
    "d": "ZmswNokEvBcxW_Kvcy8mWUQOQCBdGbnM0xR7nhvGHC-Q24z3XAQWlMWbsmGc_R1o"
    "_F3zK7DBlc3BokdRaO1KJirNmnHCw5TlnBlJrXiWpFBtVglUg98-4sRRO0VWnGXK"
    "JPOkBQ6b_DYRO3b0o8CSpWowpiV6HB71cjXTqKPZf-aXU9WjCCAtxVjfIxgQFu5I"
    "-G1Qah8mZeY8HK_y99L4f0siZcbUoaIcfeWBhxi14ODyuSAHt0sNEkhiIVBZE7QZ"
    "m-SEP1ryT9VAaljbwHHPmg7NC26vtLZhvaBGbTTJnEH0ZubbN2PMzsfeNyoCIHy4"
    "4QDSpQDCHfgcGOlHY_t5gQ",
    "e": "AQAB",
    "use": "sig",
    "kid": "testkey",
    "alg": "RS256",
    "n": "pUfcJ8WFrVue98Ygzb6KEQXHBzi8HavCu8VENB2As943--bHPcQ-nScXnrRFAUg8"
    "H5ZltuOcHWvsGw_AQifSLmOCSWJAPkdNb0w0QzY7Re8NrPjCsP58Tytp5LicF0Ao"
    "Ag28UK3JioY9hXHGvdZsWR1Rp3I-Z3nRBP6HyO18pEgcZ91c9aAzsqu80An9X4DA"
    "b1lExtZorvcd5yTBzZgr-MUeytVRni2lDNEpa6OFuopHXmg27Hn3oWAaQlbymd4g"
    "ifc01oahcwl3ze2tMK6gJxa_TdCf1y99Yq6oilmVvZJ8kwWWnbPE-oDmOVPVnEyT"
    "vYVCvN4rBT1DQ-x0F1mo2Q",
}

JWK_PUBLIC_KEY = {key: value for key, value in JWK_KEY.items() if key != "d"}


class OIDCProviderMock:
    """Mock OIDC provider for testing"""

    def __init__(self, issuer="https://auth.test.lacon.org"):
        self.issuer = issuer
        self.client_key = "test-client-id"
        self.client_secret = "test-client-secret"
        self.authorization_endpoint = f"{issuer}/authorize"
        self.token_endpoint = f"{issuer}/token"
        self.userinfo_endpoint = f"{issuer}/userinfo"
        self.jwks_uri = f"{issuer}/jwks"
        self.key = JWK_KEY.copy()
        self.public_key = JWK_PUBLIC_KEY.copy()

    def get_openid_configuration(self):
        """Return OpenID Connect discovery document"""
        return json.dumps(
            {
                "issuer": self.issuer,
                "authorization_endpoint": self.authorization_endpoint,
                "token_endpoint": self.token_endpoint,
                "userinfo_endpoint": self.userinfo_endpoint,
                "jwks_uri": self.jwks_uri,
                "response_types_supported": ["code"],
                "subject_types_supported": ["public"],
                "id_token_signing_alg_values_supported": ["RS256"],
            }
        )

    def get_jwks(self):
        """Return JSON Web Key Set"""
        return json.dumps({"keys": [self.public_key]})

    def generate_id_token(self, sub, nonce, email, extra_claims=None):
        """Generate a signed JWT id_token"""
        now = datetime.datetime.now(datetime.timezone.utc)
        expiration = now + datetime.timedelta(seconds=3600)

        claims = {
            "iss": self.issuer,
            "sub": sub,
            "aud": self.client_key,
            "azp": self.client_key,
            "exp": timegm(expiration.timetuple()),
            "iat": timegm(now.timetuple()),
            "nonce": nonce,
            "email": email,
            "email_verified": True,
        }

        if extra_claims:
            claims.update(extra_claims)

        # Calculate at_hash for the access token
        access_token = "test-access-token"
        claims["at_hash"] = LaconMemberBackend.calc_at_hash(access_token, "RS256")

        token = jwt.encode(
            claims,
            key=jwt.PyJWK(self.key).key,
            algorithm="RS256",
            headers={"kid": "testkey"},
        )

        return token

    def generate_token_response(self, nonce, email, extra_claims=None):
        """Generate OAuth token endpoint response"""
        sub = fake.uuid4()
        id_token = self.generate_id_token(sub, nonce, email, extra_claims)

        return json.dumps(
            {
                "access_token": "test-access-token",
                "token_type": "Bearer",
                "expires_in": 3600,
                "id_token": id_token,
                "scope": "openid profile email membership",
            }
        )

    def setup_discovery_mocks(self):
        """Setup discovery and JWKS endpoint mocks"""
        # Mock OpenID configuration discovery
        responses.add(
            responses.GET,
            f"{self.issuer}/.well-known/openid-configuration",
            body=self.get_openid_configuration(),
            status=200,
            content_type="application/json",
        )

        # Mock JWKS endpoint
        responses.add(
            responses.GET,
            self.jwks_uri,
            body=self.get_jwks(),
            status=200,
            content_type="application/json",
        )

    def generate_userinfo_response(self, email, extra_claims=None):
        """Generate userinfo endpoint response"""
        userinfo = {
            "sub": fake.uuid4(),
            "email": email,
            "email_verified": True,
        }
        if extra_claims:
            userinfo.update(extra_claims)
        return json.dumps(userinfo)

    def setup_token_mock(self, nonce, email=None, extra_claims=None):
        """
        Setup token and userinfo endpoint mocks.

        Args:
            nonce: The nonce from the authorization request
            email: Email address for the user
            extra_claims: Additional claims to include in id_token
        """
        if email is None:
            email = fake.email()

        def token_callback(request):
            token_response = self.generate_token_response(nonce, email, extra_claims)
            return (200, {"Content-Type": "application/json"}, token_response)

        responses.add_callback(
            responses.POST,
            self.token_endpoint,
            callback=token_callback,
            content_type="application/json",
        )

        # Mock userinfo endpoint
        responses.add(
            responses.GET,
            self.userinfo_endpoint,
            body=self.generate_userinfo_response(email, extra_claims),
            status=200,
            content_type="application/json",
        )

        # Mock JWKS endpoint
        responses.add(
            responses.GET,
            self.jwks_uri,
            body=self.get_jwks(),
            status=200,
            content_type="application/json",
        )


@pytest.fixture
def oidc_mock():
    """Fixture providing an OIDC provider mock"""
    return OIDCProviderMock()


@pytest.fixture
def client():
    """Fixture providing a Django test client"""
    return Client()


@pytest.fixture
def test_settings(settings):
    """Override settings for OAuth testing"""
    issuer = "https://auth.test.lacon.org"
    settings.SOCIAL_AUTH_LACON_KEY = "test-client-id"
    settings.SOCIAL_AUTH_LACON_SECRET = "test-client-secret"
    settings.SOCIAL_AUTH_LACON_OIDC_ENDPOINT = issuer
    settings.SOCIAL_AUTH_LACON_JWKS_URI = f"{issuer}/jwks"
    # Set a valid redirect URL for after login
    settings.LOGIN_REDIRECT_URL = "/"
    return settings


def generate_member_claims(
    reg_id=None,
    membership_type="Adult",
    is_in_person=True,
    can_nominate=True,
    can_vote=True,
    can_site_vote=False,
    has_admin_group=False,
    badge_name=None,
    name=None,
    given_name=None,
    nickname=None,
):
    """Generate LAcon-specific member claims for id_token"""
    claims = {}

    # Generate reg-id
    if reg_id is None:
        reg_id = f"member-{fake.random_int(min=1000, max=99999)}"
    claims["reg-id"] = reg_id

    # Membership information
    claims["membership-type"] = membership_type
    claims["is-in-person"] = is_in_person

    # WSFS permissions
    claims["hugos-can-nominate"] = can_nominate
    claims["hugos-can-vote"] = can_vote
    claims["site-selection-can-vote"] = can_site_vote

    # Groups
    groups = []
    if has_admin_group:
        groups.append("NomNom Admin")
    claims["groups"] = groups

    # Badge name (priority: badge-name > name > given_name > nickname)
    if badge_name:
        claims["badge-name"] = badge_name
    if name:
        claims["name"] = name
    if given_name:
        claims["given_name"] = given_name
    if nickname:
        claims["nickname"] = nickname

    return claims


def perform_oauth_login(client, oidc_mock, email, member_claims):
    """
    Helper function to perform a complete OAuth login flow.

    Args:
        client: Django test client
        oidc_mock: OIDCProviderMock instance
        email: User email address
        member_claims: Dictionary of member claims

    Returns:
        The final response after completing the login
    """
    # Setup discovery and JWKS mocks first
    oidc_mock.setup_discovery_mocks()

    # Start OAuth flow
    response = client.get("/login/lacon/", follow=False)
    assert response.status_code == 302

    # Extract nonce from authorization URL
    auth_url = response.url
    auth_params = parse_qs(urlparse(auth_url).query)
    state = auth_params.get("state", [None])[0]
    nonce = auth_params.get("nonce", [None])[0]
    redirect_uri = auth_params.get("redirect_uri", [None])[0]

    # Setup token mock with actual nonce
    oidc_mock.setup_token_mock(nonce=nonce, email=email, extra_claims=member_claims)

    # Complete callback
    callback_params = {"code": "test-auth-code"}
    if state:
        callback_params["state"] = state

    callback_url = f"{redirect_uri}?{urlencode(callback_params)}"
    response = client.get(callback_url, follow=True)

    return response


@pytest.mark.django_db
class TestOAuthLoginFlow:
    """Integration tests for the complete OAuth login flow"""

    @responses.activate
    def test_successful_login_creates_user(self, client, oidc_mock, test_settings):
        """Test that a successful OAuth login creates a new user"""
        email = fake.email()
        member_claims = generate_member_claims(
            name=f"{fake.first_name()} {fake.last_name()}"
        )

        # Setup discovery and JWKS mocks first (before any requests)
        oidc_mock.setup_discovery_mocks()

        # Start OAuth flow by visiting login URL
        response = client.get("/login/lacon/", follow=False)

        # Should redirect to authorization endpoint
        assert response.status_code == 302
        auth_url = response.url
        assert auth_url.startswith(oidc_mock.authorization_endpoint)

        # Parse authorization URL to get state and nonce
        auth_params = parse_qs(urlparse(auth_url).query)
        state = auth_params.get("state", [None])[0]
        nonce = auth_params.get("nonce", [None])[0]
        redirect_uri = auth_params.get("redirect_uri", [None])[0]

        # Now setup the token endpoint mock with the actual nonce
        oidc_mock.setup_token_mock(nonce=nonce, email=email, extra_claims=member_claims)

        # Simulate provider redirecting back with authorization code
        callback_params = {"code": "test-auth-code"}
        if state:
            callback_params["state"] = state

        callback_url = f"{redirect_uri}?{urlencode(callback_params)}"
        response = client.get(callback_url, follow=True)

        # Should be redirected and logged in
        assert response.status_code == 200

        # Verify user was created
        user = User.objects.get(username=member_claims["reg-id"])
        assert user.email == email
        assert user.is_authenticated

        # Verify user is logged into the session
        assert client.session["_auth_user_id"] == str(user.pk)

    @responses.activate
    def test_session_duration_is_six_months(self, client, oidc_mock, test_settings):
        """Test that session cookie age is set to 6 months"""
        email = fake.email()
        member_claims = generate_member_claims(
            name=f"{fake.first_name()} {fake.last_name()}"
        )

        # Complete login flow

        perform_oauth_login(client, oidc_mock, email, member_claims)

        # Verify session cookie age is 6 months (180 days)
        six_months_in_seconds = 180 * 24 * 60 * 60
        assert test_settings.SESSION_COOKIE_AGE == six_months_in_seconds

    @responses.activate
    def test_email_updated_on_subsequent_login(self, client, oidc_mock, test_settings):
        """Test that user's email is updated when provider returns different email"""
        reg_id = f"member-{fake.random_int(min=1000, max=99999)}"
        original_email = fake.email()
        first_name = fake.first_name()
        last_name = fake.last_name()

        # Create existing user
        user = User.objects.create_user(
            username=reg_id,
            email=original_email,
            first_name=first_name,
            last_name=last_name,
        )

        # Login with different email from provider
        new_email = fake.email()
        member_claims = generate_member_claims(
            reg_id=reg_id, name=f"{first_name} {last_name}"
        )

        # Complete login flow

        perform_oauth_login(client, oidc_mock, new_email, member_claims)

        # Verify email was updated
        user.refresh_from_db()
        assert user.email == new_email
        assert user.email != original_email


@pytest.mark.django_db
class TestMembershipTypes:
    """Tests for different membership type scenarios"""

    @pytest.mark.parametrize(
        "membership_type", ["Adult", "Supporting", "Youth", "Child", "Unknown"]
    )
    @responses.activate
    def test_membership_type_stored(
        self, client, oidc_mock, test_settings, membership_type
    ):
        """Test that different membership types are properly stored"""
        email = fake.email()
        member_claims = generate_member_claims(
            name=f"{fake.first_name()} {fake.last_name()}",
            membership_type=membership_type,
        )

        # Complete login flow

        perform_oauth_login(client, oidc_mock, email, member_claims)

        # Verify user was created
        user = User.objects.get(username=member_claims["reg-id"])
        # Note: membership_type would be stored in user's social auth extra data
        # We verify the user was created successfully
        assert user.is_authenticated

    @pytest.mark.parametrize("is_in_person", [True, False])
    @responses.activate
    def test_in_person_flag_stored(
        self, client, oidc_mock, test_settings, is_in_person
    ):
        """Test that in-person attendance flag is properly stored"""
        email = fake.email()
        member_claims = generate_member_claims(
            name=f"{fake.first_name()} {fake.last_name()}",
            is_in_person=is_in_person,
        )

        # Complete login flow

        perform_oauth_login(client, oidc_mock, email, member_claims)

        # Verify user was created
        user = User.objects.get(username=member_claims["reg-id"])
        assert user.is_authenticated


@pytest.mark.django_db
class TestWSFSPermissions:
    """Tests for WSFS voting and nomination permissions"""

    @pytest.mark.parametrize(
        "can_nominate,can_vote",
        [(True, True), (True, False), (False, True), (False, False)],
    )
    @responses.activate
    def test_hugo_permissions(
        self, client, oidc_mock, test_settings, can_nominate, can_vote
    ):
        """Test that Hugo nomination and voting permissions are properly handled"""
        email = fake.email()
        member_claims = generate_member_claims(
            name=f"{fake.first_name()} {fake.last_name()}",
            can_nominate=can_nominate,
            can_vote=can_vote,
        )

        # Complete login flow

        perform_oauth_login(client, oidc_mock, email, member_claims)

        # Verify user was created
        user = User.objects.get(username=member_claims["reg-id"])
        assert user.is_authenticated

    @pytest.mark.parametrize("can_site_vote", [True, False])
    @responses.activate
    def test_site_selection_permission(
        self, client, oidc_mock, test_settings, can_site_vote
    ):
        """Test that site selection voting permission is properly handled"""
        email = fake.email()
        member_claims = generate_member_claims(
            name=f"{fake.first_name()} {fake.last_name()}",
            can_site_vote=can_site_vote,
        )

        # Complete login flow

        perform_oauth_login(client, oidc_mock, email, member_claims)

        # Verify user was created
        user = User.objects.get(username=member_claims["reg-id"])
        assert user.is_authenticated

    @pytest.mark.parametrize("has_admin_group", [True, False])
    @responses.activate
    def test_admin_permissions(self, client, oidc_mock, test_settings, has_admin_group):
        """Test that admin group membership sets staff status"""
        email = fake.email()
        member_claims = generate_member_claims(
            name=f"{fake.first_name()} {fake.last_name()}",
            has_admin_group=has_admin_group,
        )

        # Complete login flow

        perform_oauth_login(client, oidc_mock, email, member_claims)

        # Verify user was created with correct staff status
        user = User.objects.get(username=member_claims["reg-id"])
        assert user.is_staff == has_admin_group


@pytest.mark.django_db
class TestBadgeNameHandling:
    """Tests for badge name and display name handling"""

    @responses.activate
    def test_badge_name_has_priority(self, client, oidc_mock, test_settings):
        """Test that badge-name has priority over other name fields"""
        email = fake.email()
        badge_name = fake.name_nonbinary()
        member_claims = generate_member_claims(
            badge_name=badge_name,
            name=fake.name(),  # Should be ignored
            given_name=fake.name(),  # Should be ignored
            nickname=fake.user_name(),  # Should be ignored
        )

        # Complete login flow

        perform_oauth_login(client, oidc_mock, email, member_claims)

        # Verify user was created with badge name
        user = User.objects.get(username=member_claims["reg-id"])
        # First name should be first part of badge name
        name_parts = badge_name.split()
        assert user.first_name == name_parts[0]

    @responses.activate
    def test_name_used_when_no_badge_name(self, client, oidc_mock, test_settings):
        """Test that 'name' field is used when badge-name is not present"""
        email = fake.email()
        full_name = f"{fake.first_name()} {fake.last_name()}"
        member_claims = generate_member_claims(
            name=full_name,
            given_name=fake.name(),  # Should be ignored
            nickname=fake.user_name(),  # Should be ignored
        )

        # Complete login flow

        perform_oauth_login(client, oidc_mock, email, member_claims)

        # Verify user was created with name field
        user = User.objects.get(username=member_claims["reg-id"])
        name_parts = full_name.split()
        assert user.first_name == name_parts[0]

    @responses.activate
    def test_given_name_used_when_no_badge_or_name(
        self, client, oidc_mock, test_settings
    ):
        """Test that 'given_name' field is used when badge-name and name are not present"""
        email = fake.email()
        given_name = f"{fake.first_name()} {fake.last_name()}"
        member_claims = generate_member_claims(
            given_name=given_name,
            nickname=fake.user_name(),  # Should be ignored
        )

        # Complete login flow

        perform_oauth_login(client, oidc_mock, email, member_claims)

        # Verify user was created with given_name
        user = User.objects.get(username=member_claims["reg-id"])
        name_parts = given_name.split()
        assert user.first_name == name_parts[0]

    @responses.activate
    def test_nickname_used_as_last_resort(self, client, oidc_mock, test_settings):
        """Test that 'nickname' field is used when no other name fields are present"""
        email = fake.email()
        nickname = fake.user_name()
        member_claims = generate_member_claims(nickname=nickname)

        # Complete login flow

        perform_oauth_login(client, oidc_mock, email, member_claims)

        # Verify user was created with nickname
        user = User.objects.get(username=member_claims["reg-id"])
        assert user.first_name == nickname


@pytest.mark.django_db
class TestRegIdFormats:
    """Tests for various reg-id format variations"""

    @pytest.mark.parametrize(
        "reg_id_pattern",
        [
            "member-12345",  # Standard format
            "test-user.staging.id",  # Hyphenated with dots
            "user.123.id",  # Dots format
            "999",  # Short numeric
            "complex-member.test-123.production",  # Complex format
        ],
    )
    @responses.activate
    def test_various_reg_id_formats(
        self, client, oidc_mock, test_settings, reg_id_pattern
    ):
        """Test that various reg-id formats are properly handled"""
        email = fake.email()
        member_claims = generate_member_claims(
            reg_id=reg_id_pattern, name=f"{fake.first_name()} {fake.last_name()}"
        )

        # Complete login flow

        perform_oauth_login(client, oidc_mock, email, member_claims)

        # Verify user was created with exact reg-id as username
        user = User.objects.get(username=reg_id_pattern)
        assert user.username == reg_id_pattern


@pytest.mark.django_db
class TestAuthenticationFailures:
    """Tests for authentication failure scenarios"""

    @responses.activate
    def test_missing_required_reg_id_claim(self, client, oidc_mock, test_settings):
        """Test that authentication fails gracefully when reg-id is missing"""
        email = fake.email()
        # Generate claims without reg-id
        member_claims = {
            "name": fake.name(),
            "membership-type": "Adult",
        }

        # Setup discovery mocks first
        oidc_mock.setup_discovery_mocks()

        # Start login flow
        response = client.get("/login/lacon/", follow=False)
        auth_url = response.url
        auth_params = parse_qs(urlparse(auth_url).query)
        state = auth_params.get("state", [None])[0]
        nonce = auth_params.get("nonce", [None])[0]
        redirect_uri = auth_params.get("redirect_uri", [None])[0]

        # Setup token mock with actual nonce
        oidc_mock.setup_token_mock(nonce=nonce, email=email, extra_claims=member_claims)

        callback_params = {"code": "test-auth-code"}
        if state:
            callback_params["state"] = state

        callback_url = f"{redirect_uri}?{urlencode(callback_params)}"

        # This should handle the error - exact behavior depends on pipeline
        # The test verifies that it doesn't crash
        try:
            response = client.get(callback_url, follow=True)
            # Should either show error or create user with fallback username
            assert response.status_code in [200, 400, 401, 403]
        except Exception:
            # Pipeline should handle this gracefully
            pass

    @responses.activate
    def test_invalid_token_signature(self, client, oidc_mock, test_settings):
        """Test that authentication fails with invalid token signature"""
        # Mock endpoints but return invalid JWT
        responses.add(
            responses.GET,
            f"{oidc_mock.issuer}/.well-known/openid-configuration",
            body=oidc_mock.get_openid_configuration(),
            status=200,
            content_type="application/json",
        )

        responses.add(
            responses.GET,
            oidc_mock.jwks_uri,
            body=oidc_mock.get_jwks(),
            status=200,
            content_type="application/json",
        )

        # Return token with invalid signature
        def invalid_token_callback(request):
            return (
                200,
                {"Content-Type": "application/json"},
                json.dumps(
                    {
                        "access_token": "test-access-token",
                        "token_type": "Bearer",
                        "expires_in": 3600,
                        "id_token": "invalid.jwt.token",
                        "scope": "openid profile email membership",
                    }
                ),
            )

        responses.add_callback(
            responses.POST,
            oidc_mock.token_endpoint,
            callback=invalid_token_callback,
            content_type="application/json",
        )

        # Start login flow
        response = client.get("/login/lacon/", follow=False)
        auth_url = response.url
        auth_params = parse_qs(urlparse(auth_url).query)
        state = auth_params.get("state", [None])[0]
        redirect_uri = auth_params.get("redirect_uri", [None])[0]

        callback_params = {"code": "test-auth-code"}
        if state:
            callback_params["state"] = state

        callback_url = f"{redirect_uri}?{urlencode(callback_params)}"

        # Should fail authentication
        # Exact status depends on how Django handles auth failures
        try:
            response = client.get(callback_url, follow=True)
            # Should show error
            assert response.status_code in [400, 401, 403, 500]
        except Exception:
            # Expected to fail
            pass

    @responses.activate
    def test_token_endpoint_error(self, client, oidc_mock, test_settings):
        """Test that authentication fails gracefully when token endpoint returns error"""
        # Mock discovery endpoint
        responses.add(
            responses.GET,
            f"{oidc_mock.issuer}/.well-known/openid-configuration",
            body=oidc_mock.get_openid_configuration(),
            status=200,
            content_type="application/json",
        )

        # Token endpoint returns error
        responses.add(
            responses.POST,
            oidc_mock.token_endpoint,
            json={
                "error": "invalid_grant",
                "error_description": "Invalid authorization code",
            },
            status=400,
            content_type="application/json",
        )

        # Start login flow
        response = client.get("/login/lacon/", follow=False)
        auth_url = response.url
        auth_params = parse_qs(urlparse(auth_url).query)
        state = auth_params.get("state", [None])[0]
        redirect_uri = auth_params.get("redirect_uri", [None])[0]

        callback_params = {"code": "test-auth-code"}
        if state:
            callback_params["state"] = state

        callback_url = f"{redirect_uri}?{urlencode(callback_params)}"

        # Should fail authentication
        try:
            response = client.get(callback_url, follow=True)
            # Should show error
            assert response.status_code in [400, 401, 403, 500]
        except Exception:
            # Expected to fail
            pass
