from flask import Flask, request, jsonify
import requests
from models import Bill
from database import SessionLocal, engine, Base
from datetime import datetime
import json  # Needed to save line_items as JSON

app = Flask(__name__)

# Create tables if not exist
Base.metadata.create_all(bind=engine)

ACCESS_TOKEN = "eyJhbGciOiJkaXIiLCJlbmMiOiJBMTI4Q0JDLUhTMjU2IiwieC5vcmciOiJIMCJ9..NJa1Ti57t86mgF4E0lvfcA.97ibSbiN3RE_XSJJ3EDQsJDRsxsIt1tdYdUp5bM0dxvWXXzY1i44VO6-ADP8dUiYbvSxYuGNiS6KiWNgXmoYQVDNnPvzIzbPpzqYPUzeye0xb5hAoqpaE3-G8eTWyeDCh1Z9UJOMwKqDB29uVtBevBkfzuj_7PTgwlzDoANCZUG0rG4pqEkj_4rYM0QTbIYxpDaKgDx8We1V91z0rMrJU-FAPq7Y-hBN803bSjOeqbQEguISZJkHKX_kdOI8Ria_lV2xH6RfY3Ck3pcHQV9OPVlI4vB5r-effu2FD-u-2I4_49wUgyLJar5dFKY3ujg8VNJso3yjAgbrHxeORCcFcu52s5O-2hsuTNhi-iDVheLurid1PtEN90aLZ6Yn5N7-F1DVPG-RyJmI6qMvQHhJB7SabEhmLSYOpr9Ie0dr0E4BcBCstrzgCTbEUMww0yUqDU8MZ2J-pgA3p5PY5u7hPfS_izCwSrw2a_am0d9pU_A.gF2cwKpX010bk5efdieQ1Q"
REALM_ID = "9341454578080950"

@app.route('/fetch-bills')
def fetch_bills():
    url = f"https://sandbox-quickbooks.api.intuit.com/v3/company/{REALM_ID}/query"
    query = "select * from Bill"
    headers = {
        "Authorization": f"Bearer {ACCESS_TOKEN}",
        "Accept": "application/json",
        "Content-Type": "application/text"
    }

    response = requests.post(url, headers=headers, data=query)

    if response.status_code == 200:
        data = response.json()
        print("Fetched Data:", json.dumps(data, indent=2))  # Pretty print JSON
        
        bills_data = data.get('QueryResponse', {}).get('Bill', [])
        db = SessionLocal()

        for bill in bills_data:
            existing_bill = db.query(Bill).filter(Bill.bill_id == bill['Id']).first()
            if existing_bill:
                continue

            new_bill = Bill(
                bill_id = bill['Id'],
                sync_token = bill.get('SyncToken'),
                domain = bill.get('domain'),
                ap_account_name = bill.get('APAccountRef', {}).get('name'),
                ap_account_value = bill.get('APAccountRef', {}).get('value'),
                vendor_name = bill.get('VendorRef', {}).get('name'),
                vendor_id = bill.get('VendorRef', {}).get('value'),
                txn_date = datetime.strptime(bill['TxnDate'], '%Y-%m-%d') if 'TxnDate' in bill else None,
                due_date = datetime.strptime(bill['DueDate'], '%Y-%m-%d') if 'DueDate' in bill else None,
                total_amt = bill.get('TotalAmt'),
                balance = bill.get('Balance', 0),
                currency_name = bill.get('CurrencyRef', {}).get('name'),
                currency_value = bill.get('CurrencyRef', {}).get('value'),
                linked_txn = bill.get('LinkedTxn'),
                sales_term_ref = bill.get('SalesTermRef', {}).get('value') if bill.get('SalesTermRef') else None,
                line_items = bill.get('Line'),
                meta_create_time = bill.get('MetaData', {}).get('CreateTime'),
                meta_last_updated_time = bill.get('MetaData', {}).get('LastUpdatedTime')
            )

            db.add(new_bill)
        
        db.commit()
        db.close()
        return "Bills fetched and stored successfully ✅"
    else:
        print(f"Error response: {response.text}")
        return f"Error fetching bills: {response.text}", 400

@app.route('/')
def home():
    return "Hello Harsh! Flask app is running 🚀"

if __name__ == "__main__":
    app.run(debug=True)
