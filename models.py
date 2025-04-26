from sqlalchemy import Column, Integer, String, Float, DateTime, JSON
from database import Base

class Bill(Base):
    __tablename__ = "bills"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    bill_id = Column(String(20), unique=True, index=True)
    sync_token = Column(String(10))
    domain = Column(String(10))
    ap_account_name = Column(String(255))
    ap_account_value = Column(String(50))
    vendor_name = Column(String(255))
    vendor_id = Column(String(50))
    txn_date = Column(DateTime)
    due_date = Column(DateTime)
    total_amt = Column(Float)
    balance = Column(Float)
    currency_name = Column(String(50))
    currency_value = Column(String(10))
    linked_txn = Column(JSON) 
    sales_term_ref = Column(String(50))
    line_items = Column(JSON)
    meta_create_time = Column(String(50))
    meta_last_updated_time = Column(String(50))
