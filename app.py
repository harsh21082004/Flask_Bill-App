from flask import Flask, request, redirect, render_template, session, url_for, flash
import os
import requests
import base64
from urllib.parse import urlencode
from sqlalchemy.orm import Session
from models import Bill, Vendor, VendorAddress, Currency, BillMetaData, BillLineItem, Customer, CustomerAddress, CustomerMetaData
from database import SessionLocal
from datetime import datetime
from sqlalchemy.orm import joinedload

app = Flask(__name__)
app.secret_key = os.urandom(24)  # needed for session

CLIENT_ID = "ABiHWaO5C05yuxL0mv0QL5rzC0z1RDvfoAVB2xMV64G3YgEmfv"
CLIENT_SECRET = "VZD28FlMtQ6K914rMnKAuoA3bd5lSac6M7Ctle65"
REDIRECT_URI = "http://localhost:5000/callback"
REALM_ID = "9341454578080950"

QB_BILL_NEXT_START_POSITION_KEY = 'qb_bill_next_start_position'
LAST_BILL_FETCH_COUNT_KEY = 'last_bill_fetch_count'
QB_CUSTOMER_NEXT_START_POSITION_KEY = 'qb_customer_next_start_position'
LAST_CUSTOMER_FETCH_COUNT_KEY = 'last_customer_fetch_count'

auth_base_url = "https://appcenter.intuit.com/connect/oauth2"
token_url = "https://oauth.platform.intuit.com/oauth2/v1/tokens/bearer"

access_token = None


# --- Bill Routes ---
@app.route("/", methods=["GET", "POST"])
def home():
    if request.method == "POST":
        # This POST is for bill pagination settings
        bill_count = request.form.get("count", 5) # Bill's count
        bill_start = request.form.get("start", 0) # Bill's start
        # Preserve customer pagination if present
        customer_count = request.args.get("customer_count", 5)
        customer_start = request.args.get("customer_start", 0)
        return redirect(url_for("home", count=bill_count, start=bill_start, customer_count=customer_count, customer_start=customer_start))

    # Bill pagination (primary for this route)
    bill_count = int(request.args.get("count", 5))
    bill_start = int(request.args.get("start", 0))

    # Customer pagination (secondary, but respect its parameters if provided)
    customer_count = int(request.args.get("customer_count", 5))
    customer_start = int(request.args.get("customer_start", 0))

    db: Session = SessionLocal()
    try:
        # Load Bill data
        total_bills = db.query(Bill).count()
        bills = db.query(Bill).options(
            joinedload(Bill.vendor),
            joinedload(Bill.currency),
            joinedload(Bill.bill_metadata)
        ).order_by(Bill.txn_date.desc()).offset(bill_start).limit(bill_count).all()
        bill_has_more = (bill_start + bill_count) < total_bills
        bill_has_prev = bill_start > 0
        last_bill_fetch_count = session.get(LAST_BILL_FETCH_COUNT_KEY, 10)

        # Load Customer data
        total_customers = db.query(Customer).count()
        customers = db.query(Customer).options(
            joinedload(Customer.bill_addr),
            joinedload(Customer.customer_metadata_info)
        ).order_by(Customer.display_name).offset(customer_start).limit(customer_count).all()
        customer_has_more = (customer_start + customer_count) < total_customers
        customer_has_prev = customer_start > 0
        last_customer_fetch_count = session.get(LAST_CUSTOMER_FETCH_COUNT_KEY, 10)

        return render_template("index.html", 
                               bills=bills, 
                               count=bill_count, 
                               start=bill_start,
                               has_more=bill_has_more, 
                               has_prev=bill_has_prev,
                               last_fetch_count=last_bill_fetch_count, 
                               next_qb_bill_start_pos=session.get(QB_BILL_NEXT_START_POSITION_KEY),
                               customers=customers, 
                               customer_count=customer_count, 
                               customer_start=customer_start,
                               customer_has_more=customer_has_more, 
                               customer_has_prev=customer_has_prev,
                               last_customer_fetch_count=last_customer_fetch_count,
                               next_qb_customer_start_pos=session.get(QB_CUSTOMER_NEXT_START_POSITION_KEY))
    finally:
        db.close()


@app.route("/initiate-fetch", methods=["POST"])
def initiate_fetch_controller():
    fetch_count = int(request.form.get("fetch_count", 10))
    display_count = int(request.form.get("current_display_count", 5))
    display_start = int(request.form.get("current_display_start", 0))

    session[LAST_BILL_FETCH_COUNT_KEY] = fetch_count
    session[QB_BILL_NEXT_START_POSITION_KEY] = 1 

    global access_token
    if not access_token:
        state_payload = f"bills:{fetch_count}:{1}:{display_count}:{display_start}"
        return redirect_to_authorization(state_payload)
    
    return redirect(url_for("fetch_and_save_worker", 
                            fetch_count=fetch_count, 
                            qb_start_position=1,
                            display_count=display_count,
                            display_start=display_start))


@app.route("/fetch-next-batch", methods=["GET"])
def fetch_next_batch_controller():
    fetch_count = session.get(LAST_BILL_FETCH_COUNT_KEY, 10)
    qb_start_position = session.get(QB_BILL_NEXT_START_POSITION_KEY, 1)
    
    display_count = int(request.args.get("current_display_count", 5))
    display_start = int(request.args.get("current_display_start", 0))

    global access_token
    if not access_token:
        state_payload = f"bills:{fetch_count}:{qb_start_position}:{display_count}:{display_start}"
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

        session[QB_BILL_NEXT_START_POSITION_KEY] = qb_start_position + num_fetched
        session[LAST_BILL_FETCH_COUNT_KEY] = fetch_count 
    finally:
        db.close()
    
    if num_fetched < fetch_count:
        flash(f"Fetched all remaining bills. {num_fetched} bill(s) added.", "info")
        session[QB_BILL_NEXT_START_POSITION_KEY] = -1 # Indicate no more to fetch
    elif num_fetched == 0 and qb_start_position > 1:
        flash("No more bills to fetch from QuickBooks.", "info")
        session[QB_BILL_NEXT_START_POSITION_KEY] = -1 # Indicate no more to fetch

    return redirect(url_for("home", count=display_count, start=display_start, customer_count=request.args.get("customer_count", 5), customer_start=request.args.get("customer_start", 0)))


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
        entity_type = state_parts[0]
        fetch_count = int(state_parts[1])
        qb_start_position = int(state_parts[2])
        display_count = int(state_parts[3])
        display_start = int(state_parts[4])
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
        if entity_type == "bills":
            return redirect(url_for("fetch_and_save_worker",
                                    fetch_count=fetch_count,
                                    qb_start_position=qb_start_position,
                                    display_count=display_count,
                                    display_start=display_start))
        elif entity_type == "customers":
            return redirect(url_for("fetch_and_save_customers_worker",
                                    fetch_count=fetch_count,
                                    qb_start_position=qb_start_position,
                                    display_count=display_count,
                                    display_start=display_start))
        else:
            return "Unknown entity type in state", 400
    
    return f"Failed to get tokens: {response.text}", 400


# --- Customer Routes ---
@app.route("/customers", methods=["GET", "POST"])
def home_customers():
    if request.method == "POST": # For display pagination settings
        # This POST is for customer pagination settings
        customer_count = request.form.get("count", 5) # Customer's count
        customer_start = request.form.get("start", 0) # Customer's start
        # Preserve bill pagination if present
        bill_count = request.args.get("count", 5)
        bill_start = request.args.get("start", 0)
        return redirect(url_for("home_customers", count=bill_count, start=bill_start, customer_count=customer_count, customer_start=customer_start))

    # Customer pagination (primary for this route)
    customer_count = int(request.args.get("customer_count", 5)) # Use customer_count for clarity
    customer_start = int(request.args.get("customer_start", 0)) # Use customer_start

    # Bill pagination (secondary, but respect its parameters if provided)
    bill_count = int(request.args.get("count", 5)) # 'count' and 'start' from URL for bills
    bill_start = int(request.args.get("start", 0))

    db: Session = SessionLocal()
    try:
        # Load Customer data
        total_customers = db.query(Customer).count()
        customers = db.query(Customer).options(
            joinedload(Customer.bill_addr),
            joinedload(Customer.customer_metadata_info)
        ).order_by(Customer.display_name).offset(customer_start).limit(customer_count).all()
        customer_has_more = (customer_start + customer_count) < total_customers
        customer_has_prev = customer_start > 0
        last_customer_fetch_count = session.get(LAST_CUSTOMER_FETCH_COUNT_KEY, 10)

        # Load Bill data
        total_bills = db.query(Bill).count()
        bills = db.query(Bill).options(
            joinedload(Bill.vendor),
            joinedload(Bill.currency),
            joinedload(Bill.bill_metadata)
        ).order_by(Bill.txn_date.desc()).offset(bill_start).limit(bill_count).all()
        bill_has_more = (bill_start + bill_count) < total_bills
        bill_has_prev = bill_start > 0
        last_bill_fetch_count = session.get(LAST_BILL_FETCH_COUNT_KEY, 10)

        return render_template("index.html", 
                               customers=customers, 
                               customer_count=customer_count, 
                               customer_start=customer_start,
                               customer_has_more=customer_has_more, 
                               customer_has_prev=customer_has_prev,
                               last_customer_fetch_count=last_customer_fetch_count,
                               next_qb_customer_start_pos=session.get(QB_CUSTOMER_NEXT_START_POSITION_KEY),
                               bills=bills, 
                               count=bill_count, 
                               start=bill_start, 
                               has_more=bill_has_more, 
                               has_prev=bill_has_prev,
                               last_fetch_count=last_bill_fetch_count,
                               next_qb_bill_start_pos=session.get(QB_BILL_NEXT_START_POSITION_KEY))
    finally:
        db.close()

@app.route("/initiate-fetch-customers", methods=["POST"])
def initiate_fetch_customers_controller():
    fetch_count = int(request.form.get("fetch_customer_count", 10))
    display_count = int(request.form.get("current_customer_display_count", 5))
    display_start = int(request.form.get("current_customer_display_start", 0))

    session[LAST_CUSTOMER_FETCH_COUNT_KEY] = fetch_count
    session[QB_CUSTOMER_NEXT_START_POSITION_KEY] = 1

    global access_token
    if not access_token:
        state_payload = f"customers:{fetch_count}:{1}:{display_count}:{display_start}"
        return redirect_to_authorization(state_payload)

    return redirect(url_for("fetch_and_save_customers_worker",
                            fetch_count=fetch_count,
                            qb_start_position=1,
                            display_count=display_count,
                            display_start=display_start))

@app.route("/fetch-next-batch-customers", methods=["GET"])
def fetch_next_batch_customers_controller():
    fetch_count = session.get(LAST_CUSTOMER_FETCH_COUNT_KEY, 10)
    qb_start_position = session.get(QB_CUSTOMER_NEXT_START_POSITION_KEY, 1)

    display_count = int(request.args.get("current_customer_display_count", 5))
    display_start = int(request.args.get("current_customer_display_start", 0))

    global access_token
    if not access_token:
        state_payload = f"customers:{fetch_count}:{qb_start_position}:{display_count}:{display_start}"
        return redirect_to_authorization(state_payload)

    return redirect(url_for("fetch_and_save_customers_worker",
                            fetch_count=fetch_count,
                            qb_start_position=qb_start_position,
                            display_count=display_count,
                            display_start=display_start))

@app.route("/fetch-and-save-customers-worker")
def fetch_and_save_customers_worker():
    # This function will be similar to fetch_and_save_worker but for Customers
    # It will query 'SELECT * FROM Customer ...'
    # Parse customer data, create/update Customer, CustomerAddress, CustomerMetaData
    # And save to DB.
    global access_token
    if not access_token:
        # Redirect to the customer view, preserving current bill pagination if any
        bill_count = request.args.get("current_display_count", 5) # Assuming this is passed if coming from a bill context
        bill_start = request.args.get("current_display_start", 0)
        return redirect(url_for("home_customers", error="Authentication required.", count=bill_count, start=bill_start))

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
    query = f"SELECT * FROM Customer STARTPOSITION {qb_start_position} MAXRESULTS {fetch_count}"
    response = requests.post(url, headers=headers, data=query)

    if not response.ok:
        return f"Failed to fetch customers: {response.text}", 500

    customers_data = response.json().get("QueryResponse", {}).get("Customer", [])
    num_fetched = len(customers_data)

    db: Session = SessionLocal()
    try:
        for c_data in customers_data:
            qb_customer_id = c_data.get("Id")
            if not qb_customer_id:
                continue

            customer = db.query(Customer).filter(Customer.customer_id == qb_customer_id).first()

            if not customer:
                customer = Customer(customer_id=qb_customer_id)
                db.add(customer)
            
            customer.sync_token = c_data.get("SyncToken")
            customer.domain = c_data.get("domain")
            customer.given_name = c_data.get("GivenName")
            customer.display_name = c_data.get("DisplayName")
            customer.bill_with_parent = c_data.get("BillWithParent", False)
            customer.fully_qualified_name = c_data.get("FullyQualifiedName")
            customer.company_name = c_data.get("CompanyName")
            customer.family_name = c_data.get("FamilyName")
            customer.sparse = c_data.get("sparse", False)
            customer.primary_phone_free_form_number = c_data.get("PrimaryPhone", {}).get("FreeFormNumber")
            customer.primary_email_addr = c_data.get("PrimaryEmailAddr", {}).get("Address")
            customer.active = c_data.get("Active", True)
            customer.job = c_data.get("Job", False)
            customer.balance_with_jobs = float(c_data.get("BalanceWithJobs", 0))
            customer.preferred_delivery_method = c_data.get("PreferredDeliveryMethod")
            customer.taxable = c_data.get("Taxable", False)
            customer.print_on_check_name = c_data.get("PrintOnCheckName")
            customer.balance = float(c_data.get("Balance", 0))

            # Address (BillAddr)
            bill_addr_data = c_data.get("BillAddr")
            if bill_addr_data:
                if not customer.bill_addr:
                    customer.bill_addr = CustomerAddress(qb_address_id=bill_addr_data.get("Id"))
                
                customer.bill_addr.line1 = bill_addr_data.get("Line1")
                customer.bill_addr.city = bill_addr_data.get("City")
                customer.bill_addr.country_sub_division_code = bill_addr_data.get("CountrySubDivisionCode")
                customer.bill_addr.postal_code = bill_addr_data.get("PostalCode")
                customer.bill_addr.lat = bill_addr_data.get("Lat")
                customer.bill_addr.long = bill_addr_data.get("Long")

            # MetaData
            meta_data_json = c_data.get("MetaData")
            if meta_data_json:
                create_time_str = meta_data_json.get("CreateTime")
                last_updated_time_str = meta_data_json.get("LastUpdatedTime")
                parsed_create_time = datetime.fromisoformat(create_time_str.replace("Z", "+00:00")) if create_time_str else None
                parsed_last_updated_time = datetime.fromisoformat(last_updated_time_str.replace("Z", "+00:00")) if last_updated_time_str else None

                if not customer.customer_metadata_info:
                    customer.customer_metadata_info = CustomerMetaData()
                customer.customer_metadata_info.create_time = parsed_create_time
                customer.customer_metadata_info.last_updated_time = parsed_last_updated_time
        
        db.commit()
        session[QB_CUSTOMER_NEXT_START_POSITION_KEY] = qb_start_position + num_fetched
        session[LAST_CUSTOMER_FETCH_COUNT_KEY] = fetch_count
    finally:
        db.close()

    # When redirecting back to home_customers, ensure bill pagination is also considered
    # For simplicity, let's assume the bill pagination was not the primary focus of this fetch action
    # So, we might just redirect to the first page of bills, or try to preserve it if it was in the state.
    # The display_count and display_start from the worker are for the customers.
    # We need to decide what the bill pagination should be.
    if num_fetched < fetch_count:
        flash(f"Fetched all remaining customers. {num_fetched} customer(s) added.", "info")
        session[QB_CUSTOMER_NEXT_START_POSITION_KEY] = -1 # Indicate no more to fetch
    elif num_fetched == 0 and qb_start_position > 1:
        flash("No more customers to fetch from QuickBooks.", "info")
        session[QB_CUSTOMER_NEXT_START_POSITION_KEY] = -1 # Indicate no more to fetch
    return redirect(url_for("home_customers", customer_count=display_count, customer_start=display_start, count=request.args.get("count",5), start=request.args.get("start",0)))



@app.route("/callback_old") 
def callback_old(): # Renamed the function
    global access_token
    auth_code = request.args.get("code")
    state = request.args.get("state")

    if not auth_code:
        return "No auth code received", 400
    if not state:
        return "No state received", 400

    try:
        state_parts = state.split(':')
        entity_type = state_parts[0] # "bills" or "customers"
        fetch_count = int(state_parts[1])
        qb_start_position = int(state_parts[2])
        display_count = int(state_parts[3])
        display_start = int(state_parts[4])
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
        if entity_type == "bills":
            return redirect(url_for("fetch_and_save_worker",
                                    fetch_count=fetch_count,
                                    qb_start_position=qb_start_position,
                                    display_count=display_count,
                                    display_start=display_start))
        elif entity_type == "customers":
             return redirect(url_for("fetch_and_save_customers_worker",
                                    fetch_count=fetch_count,
                                    qb_start_position=qb_start_position,
                                    display_count=display_count,
                                    display_start=display_start))
        # Add more entity types if needed
    
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
