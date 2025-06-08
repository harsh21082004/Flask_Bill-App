from flask import Flask, request, redirect, render_template, session, url_for
import os
import requests
import base64
from urllib.parse import urlencode
from sqlalchemy.orm import Session
from models import Bill, Vendor, VendorAddress, Currency, BillMetaData, BillLineItem
from database import SessionLocal
from datetime import datetime
from sqlalchemy.orm import joinedload

app = Flask(__name__)
app.secret_key = os.urandom(24)  # needed for session

CLIENT_ID = "ABiHWaO5C05yuxL0mv0QL5rzC0z1RDvfoAVB2xMV64G3YgEmfv"
CLIENT_SECRET = "VZD28FlMtQ6K914rMnKAuoA3bd5lSac6M7Ctle65"
REDIRECT_URI = "http://localhost:5000/callback"
REALM_ID = "9341454578080950"

QB_NEXT_START_POSITION_KEY = 'qb_next_start_position'
LAST_FETCH_COUNT_KEY = 'last_fetch_count'

auth_base_url = "https://appcenter.intuit.com/connect/oauth2"
token_url = "https://oauth.platform.intuit.com/oauth2/v1/tokens/bearer"

access_token = None


@app.route("/", methods=["GET", "POST"])
def home():
    if request.method == "POST":
        count = request.form.get("count", 5)
        start = request.form.get("start", 0)
        return redirect(url_for("home", count=count, start=start))

    try:
        count = int(request.args.get("count", 5))
    except (ValueError, TypeError):
        count = 5

    try:
        start = int(request.args.get("start", 0))
    except (ValueError, TypeError):
        start = 0

    db: Session = SessionLocal()
    try:
        total_bills = db.query(Bill).count()
        bills = db.query(Bill).options(
            joinedload(Bill.vendor),
            joinedload(Bill.currency),
            joinedload(Bill.bill_metadata)
        ).order_by(Bill.txn_date.desc()).offset(start).limit(count).all()

        has_more = (start + count) < total_bills
        has_prev = start > 0
        last_fetch_count = session.get(LAST_FETCH_COUNT_KEY, 10)

        return render_template("index.html", bills=bills, count=count, start=start,
                               has_more=has_more, has_prev=has_prev,
                               last_fetch_count=last_fetch_count,
                               next_qb_start_pos=session.get(QB_NEXT_START_POSITION_KEY))
    finally:
        db.close()


@app.route("/initiate-fetch", methods=["POST"])
def initiate_fetch_controller():
    fetch_count = int(request.form.get("fetch_count", 10))
    display_count = int(request.form.get("current_display_count", 5))
    display_start = int(request.form.get("current_display_start", 0))

    session[LAST_FETCH_COUNT_KEY] = fetch_count
    session[QB_NEXT_START_POSITION_KEY] = 1 

    global access_token
    if not access_token:
        state_payload = f"{fetch_count}:{1}:{display_count}:{display_start}"
        return redirect_to_authorization(state_payload)
    
    return redirect(url_for("fetch_and_save_worker", 
                            fetch_count=fetch_count, 
                            qb_start_position=1,
                            display_count=display_count,
                            display_start=display_start))


@app.route("/fetch-next-batch", methods=["GET"])
def fetch_next_batch_controller():
    fetch_count = session.get(LAST_FETCH_COUNT_KEY, 10)
    qb_start_position = session.get(QB_NEXT_START_POSITION_KEY, 1)
    
    display_count = int(request.args.get("current_display_count", 5))
    display_start = int(request.args.get("current_display_start", 0))

    global access_token
    if not access_token:
        state_payload = f"{fetch_count}:{qb_start_position}:{display_count}:{display_start}"
        return redirect_to_authorization(state_payload)

    return redirect(url_for("fetch_and_save_worker", 
                            fetch_count=fetch_count, 
                            qb_start_position=qb_start_position,
                            display_count=display_count,
                            display_start=display_start))


@app.route("/fetch-and-save-worker")
def fetch_and_save_worker():
    global access_token
    if not access_token:
        return redirect(url_for("home", error="Authentication required."))

    fetch_count = int(request.args.get("fetch_count"))
    qb_start_position = int(request.args.get("qb_start_position"))
    display_count = int(request.args.get("display_count"))
    display_start = int(request.args.get("display_start"))
    
    url = f"https://sandbox-quickbooks.api.intuit.com/v3/company/{REALM_ID}/query"
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Accept": "application/json",
        "Content-Type": "application/text"
    }
    query = f"SELECT * FROM Bill STARTPOSITION {qb_start_position} MAXRESULTS {fetch_count}"
    response = requests.post(url, headers=headers, data=query)

    if not response.ok:
        return f"Failed to fetch bills: {response.text}", 500

    bills_data = response.json().get("QueryResponse", {}).get("Bill", [])
    num_fetched = len(bills_data)

    db: Session = SessionLocal()
    try:
        for b in bills_data:
            qb_bill_id_str = b.get("Id")
            if not qb_bill_id_str:
                continue

            vendor_ref = b.get("VendorRef", {})
            vendor_name = vendor_ref.get("name")
            vendor_qb_id = vendor_ref.get("value")
            vendor = db.query(Vendor).filter(Vendor.vendor_ref == vendor_qb_id).first()
            if not vendor and vendor_name and vendor_qb_id:
                vendor = Vendor(name=vendor_name, vendor_ref=vendor_qb_id)
                db.add(vendor)
                db.flush() 

            if vendor: 
                vendor_addr_data = b.get("VendorAddr")
                if vendor_addr_data:
                    address = db.query(VendorAddress).filter(VendorAddress.vendor_id == vendor.id).first()
                    if not address:
                        address = VendorAddress(vendor_id=vendor.id)
                        db.add(address)
                    address.line1 = vendor_addr_data.get("Line1")
                    address.city = vendor_addr_data.get("City")
                    address.country_sub_division_code = vendor_addr_data.get("CountrySubDivisionCode")
                    address.postal_code = vendor_addr_data.get("PostalCode")

            currency = None
            currency_data = b.get("CurrencyRef", {})
            currency_code = currency_data.get("value")
            if currency_code:
                currency = db.query(Currency).filter(Currency.value == currency_code).first()
                if not currency:
                    currency = Currency(value=currency_code, name=currency_data.get("name"))
                    db.add(currency)
                    db.flush() 

            bill = db.query(Bill).filter(Bill.bill_id == qb_bill_id_str).first()

            txn_date_str = b.get("TxnDate")
            due_date_str = b.get("DueDate")
            total_amt = float(b.get("TotalAmt", 0))
            balance = float(b.get("Balance", 0))
            
            parsed_txn_date = datetime.strptime(txn_date_str, "%Y-%m-%d") if txn_date_str else None
            parsed_due_date = datetime.strptime(due_date_str, "%Y-%m-%d") if due_date_str else None

            metadata_data = b.get("MetaData", {})
            create_time_str = metadata_data.get("CreateTime")
            last_updated_time_str = metadata_data.get("LastUpdatedTime")
            parsed_create_time = datetime.fromisoformat(create_time_str.replace("Z", "+00:00")) if create_time_str else None
            parsed_last_updated_time = datetime.fromisoformat(last_updated_time_str.replace("Z", "+00:00")) if last_updated_time_str else None

            if not bill:
                bill = Bill(
                    bill_id=qb_bill_id_str,
                    txn_date=parsed_txn_date,
                    due_date=parsed_due_date,
                    total_amt=total_amt,
                    balance=balance,
                    vendor_id=vendor.id if vendor else None,
                    currency_id=currency.id if currency else None,
                )
                db.add(bill)
                bill_meta = BillMetaData(
                    create_time=parsed_create_time,
                    last_updated_time=parsed_last_updated_time
                )
                bill.bill_metadata = bill_meta
            else:
                bill.txn_date = parsed_txn_date if parsed_txn_date else bill.txn_date
                bill.due_date = parsed_due_date if parsed_due_date else bill.due_date
                bill.total_amt = total_amt
                bill.balance = balance
                bill.vendor_id = vendor.id if vendor else bill.vendor_id
                bill.currency_id = currency.id if currency else bill.currency_id

                if bill.bill_metadata:
                    bill.bill_metadata.create_time = parsed_create_time if parsed_create_time else bill.bill_metadata.create_time
                    bill.bill_metadata.last_updated_time = parsed_last_updated_time if parsed_last_updated_time else bill.bill_metadata.last_updated_time
                elif parsed_create_time or parsed_last_updated_time: 
                    bill_meta = BillMetaData(
                        create_time=parsed_create_time,
                        last_updated_time=parsed_last_updated_time
                    )
                    bill.bill_metadata = bill_meta
        db.commit()

        session[QB_NEXT_START_POSITION_KEY] = qb_start_position + num_fetched
        session[LAST_FETCH_COUNT_KEY] = fetch_count 
    finally:
        db.close()

    return redirect(url_for("home", count=display_count, start=display_start))


@app.route("/callback")
def callback():
    global access_token
    auth_code = request.args.get("code")
    state = request.args.get("state")

    if not auth_code:
        return "No auth code received", 400
    if not state:
        return "No state received", 400

    try:
        state_parts = state.split(':')
        fetch_count = int(state_parts[0])
        qb_start_position = int(state_parts[1])
        display_count = int(state_parts[2])
        display_start = int(state_parts[3])
    except (IndexError, ValueError):
        return "Invalid state format", 400

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
        return redirect(url_for("fetch_and_save_worker",
                                fetch_count=fetch_count,
                                qb_start_position=qb_start_position,
                                display_count=display_count,
                                display_start=display_start))
    
    return f"Failed to get tokens: {response.text}", 400


def redirect_to_authorization(state_payload: str):
    params = {
        "client_id": CLIENT_ID,
        "response_type": "code",
        "scope": "com.intuit.quickbooks.accounting",
        "redirect_uri": REDIRECT_URI,
        "state": state_payload
    }
    return redirect(f"{auth_base_url}?{urlencode(params)}")


if __name__ == "__main__":
    app.run(debug=True, host="localhost", port=5000)
