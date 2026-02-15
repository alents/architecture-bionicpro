import os
from dotenv import load_dotenv

load_dotenv()

KEYCLOAK_INTERNAL_URL = os.getenv("KEYCLOAK_INTERNAL_URL")
KEYCLOAK_EXTERNAL_URL = os.getenv("KEYCLOAK_EXTERNAL_URL")
KEYCLOAK_REALM = os.getenv("KEYCLOAK_REALM")
CLIENT_ID = os.getenv("CLIENT_ID")
CLIENT_SECRET = os.getenv("CLIENT_SECRET")
FRONTEND_URL = os.getenv("FRONTEND_URL", "http://localhost:3000")
ENCRYPTION_KEY = os.getenv("ENCRYPTION_KEY")

# Формируем URLs Keycloak
KEYCLOAK_AUTH_URL = f"{KEYCLOAK_EXTERNAL_URL}/realms/{KEYCLOAK_REALM}/protocol/openid-connect/auth"
KEYCLOAK_TOKEN_URL = f"{KEYCLOAK_INTERNAL_URL}/realms/{KEYCLOAK_REALM}/protocol/openid-connect/token"

CALLBACK_URL = os.getenv("CALLBACK_URL", "http://localhost:3001/auth/callback")

SESSION_MAX_AGE = 1800  # 30 минут — больше чем access_token (2 мин)

DATABASE_URL = os.getenv("DATABASE_URL")

REPORTS_SERVICE_URL = os.getenv("REPORTS_SERVICE_URL", "http://reports-api:8080")



