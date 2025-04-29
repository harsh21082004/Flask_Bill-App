from flask import Flask, request, redirect, jsonify
import requests
import base64
from urllib.parse import urlencode
from models import Bill
from database import SessionLocal, engine, Base
from datetime import datetime

app = Flask(__name__)
Base.metadata.create_all(bind=engine)

# Replace with your actual credentials
CLIENT_ID = "ABiHWaO5C05yuxL0mv0QL5rzC0z1RDvfoAVB2xMV64G3YgEmfv"
CLIENT_SECRET = "VZD28FlMtQ6K914rMnKAuoA3bd5lSac6M7Ctle65"
REDIRECT_URI = "http://localhost:5000/callback"  # Update to match your actual callback
REALM_ID = "9341454578080950"

auth_base_url = "https://appcenter.intuit.com/connect/oauth2"
token_url = "https://oauth.platform.intuit.com/oauth2/v1/tokens/bearer"

access_token = None  # Stored in memory (for demo)

@app.route("/")
def home():
    return "🚀 QuickBooks OAuth Demo"

@app.route("/fetch-bills")
def fetch_bills():
    global access_token

    if not access_token:
        return redirect_to_authorization()

    url = f"https://sandbox-quickbooks.api.intuit.com/v3/company/{REALM_ID}/query"
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Accept": "application/json",
        "Content-Type": "application/text"
    }
    query = "SELECT * FROM Bill"

    response = requests.post(url, headers=headers, data=query)
    if response.status_code != 200:
        return f"❌ Error: {response.text}", response.status_code

    data = response.json()
    bills = data.get("QueryResponse", {}).get("Bill", [])
    
    db = SessionLocal()
    for item in bills:
        bill = Bill(
            bill_id=item.get("Id"),
            sync_token=item.get("SyncToken"),
            domain=item.get("domain"),
            ap_account_name=item.get("APAccountRef", {}).get("name"),
            ap_account_value=item.get("APAccountRef", {}).get("value"),
            vendor_name=item.get("VendorRef", {}).get("name"),
            vendor_id=item.get("VendorRef", {}).get("value"),
            txn_date=datetime.fromisoformat(item.get("TxnDate")) if item.get("TxnDate") else None,
            due_date=datetime.fromisoformat(item.get("DueDate")) if item.get("DueDate") else None,
            total_amt=item.get("TotalAmt"),
            balance=item.get("Balance"),
            currency_name=item.get("CurrencyRef", {}).get("name"),
            currency_value=item.get("CurrencyRef", {}).get("value"),
            linked_txn=item.get("LinkedTxn"),
            sales_term_ref=item.get("SalesTermRef", {}).get("value") if item.get("SalesTermRef") else None,
            line_items=item.get("Line"),
            meta_create_time=item.get("MetaData", {}).get("CreateTime"),
            meta_last_updated_time=item.get("MetaData", {}).get("LastUpdatedTime")
        )
        # Avoid duplicate insertions (e.g., using bill_id)
        existing = db.query(Bill).filter_by(bill_id=bill.bill_id).first()
        if not existing:
            db.add(bill)

    db.commit()
    db.close()

    return jsonify({"message": f"{len(bills)} bills fetched and stored successfully."})


@app.route("/callback")
def callback():
    global access_token

    auth_code = request.args.get("code")
    if not auth_code:
        return "No auth code received", 400

    basic_auth = base64.b64encode(f"{CLIENT_ID}:{CLIENT_SECRET}".encode()).decode()

    headers = {
        "Authorization": f"Basic {basic_auth}",
        "Accept": "application/json",
        "Content-Type": "application/x-www-form-urlencoded"
    }
    data = {
        "grant_type": "authorization_code",
        "code": auth_code,
        "redirect_uri": REDIRECT_URI
    }

    response = requests.post(token_url, headers=headers, data=urlencode(data))
    if response.status_code == 200:
        tokens = response.json()
        access_token = tokens["access_token"]
        return redirect("/fetch-bills")
    return f"Failed to get tokens: {response.text}", 400

def redirect_to_authorization():
    query_params = urlencode({
        "client_id": CLIENT_ID,
        "redirect_uri": REDIRECT_URI,
        "response_type": "code",
        "scope": "com.intuit.quickbooks.accounting openid profile email phone address",
        "state": "testState"
    })
    return redirect(f"{auth_base_url}?{query_params}")

if __name__ == "__main__":
    app.run(debug=True)
