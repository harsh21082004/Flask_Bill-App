from sqlalchemy import Column, Integer, String, Float, DateTime, ForeignKey, Boolean
from sqlalchemy.orm import relationship, backref
from database import Base


class Vendor(Base):
    __tablename__ = "vendors"
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(255), unique=True)
    vendor_ref = Column(String(50), unique=True)

    address = relationship("VendorAddress", uselist=False, back_populates="vendor")
    bills = relationship("Bill", back_populates="vendor")


class VendorAddress(Base):
    __tablename__ = "vendor_addresses"
    id = Column(Integer, primary_key=True, index=True)
    vendor_id = Column(Integer, ForeignKey('vendors.id'))
    line1 = Column(String(255))
    city = Column(String(100))
    country_sub_division_code = Column(String(10))
    postal_code = Column(String(20))
    lat = Column(String(50))
    lon = Column(String(50))

    vendor = relationship("Vendor", back_populates="address")


class Currency(Base):
    __tablename__ = "currencies"
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(50))
    value = Column(String(10))

    bills = relationship("Bill", back_populates="currency")


class BillMetaData(Base):
    __tablename__ = "bill_metadata"
    id = Column(Integer, primary_key=True, index=True)
    bill_id = Column(Integer, ForeignKey('bills.id'))
    create_time = Column(DateTime)
    last_updated_time = Column(DateTime)
    last_modified_by = Column(String(100))

    bill = relationship("Bill", back_populates="bill_metadata")


class Bill(Base):
    __tablename__ = "bills"
    id = Column(Integer, primary_key=True, index=True)
    bill_id = Column(String(20), unique=True)
    txn_date = Column(DateTime)
    due_date = Column(DateTime)
    total_amt = Column(Float)
    balance = Column(Float)

    vendor_id = Column(Integer, ForeignKey('vendors.id'))
    currency_id = Column(Integer, ForeignKey('currencies.id'))

    vendor = relationship("Vendor", back_populates="bills")
    currency = relationship("Currency", back_populates="bills")
    bill_metadata = relationship("BillMetaData", uselist=False, back_populates="bill")
    line_items = relationship("BillLineItem", back_populates="bill")


class BillLineItem(Base):
    __tablename__ = "bill_line_items"
    id = Column(Integer, primary_key=True, index=True)
    bill_id = Column(Integer, ForeignKey('bills.id'))

    line_num = Column(Integer)
    description = Column(String(255))
    amount = Column(Float)

    item_name = Column(String(100))
    item_ref = Column(String(50))
    qty = Column(Integer)
    unit_price = Column(Float)
    billable_status = Column(String(50))
    tax_code = Column(String(10))

    bill = relationship("Bill", back_populates="line_items")


class CustomerAddress(Base):
    __tablename__ = "customer_addresses"
    id = Column(Integer, primary_key=True, index=True)
    customer_id = Column(Integer, ForeignKey('customers.id'))
    qb_address_id = Column(String(50)) # From BillAddr.Id or ShipAddr.Id
    line1 = Column(String(255))
    city = Column(String(100))
    country_sub_division_code = Column(String(10))
    postal_code = Column(String(20))
    lat = Column(String(50))
    lon = Column(String(50))

    customer = relationship("Customer", back_populates="bill_addr") # Assuming BillAddr for now


class CustomerMetaData(Base):
    __tablename__ = "customer_metadata"
    id = Column(Integer, primary_key=True, index=True)
    customer_id_fk = Column(Integer, ForeignKey('customers.id')) # Renamed to avoid conflict
    create_time = Column(DateTime)
    last_updated_time = Column(DateTime)

    customer = relationship("Customer", back_populates="customer_metadata_info")


class Customer(Base):
    __tablename__ = "customers"
    id = Column(Integer, primary_key=True, index=True) # DB primary key
    customer_id = Column(String(50), unique=True, index=True) # QuickBooks Customer ID
    sync_token = Column(String(10))
    domain = Column(String(50))
    given_name = Column(String(100))
    display_name = Column(String(255), unique=True, index=True)
    bill_with_parent = Column(Boolean, default=False)
    fully_qualified_name = Column(String(255))
    company_name = Column(String(255))
    family_name = Column(String(100))
    sparse = Column(Boolean, default=False)
    primary_phone_free_form_number = Column(String(50))
    primary_email_addr = Column(String(255))
    active = Column(Boolean, default=True)
    job = Column(Boolean, default=False)
    balance_with_jobs = Column(Float)
    preferred_delivery_method = Column(String(50))
    taxable = Column(Boolean, default=False)
    print_on_check_name = Column(String(255))
    balance = Column(Float)

    bill_addr = relationship("CustomerAddress", uselist=False, back_populates="customer", cascade="all, delete-orphan")
    customer_metadata_info = relationship("CustomerMetaData", uselist=False, back_populates="customer", cascade="all, delete-orphan")
