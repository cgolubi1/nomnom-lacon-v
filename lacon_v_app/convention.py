from datetime import datetime, timezone

from nomnom.convention import (
    ConventionConfiguration,
    ConventionTheme,
)


class LaconTheme(ConventionTheme):
    """Custom theme for LAcon V that excludes advisory vote styles."""

    @property
    def functional_stylesheets(self) -> list[str]:
        # Override to exclude advise.css since advisory votes are disabled
        # Add any other functional stylesheets here if needed in the future
        return []


theme = LaconTheme(
    stylesheets="css/lacon-v.css",
    font_urls=[
        "https://fonts.googleapis.com/css2?family=Poppins&family=Nunito%20Sans&display=swap",
    ],
)

convention = ConventionConfiguration(
    name="LAcon V",
    subtitle="The New Frontier",
    slug="lacon-v",
    site_url="https://www.lacon.org",
    nomination_eligibility_cutoff=datetime(2024, 2, 1, 0, 0, 0, tzinfo=timezone.utc),
    hugo_help_email="hugo-help@lacon.org",
    hugo_admin_email="hugo-admin@lacon.org",
    hugo_packet_backend="digitalocean",
    registration_email="registration@lacon.org",
    logo="images/logo-menu-small-final2.png",
    logo_alt_text="LAcon V logo",
    urls_app_name="lacon_v_app",
)
