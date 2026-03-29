"""Professional PDF invoice generation using reportlab."""

import io
from reportlab.lib import colors
from reportlab.lib.pagesizes import letter
from reportlab.lib.units import inch, mm
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.platypus import (
    SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer, HRFlowable
)
from reportlab.lib.enums import TA_LEFT, TA_RIGHT, TA_CENTER
from calculator import format_currency


def generate_invoice_pdf(invoice: dict, company_name: str = "InvoicePilot", company_address: str = "") -> bytes:
    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf,
        pagesize=letter,
        rightMargin=0.75 * inch,
        leftMargin=0.75 * inch,
        topMargin=0.6 * inch,
        bottomMargin=0.6 * inch,
    )

    styles = getSampleStyleSheet()
    story = []

    # Custom styles
    title_style = ParagraphStyle(
        "InvTitle", parent=styles["Title"], fontSize=28, textColor=colors.HexColor("#1a1a2e"),
        spaceAfter=2, fontName="Helvetica-Bold",
    )
    heading_style = ParagraphStyle(
        "InvHeading", parent=styles["Normal"], fontSize=11, textColor=colors.HexColor("#6c63ff"),
        fontName="Helvetica-Bold", spaceAfter=4,
    )
    normal_style = ParagraphStyle(
        "InvNormal", parent=styles["Normal"], fontSize=10, textColor=colors.HexColor("#333333"),
        leading=14,
    )
    small_style = ParagraphStyle(
        "InvSmall", parent=styles["Normal"], fontSize=8.5, textColor=colors.HexColor("#666666"),
        leading=12,
    )
    right_style = ParagraphStyle(
        "InvRight", parent=normal_style, alignment=TA_RIGHT,
    )
    right_bold = ParagraphStyle(
        "InvRightBold", parent=right_style, fontName="Helvetica-Bold",
    )
    center_style = ParagraphStyle(
        "InvCenter", parent=normal_style, alignment=TA_CENTER,
    )

    currency = invoice.get("currency", "USD")

    # Header row: Company name + INVOICE label
    header_data = [
        [
            Paragraph(company_name, title_style),
            Paragraph("INVOICE", ParagraphStyle(
                "InvLabel", parent=styles["Title"], fontSize=28,
                textColor=colors.HexColor("#6c63ff"), alignment=TA_RIGHT,
                fontName="Helvetica-Bold",
            )),
        ]
    ]
    header_table = Table(header_data, colWidths=[3.5 * inch, 3.5 * inch])
    header_table.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("RIGHTPADDING", (0, 0), (-1, -1), 0),
    ]))
    story.append(header_table)
    story.append(Spacer(1, 4))

    # Accent line
    story.append(HRFlowable(
        width="100%", thickness=3, color=colors.HexColor("#6c63ff"),
        spaceAfter=16, spaceBefore=4,
    ))

    # Invoice info + Bill To
    inv_number = invoice.get("invoice_number", "")
    created = invoice.get("created_at", "")[:10]
    due_date = invoice.get("due_date", "")[:10]
    status = invoice.get("status", "draft").upper()

    status_colors = {
        "DRAFT": "#999999", "SENT": "#2196f3", "OVERDUE": "#f44336", "PAID": "#4caf50",
    }
    status_color = status_colors.get(status, "#999999")

    left_info = f"""
    <b>Invoice #:</b> {inv_number}<br/>
    <b>Date:</b> {created}<br/>
    <b>Due Date:</b> {due_date}<br/>
    <b>Status:</b> <font color="{status_color}"><b>{status}</b></font>
    """

    if company_address:
        left_info = f"<b>From:</b><br/>{company_address}<br/><br/>" + left_info.strip()

    right_info = f"""
    <b>Bill To:</b><br/>
    {invoice.get('client_name', '')}<br/>
    {invoice.get('client_email', '')}
    """

    info_data = [
        [Paragraph(left_info.strip(), normal_style), Paragraph(right_info.strip(), normal_style)]
    ]
    info_table = Table(info_data, colWidths=[3.5 * inch, 3.5 * inch])
    info_table.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("RIGHTPADDING", (0, 0), (-1, -1), 0),
    ]))
    story.append(info_table)
    story.append(Spacer(1, 24))

    # Line items table
    items = invoice.get("items", [])
    header_row = [
        Paragraph("<b>#</b>", ParagraphStyle("H", parent=small_style, textColor=colors.white, fontName="Helvetica-Bold")),
        Paragraph("<b>Description</b>", ParagraphStyle("H", parent=small_style, textColor=colors.white, fontName="Helvetica-Bold")),
        Paragraph("<b>Qty</b>", ParagraphStyle("H", parent=small_style, textColor=colors.white, fontName="Helvetica-Bold", alignment=TA_CENTER)),
        Paragraph("<b>Rate</b>", ParagraphStyle("H", parent=small_style, textColor=colors.white, fontName="Helvetica-Bold", alignment=TA_RIGHT)),
        Paragraph("<b>Amount</b>", ParagraphStyle("H", parent=small_style, textColor=colors.white, fontName="Helvetica-Bold", alignment=TA_RIGHT)),
    ]
    table_data = [header_row]

    for i, item in enumerate(items, 1):
        qty = item.get("qty", 0)
        rate = item.get("rate", 0)
        amount = round(qty * rate, 2)
        table_data.append([
            Paragraph(str(i), small_style),
            Paragraph(item.get("description", ""), normal_style),
            Paragraph(str(qty), ParagraphStyle("C", parent=small_style, alignment=TA_CENTER)),
            Paragraph(format_currency(rate, currency), ParagraphStyle("R", parent=small_style, alignment=TA_RIGHT)),
            Paragraph(format_currency(amount, currency), ParagraphStyle("R", parent=small_style, alignment=TA_RIGHT)),
        ])

    col_widths = [0.4 * inch, 3.6 * inch, 0.7 * inch, 1.1 * inch, 1.2 * inch]
    items_table = Table(table_data, colWidths=col_widths, repeatRows=1)
    items_table.setStyle(TableStyle([
        # Header
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1a1a2e")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, 0), 9),
        ("TOPPADDING", (0, 0), (-1, 0), 10),
        ("BOTTOMPADDING", (0, 0), (-1, 0), 10),
        # Body rows
        ("FONTSIZE", (0, 1), (-1, -1), 9),
        ("TOPPADDING", (0, 1), (-1, -1), 8),
        ("BOTTOMPADDING", (0, 1), (-1, -1), 8),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING", (0, 0), (-1, -1), 8),
        ("RIGHTPADDING", (0, 0), (-1, -1), 8),
        # Alternating row colors
        *[("BACKGROUND", (0, i), (-1, i), colors.HexColor("#f8f9ff")) for i in range(1, len(table_data), 2)],
        *[("BACKGROUND", (0, i), (-1, i), colors.white) for i in range(2, len(table_data), 2)],
        # Grid
        ("LINEBELOW", (0, 0), (-1, 0), 1, colors.HexColor("#1a1a2e")),
        ("LINEBELOW", (0, -1), (-1, -1), 1, colors.HexColor("#dddddd")),
    ]))
    story.append(items_table)
    story.append(Spacer(1, 16))

    # Totals section (right-aligned)
    subtotal = invoice.get("subtotal", 0)
    tax_rate = invoice.get("tax_rate", 0)
    tax = invoice.get("tax", 0)
    late_fee = invoice.get("late_fee_applied", 0)
    total = invoice.get("total", 0)

    totals_data = [
        [Paragraph("Subtotal", right_style), Paragraph(format_currency(subtotal, currency), right_style)],
    ]
    if tax_rate > 0:
        totals_data.append([
            Paragraph(f"Tax ({tax_rate}%)", right_style),
            Paragraph(format_currency(tax, currency), right_style),
        ])
    if late_fee > 0:
        totals_data.append([
            Paragraph("Late Fee", ParagraphStyle("LateFee", parent=right_style, textColor=colors.HexColor("#f44336"))),
            Paragraph(format_currency(late_fee, currency), ParagraphStyle("LateFee", parent=right_style, textColor=colors.HexColor("#f44336"))),
        ])

    totals_data.append([
        Paragraph("<b>TOTAL DUE</b>", ParagraphStyle("TotalLabel", parent=right_bold, fontSize=12, textColor=colors.HexColor("#1a1a2e"))),
        Paragraph(f"<b>{format_currency(total, currency)}</b>", ParagraphStyle("TotalVal", parent=right_bold, fontSize=12, textColor=colors.HexColor("#6c63ff"))),
    ])

    totals_table = Table(totals_data, colWidths=[5 * inch, 2 * inch])
    totals_table.setStyle(TableStyle([
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("RIGHTPADDING", (0, 0), (-1, -1), 0),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ("LINEABOVE", (0, -1), (-1, -1), 2, colors.HexColor("#1a1a2e")),
    ]))
    story.append(totals_table)
    story.append(Spacer(1, 30))

    # Notes
    notes = invoice.get("notes")
    if notes:
        story.append(Paragraph("Notes", heading_style))
        story.append(Paragraph(notes, small_style))
        story.append(Spacer(1, 16))

    # Payment info
    payment_link = invoice.get("payment_link")
    if payment_link:
        story.append(Paragraph("Payment", heading_style))
        story.append(Paragraph(
            f'Pay online: <link href="{payment_link}" color="#6c63ff">{payment_link}</link>',
            small_style,
        ))
        story.append(Spacer(1, 16))

    # Footer
    story.append(Spacer(1, 20))
    story.append(HRFlowable(
        width="100%", thickness=1, color=colors.HexColor("#dddddd"),
        spaceAfter=8, spaceBefore=0,
    ))
    story.append(Paragraph(
        f"Generated by {company_name} | Thank you for your business",
        ParagraphStyle("Footer", parent=small_style, alignment=TA_CENTER, textColor=colors.HexColor("#999999")),
    ))

    doc.build(story)
    return buf.getvalue()
