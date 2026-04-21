# REV'IT EDI Specification

## Connection
- **Protocol:** SFTP
- **Requirement:** Static IP for whitelist (EC2 at ftp.ridefivenine.com)
- **File format:** Semicolon-delimited CSV

## Order File Format

### ORDHDR (Header Row)
| # | Field | Required | Format | Description |
|---|-------|----------|--------|-------------|
| 1 | Record ID | M | "ORDHDR" | Always "ORDHDR" |
| 2 | Document number | M | AN20 | Our PO number |
| 3 | Document date | M | YYYYMMDD | Order date |
| 4 | Delivery date | M | YYYYMMDD | Requested delivery date |
| 5 | Your Reference | M | AN30 | Our reference |
| 6 | Sell-to Customer nr | M | AN20 | REV'IT customer number |
| 7 | Sell to Contact | O | AN50 | Contact name |
| 8-16 | Ship-to fields | O | Various | Code, Name1, Name2, Addr1, Addr2, City, Postal, Country, State |
| 17 | Shipping Agent | O | AN10 | Carrier |
| 18 | Ordertype | M | AN3 | 2=Dropship |
| 19 | Bill-to Customer nr | O | AN20 | If different from Sell-to |
| 20 | Currency Code | O | AN3 | ISO currency |
| 21 | Remark | O | AN250 | Order notes |
| 22 | Ship-to Email | O | AN80 | Consumer email |
| 23 | Ship-to Phone | O | AN30 | Consumer phone |
| 24 | Shipping Agent Service Code | O | AN10 | Carrier service code |

### ORDLIN (Line Item Rows)
| # | Field | Required | Format | Description |
|---|-------|----------|--------|-------------|
| 1 | Record ID | M | "ORDLIN" | Always "ORDLIN" |
| 2 | Line nr | M | N6 | Starting with 1 |
| 3 | EAN/Item nr | M | AN13 | 13-digit EAN barcode |
| 4 | Description 1 | O | AN35 | Item description |
| 5 | Description 2 | O | AN35 | Variant description |
| 6 | Order Quantity | M | N15 | Quantity |
| 7 | Quantity unit per measure | O | AN3 | Unit |
| 8 | Net unit price | O | N18 | Price |
| 9 | Item no. NAV | O | AN20 | REV'IT article code (from MPN) |
| 10 | Variant Code | O | AN10 | Color + Size |
| 11 | Colour Code | O | AN10 | Color code |
| 12 | Size Code | O | AN10 | Size code |

### ORDSUM (Summary Row)
| # | Field | Required | Format | Description |
|---|-------|----------|--------|-------------|
| 1 | Record ID | M | "ORDSUM" | Always "ORDSUM" |
| 2 | Number of ORDLIN | M | N15 | Line count |
| 3 | Sum Order Quantity | M | N15 | Total quantity |

## Example
```
ORDHDR;SA-REV-20260331-001;20260331;20260331;SA-REV-20260331-001;C11192;;SHIPTO;John Smith;;123 Main St;;Anytown;12345;US;NY;;;2;;USD;;;;
ORDLIN;1;8700001169998;;;1;;;;FAR039;0410-L;0410;L
ORDLIN;2;8700001169981;;;2;;;;FAR039;0410-M;0410;M
ORDSUM;2;3
```

## Tracking (Invoice CSV)
REV'IT sends daily email with semicolon-delimited CSV containing:
- Document No, PO/Customer Order No, Shipment Date, Item No, Description, Variant, Quantity, Tracking No, Box ID, SKU

## Stock File
Available via SFTP, updated 5x/day (06:00, 10:00, 14:00, 18:00, 22:00 CET):
- EAN, SKUCode, LifecycleStatus, Stock Status1 (J/N), Stock Status2 (0/1), Stock Status3 (count/30+), ETA

## Rithum Product Mapping (Confirmed via API)
- SKU format: `REV-{article_code}` (e.g., `REV-FAR039-0410-L`)
- EAN: Stored in product `EAN` field
- MPN: Contains REV'IT article code (e.g., `FAR039-0410-L`)
- DC Code: `REV` (Name: `REV'IT!`)
- Product count: 14,504 non-parent products
