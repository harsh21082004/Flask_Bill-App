import urllib.parse
import requests



# Constants
AUTH_URL = "https://appcenter.intuit.com/connect/oauth2"
TOKEN_URL = "https://oauth.platform.intuit.com/oauth2/v1/tokens/bearer"

CLIENT_ID = "ABiHWaO5C05yuxL0mv0QL5rzC0z1RDvfoAVB2xMV64G3YgEmfv"
CLIENT_SECRET = "VZD28FlMtQ6K914rMnKAuoA3bd5lSac6M7Ctle65"
REDIRECT_URI = "http://localhost:5000/callback"
AUTH_HEADER = "QUJpSFdhTzVDMDV5dXhMMG12MFFMNXJ6QzB6MVJEdmZvQVZCMnhNVjY0RzNZZ0VtZnY6VlpEMjhGbE10UTZLOTE0ck1uS0F1b0EzYmQ1bFNhYzZNN0N0bGU2NQ=="

def get_authorization_url(state="random_state_string"):
    """Generate the QuickBooks authorization URL."""
    params = {
        "client_id": CLIENT_ID,
        "redirect_uri": REDIRECT_URI,
        "response_type": "code",
        "scope": "com.intuit.quickbooks.accounting com.intuit.quickbooks.payment openid profile email phone address",
        "state": state
    }
    url = f"{AUTH_URL}?{urllib.parse.urlencode(params)}"
    return url

def exchange_code_for_token(auth_code):
    """Exchange the authorization code for an access token and refresh token."""
    headers = {
        'Content-Type': 'application/x-www-form-urlencoded',
        'Accept': 'application/json',
        'Authorization': f'Basic {AUTH_HEADER}'
    }
    payload = {
        'grant_type': 'authorization_code',
        'code': auth_code,
        'redirect_uri': REDIRECT_URI
    }

    response = requests.post(TOKEN_URL, headers=headers, data=payload)
    if response.status_code == 200:
        token_data = response.json()
        print("Token Data:", token_data)
        return token_data  # Contains access_token, refresh_token, etc.
    else:
        raise Exception(f"Failed to exchange code: {response.text}")

def refresh_access_token(refresh_token):
    """Use the refresh token to get a new access token."""
    headers = {
        'Content-Type': 'application/x-www-form-urlencoded',
        'Accept': 'application/json',
        'Authorization': f'Basic {AUTH_HEADER}'
    }
    payload = {
        'grant_type': 'refresh_token',
        'refresh_token': refresh_token
    }

    response = requests.post(TOKEN_URL, headers=headers, data=payload)
    if response.status_code == 200:
        token_data = response.json()
        print("New Token Data:", token_data)
        return token_data  # Contains new access_token, refresh_token, etc.
    else:
        raise Exception(f"Failed to refresh token: {response.text}")