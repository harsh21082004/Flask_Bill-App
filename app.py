from flask import Flask, request, redirect, jsonify
import requests
import base64
from urllib.parse import urlencode
from datetime import datetime

from models import Bill, Vendor, Currency, VendorAddress, BillMetaData, BillLineItem
from database import SessionLocal, engine

app = Flask(__name__)

CLIENT_ID = "ABiHWaO5C05yuxL0mv0QL5rzC0z1RDvfoAVB2xMV64G3YgEmfv"
CLIENT_SECRET = "VZD28FlMtQ6K914rMnKAuoA3bd5lSac6M7Ctle65"
REDIRECT_URI = "http://localhost:5000/callback"
REALM_ID = "9341454578080950"

auth_base_url = "https://appcenter.intuit.com/connect/oauth2"
token_url = "https://oauth.platform.intuit.com/oauth2/v1/tokens/bearer"

access_token = None

@app.route("/")
def home():
    return "🚀 QuickBooks OAuth Demo"

@app.route("/fetch-bills")
def fetch_bills():
    global access_token
    count = int(request.args.get("count", 0))

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

    bills_data = response.json().get("QueryResponse", {}).get("Bill", [])

    if count > len(bills_data):
        return jsonify({"error": "Requested number exceeds available data."}), 400

    db = SessionLocal()
    try:
        for item in bills_data[:count]:
            if db.query(Bill).filter_by(bill_id=item.get("Id")).first():
                continue

            vendor_ref = item.get("VendorRef", {})
            vendor = db.query(Vendor).filter_by(vendor_ref=vendor_ref.get("value")).first()
            if not vendor and vendor_ref.get("value"):
                vendor = Vendor(name=vendor_ref.get("name"), vendor_ref=vendor_ref.get("value"))
                db.add(vendor)
                db.flush()

            addr = item.get("VendorAddr")
            if addr and vendor:
                if not db.query(VendorAddress).filter_by(vendor_id=vendor.id).first():
                    vendor_address = VendorAddress(
                        vendor_id=vendor.id,
                        line1=addr.get("Line1"),
                        city=addr.get("City"),
                        country_sub_division_code=addr.get("CountrySubDivisionCode"),
                        postal_code=addr.get("PostalCode"),
                        lat=addr.get("Lat"),
                        long=addr.get("Long")
                    )
                    db.add(vendor_address)

            currency_ref = item.get("CurrencyRef", {})
            currency = db.query(Currency).filter_by(value=currency_ref.get("value")).first()
            if not currency and currency_ref.get("value"):
                currency = Currency(name=currency_ref.get("name"), value=currency_ref.get("value"))
                db.add(currency)
                db.flush()

            bill = Bill(
                bill_id=item.get("Id"),
                txn_date=datetime.fromisoformat(item.get("TxnDate")) if item.get("TxnDate") else None,
                due_date=datetime.fromisoformat(item.get("DueDate")) if item.get("DueDate") else None,
                total_amt=item.get("TotalAmt"),
                balance=item.get("Balance"),
                vendor_id=vendor.id if vendor else None,
                currency_id=currency.id if currency else None
            )
            db.add(bill)
            db.flush()

            meta = item.get("MetaData", {})
            if meta:
                meta_record = BillMetaData(
                    bill_id=bill.id,
                    create_time=datetime.fromisoformat(meta.get("CreateTime")),
                    last_updated_time=datetime.fromisoformat(meta.get("LastUpdatedTime")),
                    last_modified_by=meta.get("LastModifiedByRef", {}).get("value")
                )
                db.add(meta_record)

            for line in item.get("Line", []):
                detail = line.get("ItemBasedExpenseLineDetail", {})
                line_item = BillLineItem(
                    bill_id=bill.id,
                    line_num=line.get("LineNum"),
                    description=line.get("Description"),
                    amount=line.get("Amount"),
                    item_name=detail.get("ItemRef", {}).get("name"),
                    item_ref=detail.get("ItemRef", {}).get("value"),
                    qty=detail.get("Qty"),
                    unit_price=detail.get("UnitPrice"),
                    billable_status=detail.get("BillableStatus"),
                    tax_code=detail.get("TaxCodeRef", {}).get("value")
                )
                db.add(line_item)

        db.commit()
        return jsonify({"message": f"{count} bills fetched and stored."})
    except Exception as e:
        db.rollback()
        return jsonify({"error": str(e)}), 500
    finally:
        db.close()

@app.route("/callback")
def callback():
    global access_token
    auth_code = request.args.get("code")
    state = request.args.get("state", "0")

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
        return redirect(f"/fetch-bills?count={state}")
    return f"Failed to get tokens: {response.text}", 400

def redirect_to_authorization():
    count = request.args.get("count", "0")
    query_params = urlencode({
        "client_id": CLIENT_ID,
        "redirect_uri": REDIRECT_URI,
        "response_type": "code",
        "scope": "com.intuit.quickbooks.accounting openid profile email phone address",
        "state": count
    })
    return redirect(f"{auth_base_url}?{query_params}")

if __name__ == "__main__":
    app.run(debug=True, host="localhost", port=5000)
