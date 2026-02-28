import nomnom.apps


class LaconVAdminConfig(nomnom.apps.NomnomAdminConfig):
    default_site = "lacon_v_app.admin.LaconVAdminSite"
