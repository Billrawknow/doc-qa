"""
Builds samples/supply_agreement.pdf: a fictional supply agreement between a
building-materials distributor and a hardware shop, with a long price schedule.
It is long enough (12+ pages) that doc_qa.py has to chunk and retrieve.

    pip install reportlab
    python make_sample_pdf.py
"""

import random
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

OUT = Path(__file__).resolve().parent / "samples" / "supply_agreement.pdf"

CLAUSES = [
    ("1. Parties", [
        "This Supply Agreement (the \"Agreement\") is made on 3 March 2026 between <b>Rift Valley Building "
        "Supplies Ltd</b>, a company registered in Kenya (registration number PVT-RV2019X44, KRA PIN "
        "P051234567Z) of Industrial Area, Nakuru (the \"Supplier\"), and <b>Mlimani Hardware &amp; Building "
        "Supplies</b>, a business registered in Kenya (KRA PIN A009876543B) of Temple Road, Kericho "
        "(the \"Buyer\").",
        "The Supplier is represented by Mr. Peter Kamau, Sales Director. The Buyer is represented by "
        "Mrs. Grace Chepkoech, Proprietor.",
    ]),
    ("2. Term", [
        "This Agreement starts on 1 April 2026 and runs for twelve (12) months until 31 March 2027. "
        "It renews automatically for further periods of twelve months unless either party gives written "
        "notice of non-renewal at least sixty (60) days before the end of the current term.",
    ]),
    ("3. Products and prices", [
        "The Supplier will supply cement, steel, roofing, plumbing and other building materials as listed "
        "in Schedule A (Price Schedule). Prices in Schedule A are in Kenya Shillings, include VAT at 16%, "
        "and are fixed for the first three (3) months of the term.",
        "After the first three months, the Supplier may change prices by giving the Buyer at least fourteen "
        "(14) days' written notice. Price increases on cement may not exceed eight percent (8%) in any "
        "single quarter unless the manufacturer's ex-factory price rises by more than that amount, in which "
        "case the Supplier must provide the manufacturer's price notice as evidence.",
    ]),
    ("4. Minimum order and volume discount", [
        "Each order must be worth at least KES 50,000. Orders below this amount will attract a handling "
        "fee of KES 2,500.",
        "If the Buyer's total purchases in a calendar quarter exceed KES 1,500,000, the Supplier will give "
        "a volume rebate of 2.5% of that quarter's purchases, credited against the next invoice. Purchases "
        "above KES 3,000,000 in a quarter earn a rebate of 4%.",
    ]),
    ("5. Ordering", [
        "The Buyer will place orders by email to orders@rvbuildingsupplies.example.com or by WhatsApp to "
        "0711 222 333, stating the product codes from Schedule A, quantities and the delivery address. "
        "The Supplier will confirm each order in writing within four (4) working hours. An order is binding "
        "once confirmed.",
    ]),
    ("6. Delivery", [
        "The Supplier will deliver confirmed orders to the Buyer's premises in Kericho town within five (5) "
        "working days of confirmation. Deliveries to sites outside Kericho town but within Kericho County "
        "will be made within seven (7) working days and carry a transport charge of KES 45 per kilometre "
        "beyond the town boundary.",
        "Delivery is free for orders above KES 150,000. For orders between KES 50,000 and KES 150,000 a "
        "flat delivery fee of KES 3,500 applies.",
        "Deliveries will be made between 8:00 a.m. and 5:00 p.m., Monday to Saturday, excluding public "
        "holidays. The Buyer must inspect goods on delivery and note any shortage or visible damage on the "
        "delivery note before signing it.",
    ]),
    ("7. Late delivery", [
        "If the Supplier delivers later than the period in clause 6, the Buyer is entitled to a discount of "
        "one percent (1%) of the value of the late goods for each working day of delay, up to a maximum of "
        "ten percent (10%).",
        "If a delivery is more than ten (10) working days late, the Buyer may cancel that order without "
        "penalty and buy the goods elsewhere. The Supplier will then refund any deposit paid for that order "
        "within seven (7) days.",
        "The Supplier is not liable for delays caused by events outside its reasonable control, including "
        "road closures, strikes, floods or factory shutdowns (\"Force Majeure\"), provided it notifies the "
        "Buyer within 48 hours of becoming aware of the event.",
    ]),
    ("8. Payment terms", [
        "The Supplier will issue a KRA eTIMS-compliant tax invoice for every delivery. The Buyer will pay "
        "each invoice within thirty (30) days of the invoice date.",
        "Payment may be made by bank transfer to Rift Valley Building Supplies Ltd, KCB Bank, Nakuru "
        "Branch, account 1100223344, or by M-Pesa Paybill 522522, account number RVBS-MLIMANI.",
        "The Buyer may deduct a prompt-payment discount of two percent (2%) if an invoice is paid in full "
        "within seven (7) days of the invoice date.",
        "The Supplier grants the Buyer a credit limit of KES 800,000. The Supplier may decline new orders "
        "while the Buyer's unpaid balance is above this limit.",
    ]),
    ("9. Late payment", [
        "Overdue invoices attract interest at one and a half percent (1.5%) per month on the unpaid amount, "
        "calculated daily from the due date until payment.",
        "If any invoice remains unpaid for more than sixty (60) days after its due date, the Supplier may "
        "suspend deliveries until the account is brought up to date, after giving the Buyer seven (7) days' "
        "written notice.",
        "Cheques returned unpaid by the bank attract a charge of KES 3,000 per cheque.",
    ]),
    ("10. Returns and defective goods", [
        "The Buyer may return goods that are defective, damaged on delivery, or not what was ordered, within "
        "fourteen (14) days of delivery. The Supplier will collect such goods at its own cost and either "
        "replace them within five (5) working days or issue a credit note, at the Buyer's choice.",
        "Undamaged goods ordered in error may be returned within seven (7) days subject to a restocking fee "
        "of ten percent (10%). Cement older than sixty (60) days from its manufacture date and goods cut "
        "to size (such as roofing sheets cut to length) cannot be returned unless defective.",
    ]),
    ("11. Warranty", [
        "The Supplier warrants that all goods meet the relevant Kenya Bureau of Standards (KEBS) standards "
        "and carry a valid KEBS mark where required. Galvanised roofing sheets carry a manufacturer's "
        "warranty of ten (10) years against rust-through under normal conditions. Plumbing fittings carry a "
        "twelve (12) month warranty against manufacturing defects.",
    ]),
    ("12. Exclusivity", [
        "This Agreement is not exclusive. The Buyer may buy the same goods from other suppliers. However, "
        "the Supplier agrees not to supply the products in Schedule A to any other retailer within a radius "
        "of two (2) kilometres of the Buyer's premises at prices lower than those in Schedule A.",
    ]),
    ("13. Termination", [
        "Either party may end this Agreement by giving ninety (90) days' written notice to the other.",
        "Either party may end this Agreement immediately by written notice if the other party commits a "
        "material breach and fails to correct it within fourteen (14) days of being asked to in writing, or "
        "if the other party becomes insolvent.",
        "On termination the Buyer must pay all outstanding invoices within thirty (30) days, and the "
        "Supplier must pay any volume rebate already earned.",
    ]),
    ("14. Confidentiality", [
        "Each party will keep the prices and terms of this Agreement confidential and will not disclose them "
        "to any third party except its professional advisers, lenders or as required by law.",
    ]),
    ("15. Disputes", [
        "The parties will first try to resolve any dispute by a meeting between Mr. Peter Kamau and Mrs. "
        "Grace Chepkoech within ten (10) days of either party raising it in writing.",
        "If the dispute is not resolved within thirty (30) days, it will be referred to a single arbitrator "
        "appointed by the Chairperson of the Chartered Institute of Arbitrators (Kenya Branch). The "
        "arbitration will take place in Nakuru and the arbitrator's decision will be final and binding.",
    ]),
    ("16. Governing law and notices", [
        "This Agreement is governed by the laws of Kenya. Notices must be in writing and sent by email with a "
        "copy by registered post to the addresses above. A notice sent by email is received on the next "
        "working day after it is sent.",
    ]),
]

PRODUCTS = {
    "CEM": [("Cement 42.5N 50kg", 780), ("Cement 32.5R 50kg", 720), ("White cement 25kg", 1650),
            ("Tile adhesive 20kg", 980), ("Ready mix mortar 40kg", 690)],
    "STL": [("Y8 deformed bar 12m", 520), ("Y10 deformed bar 12m", 790), ("Y12 deformed bar 12m", 1130),
            ("Y16 deformed bar 12m", 2010), ("Y20 deformed bar 12m", 3150), ("R6 round bar 12m", 310),
            ("BRC mesh A142 2.4x4.8m", 4850), ("BRC mesh A98 2.4x4.8m", 3600),
            ("Binding wire 25kg roll", 4300), ("Hollow section 2x2 inch 6m", 2650)],
    "ROF": [("Box profile sheet G30 3m", 1120), ("Box profile sheet G28 3m", 1380),
            ("Corrugated sheet G30 3m", 980), ("Corrugated sheet G32 2m", 590),
            ("Roofing ridge G30 2m", 650), ("Roofing nails 1kg", 280), ("Valley gutter 2m", 760)],
    "PLB": [("PPR pipe 20mm 4m", 340), ("PPR pipe 25mm 4m", 510), ("PVC pipe 4 inch 6m", 1850),
            ("PVC pipe 2 inch 6m", 720), ("Gate valve 1/2 inch", 690), ("Gate valve 1 inch", 1480),
            ("Water tank 1000L", 9800), ("Water tank 5000L", 41500), ("Pillar tap chrome", 950),
            ("Toilet set close-coupled", 8900)],
    "ELC": [("Cable 2.5mm twin & earth 100m", 8600), ("Cable 1.5mm twin & earth 100m", 5700),
            ("Single switch socket 13A", 420), ("Twin switch socket 13A", 690),
            ("Consumer unit 8-way", 4800), ("LED bulb 12W", 210), ("Conduit pipe 20mm 3m", 95)],
    "PNT": [("Emulsion paint white 20L", 6400), ("Emulsion paint white 4L", 1450),
            ("Gloss paint 4L", 2350), ("Wood varnish 4L", 2700), ("Thinner 5L", 1250),
            ("Paint brush 4 inch", 260), ("Roller set 9 inch", 650)],
    "TLS": [("Wheelbarrow heavy duty", 6800), ("Spade", 750), ("Jembe", 680), ("Claw hammer", 690),
            ("Tape measure 5m", 380), ("Spirit level 600mm", 1100), ("Masonry trowel", 420)],
    "TIM": [("Timber cypress 2x4 per ft", 85), ("Timber cypress 2x3 per ft", 62),
            ("Timber cypress 3x2 per ft", 62), ("Plywood 18mm 8x4", 4700), ("Blockboard 18mm 8x4", 5200),
            ("Marine board 18mm 8x4", 6900), ("Fascia board 1x8 per ft", 95)],
    "HWR": [("Wire nails 3 inch 1kg", 210), ("Wire nails 4 inch 1kg", 210), ("Hinges 4 inch pair", 240),
            ("Padlock 50mm", 650), ("Door lock 3-lever", 1450), ("Door lock 4-lever", 1950),
            ("Barrel bolt 6 inch", 180), ("Chain-link fence 1.2m x 20m", 4650), ("Barbed wire 25kg", 4950)],
}
SIZES = ["", " (bulk 10+)", " (bulk 50+)", " (pallet)"]


def schedule_rows():
    random.seed(7)
    rows, n = [], 0
    for code, items in PRODUCTS.items():
        for name, price in items:
            for size in SIZES:
                n += 1
                discount = {"": 1, " (bulk 10+)": 0.97, " (bulk 50+)": 0.94, " (pallet)": 0.91}[size]
                unit = round(price * discount / 5) * 5
                rows.append([f"{code}-{n:04d}", name + size, f"{unit:,}",
                             random.choice(["In stock", "In stock", "In stock", "3 days", "7 days"])])
    return rows


def main():
    OUT.parent.mkdir(exist_ok=True)
    ss = getSampleStyleSheet()
    body = ParagraphStyle("body", parent=ss["BodyText"], fontSize=10.5, leading=15, spaceAfter=7)
    h1 = ParagraphStyle("h1", parent=ss["Heading1"], fontSize=17, spaceAfter=4)
    h2 = ParagraphStyle("h2", parent=ss["Heading2"], fontSize=12.5, spaceBefore=10, spaceAfter=4,
                        textColor=colors.HexColor("#1F4E79"))
    story = [Paragraph("SUPPLY AGREEMENT", h1),
             Paragraph("Rift Valley Building Supplies Ltd and Mlimani Hardware &amp; Building Supplies", body),
             Spacer(1, 6)]
    for title, paras in CLAUSES:
        story.append(Paragraph(title, h2))
        story += [Paragraph(p, body) for p in paras]

    story += [Spacer(1, 18), Paragraph("Signed for the Supplier: Peter Kamau, Sales Director, 3 March 2026", body),
              Paragraph("Signed for the Buyer: Grace Chepkoech, Proprietor, 3 March 2026", body),
              PageBreak(), Paragraph("SCHEDULE A: PRICE SCHEDULE", h1),
              Paragraph("Prices in KES per unit, VAT inclusive, valid 1 April to 30 June 2026. Lead time "
                        "shows how long an out-of-stock item takes to arrive.", body)]
    table = Table([["Code", "Product", "Price (KES)", "Lead time"]] + schedule_rows(),
                  colWidths=[28 * mm, 85 * mm, 28 * mm, 25 * mm], repeatRows=1)
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1F4E79")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTSIZE", (0, 0), (-1, -1), 9),
        ("ALIGN", (2, 1), (2, -1), "RIGHT"),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#F3F5F9")]),
        ("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#D9DEE7")),
    ]))
    story.append(table)

    def footer(canvas, doc):
        canvas.setFont("Helvetica", 8)
        canvas.setFillColor(colors.grey)
        canvas.drawString(20 * mm, 12 * mm, "Supply Agreement: Rift Valley Building Supplies / Mlimani Hardware")
        canvas.drawRightString(190 * mm, 12 * mm, f"Page {doc.page}")

    SimpleDocTemplate(str(OUT), pagesize=A4, leftMargin=20 * mm, rightMargin=20 * mm,
                      topMargin=18 * mm, bottomMargin=20 * mm, title="Supply Agreement",
                      author="Sample document for doc_qa.py").build(story, onFirstPage=footer, onLaterPages=footer)
    print(f"Saved {OUT.relative_to(OUT.parent.parent)}")


if __name__ == "__main__":
    main()
