"""Generate a small, realistic lease corpus for demos, tests, and evals.

All documents are fictional. One is intentionally image-only so the OCR
warning path is visible. One is intentionally silent on a few clauses so
abstention can be observed.
"""

from __future__ import annotations

import textwrap
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from reportlab.lib import colors
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.pdfgen import canvas
from reportlab.platypus import (
    BaseDocTemplate,
    Frame,
    PageBreak,
    PageTemplate,
    Paragraph,
    Spacer,
    Table,
    TableStyle,
)
from reportlab.platypus.tableofcontents import TableOfContents

from paperproof.config import Settings

PAGE_WIDTH, PAGE_HEIGHT = letter


@dataclass(frozen=True)
class LeaseSpec:
    slug: str
    title: str
    address: str
    landlord: str
    tenant: str
    term_words: str
    term_months: int
    rent: str
    deposit: str
    notice_words: str
    sublet: str
    renewal: str
    late_fee: str
    silent_sublet: bool = False
    silent_renewal: bool = False
    silent_notice: bool = False
    scanned: bool = False


SPECS: tuple[LeaseSpec, ...] = (
    LeaseSpec(
        slug="lease_01_alder_court",
        title="Residential Lease Agreement",
        address="14 Alder Court, Brookline, MA 02446",
        landlord="Alder Court Holdings LLC",
        tenant="Maya R. Chen",
        term_words="twenty-four (24) months",
        term_months=24,
        rent="2,400.00",
        deposit="4,800.00",
        notice_words="thirty (30) days",
        sublet="allowed_with_consent",
        renewal=(
            "Tenant shall have one (1) option to renew the Term for an additional "
            "twelve (12) months by delivering written notice to Landlord no later "
            "than sixty (60) days before the expiration of the then-current Term."
        ),
        late_fee="150.00",
    ),
    LeaseSpec(
        slug="lease_02_beacon_street",
        title="Apartment Lease",
        address="88 Beacon Street, Unit 5B, Boston, MA 02108",
        landlord="Beacon Street Partners LP",
        tenant="Daniel Okafor",
        term_words="twelve (12) months",
        term_months=12,
        rent="3,150.00",
        deposit="3,000.00",
        notice_words="sixty (60) days",
        sublet="prohibited",
        renewal="No renewal option.",
        late_fee="75.00",
    ),
    LeaseSpec(
        slug="lease_03_juniper_way",
        title="Residential Lease",
        address="402 Juniper Way, Somerville, MA 02143",
        landlord="Juniper Way Trust",
        tenant="Priya N. Raman",
        term_words="thirty-six (36) months",
        term_months=36,
        rent="2,850.00",
        deposit="7,200.00",
        notice_words="ninety (90) days",
        sublet="allowed",
        renewal=(
            "Tenant shall have two (2) consecutive options to renew the Term for "
            "twelve (12) months each, exercisable by written notice delivered at "
            "least ninety (90) days before the end of the then-current Term."
        ),
        late_fee="100.00",
    ),
    LeaseSpec(
        slug="lease_04_marlowe_terrace",
        title="Residential Lease Agreement",
        address="9 Marlowe Terrace, Cambridge, MA 02139",
        landlord="Marlowe Terrace LLC",
        tenant="Elena V. Petrova",
        term_words="eighteen (18) months",
        term_months=18,
        rent="2,600.00",
        deposit="3,600.00",
        notice_words="thirty (30) days",
        sublet="allowed_with_consent",
        renewal="No renewal option.",
        late_fee="125.00",
        silent_sublet=True,
        silent_renewal=True,
        silent_notice=True,
    ),
    LeaseSpec(
        slug="lease_05_scanned_studio",
        title="Studio Lease",
        address="61 Harbor Lane, Unit 2, Salem, MA 01970",
        landlord="Harbor Lane Properties",
        tenant="Jonah M. Fields",
        term_words="twelve (12) months",
        term_months=12,
        rent="1,950.00",
        deposit="2,900.00",
        notice_words="thirty (30) days",
        sublet="prohibited",
        renewal="No renewal option.",
        late_fee="90.00",
        scanned=True,
    ),
)

BODY_TEXT = (
    "This Agreement is made and entered into by and between Landlord and Tenant "
    "as of the Effective Date stated on the cover page. Landlord leases to Tenant, "
    "and Tenant leases from Landlord, the Premises described above, together with "
    "the appurtenances, fixtures, and improvements belonging to the Premises, "
    "subject to the terms and conditions of this Agreement."
)

BOILERPLATE = (
    "Tenant shall keep the Premises clean, safe, and in good repair, ordinary wear "
    "and tear excepted, and shall promptly notify Landlord of any condition that "
    "requires repair. Tenant shall not make alterations to the Premises without "
    "Landlord's prior written consent. Landlord shall be responsible for repairs "
    "to the structural elements, roof, and building systems, except where the need "
    "for repair arises from Tenant's negligence or willful misconduct."
)

UTILITIES = (
    "Tenant shall pay all charges for electricity, gas, internet, cable, and other "
    "utility services furnished to the Premises during the Term. Landlord shall pay "
    "water and sewer charges. If any utility account is in Landlord's name, Tenant "
    "shall reimburse Landlord within fifteen days after receipt of an invoice."
)

DEFAULT = (
    "If Tenant fails to pay rent when due, or otherwise breaches a material term of "
    "this Agreement, Landlord may provide written notice and pursue any remedy "
    "available at law or in equity, including termination of this Agreement and "
    "recovery of possession. Tenant shall have the opportunity to cure a curable "
    "breach within the period required by applicable law."
)

MISC = (
    "This Agreement constitutes the entire agreement between the parties and "
    "supersedes all prior discussions and understandings. No amendment shall be "
    "effective unless in writing and signed by both parties. If any provision is "
    "held invalid, the remaining provisions shall continue in full force. This "
    "Agreement shall be governed by the laws of the Commonwealth of Massachusetts."
)


class NumberedCanvas(canvas.Canvas):
    def __init__(self, *args, **kwargs):  # type: ignore[no-untyped-def]
        canvas.Canvas.__init__(self, *args, **kwargs)
        self._saved_page_states: list[dict[str, object]] = []

    def showPage(self):
        self._saved_page_states.append(dict(self.__dict__))
        self._startPage()  # pyright: ignore[reportAttributeAccessIssue]

    def save(self):
        total = len(self._saved_page_states)
        for state in self._saved_page_states:
            self.__dict__.update(state)
            page_number = int(getattr(self, "_pageNumber", 1))
            if page_number > 1:
                self.setFont("Helvetica", 8)
                self.setFillColor(colors.HexColor("#6b6b6b"))
                self.drawCentredString(
                    PAGE_WIDTH / 2,
                    0.5 * inch,
                    f"Page {page_number - 1} of {total - 1}",
                )
            canvas.Canvas.showPage(self)
        canvas.Canvas.save(self)


class LeaseTemplate(BaseDocTemplate):
    def __init__(self, filename: str, spec: LeaseSpec, **kwargs):  # type: ignore[no-untyped-def]
        super().__init__(
            filename,
            pagesize=letter,
            leftMargin=inch,
            rightMargin=inch,
            topMargin=0.9 * inch,
            bottomMargin=0.9 * inch,
            title=f"{spec.title} - {spec.address}",
            author=spec.landlord,
            subject="Synthetic sample document for Paperproof",
        )
        self.spec = spec
        frame = Frame(
            self.leftMargin,
            self.bottomMargin,
            self.width,
            self.height,
            id="body",
        )
        self.addPageTemplates([PageTemplate(id="main", frames=[frame])])

    def afterFlowable(self, flowable):  # type: ignore[no-untyped-def]
        if isinstance(flowable, Paragraph):
            style_name = flowable.style.name
            if style_name.startswith("H") and len(style_name) == 2:
                level = int(style_name[1])
                self.notify("TOCEntry", (level, flowable.getPlainText(), self.page))


def _styles() -> dict[str, ParagraphStyle]:
    base = getSampleStyleSheet()
    return {
        "title": ParagraphStyle(
            "CoverTitle",
            parent=base["Title"],
            fontName="Times-Bold",
            fontSize=28,
            leading=34,
            spaceAfter=18,
            textColor=colors.HexColor("#1c1a17"),
        ),
        "cover": ParagraphStyle(
            "CoverBody",
            parent=base["BodyText"],
            fontName="Helvetica",
            fontSize=11,
            leading=18,
            alignment=1,
            textColor=colors.HexColor("#3d3a34"),
        ),
        "small": ParagraphStyle(
            "Small",
            parent=base["BodyText"],
            fontName="Helvetica",
            fontSize=8,
            leading=11,
            textColor=colors.HexColor("#7a746a"),
            alignment=1,
        ),
        "h1": ParagraphStyle(
            "H1",
            parent=base["Heading1"],
            fontName="Times-Bold",
            fontSize=15,
            leading=20,
            spaceBefore=18,
            spaceAfter=8,
            textColor=colors.HexColor("#1c1a17"),
        ),
        "h2": ParagraphStyle(
            "H2",
            parent=base["Heading2"],
            fontName="Times-Bold",
            fontSize=12,
            leading=16,
            spaceBefore=12,
            spaceAfter=5,
            textColor=colors.HexColor("#1c1a17"),
        ),
        "body": ParagraphStyle(
            "Body",
            parent=base["BodyText"],
            fontName="Times-Roman",
            fontSize=10.5,
            leading=16,
            spaceAfter=9,
            textColor=colors.HexColor("#22201c"),
        ),
        "toc_title": ParagraphStyle(
            "TOCTitle",
            parent=base["Heading1"],
            fontName="Times-Bold",
            fontSize=16,
            leading=20,
            spaceAfter=14,
        ),
    }


def _sublet_paragraph(spec: LeaseSpec) -> str:
    if spec.sublet == "allowed_with_consent":
        return (
            "Tenant may sublet the Premises only with Landlord's prior written "
            "consent, which consent shall not be unreasonably withheld, conditioned, "
            "or delayed. Any sublease shall be subject to the terms of this Agreement, "
            "and Tenant shall remain fully liable for all obligations under this "
            "Agreement."
        )
    if spec.sublet == "prohibited":
        return (
            "Tenant shall not sublet, assign, or otherwise transfer the Premises or "
            "any portion thereof without Landlord's prior written consent. Any "
            "attempted sublease, assignment, or transfer without such consent shall "
            "be void and shall constitute a material breach of this Agreement."
        )
    return (
        "Tenant may sublet the Premises without Landlord's prior written consent, "
        "provided that Tenant gives Landlord prompt written notice of the sublease "
        "and the identity of the proposed subtenant. Tenant shall remain fully "
        "liable for all obligations under this Agreement."
    )


def _story(spec: LeaseSpec, styles: dict[str, ParagraphStyle]) -> list[Any]:
    story: list[Any] = []
    banner_style = ParagraphStyle(
        "Banner",
        parent=styles["small"],
        fontName="Helvetica-Bold",
        fontSize=8,
        textColor=colors.HexColor("#8a5a12"),
        spaceAfter=26,
    )
    story.append(Paragraph("SAMPLE DOCUMENT - NOT LEGAL ADVICE", banner_style))
    story.append(Spacer(1, 1.1 * inch))
    story.append(Paragraph(spec.title, styles["title"]))
    story.append(Spacer(1, 0.25 * inch))
    story.append(Paragraph(spec.address, styles["cover"]))
    story.append(Spacer(1, 0.55 * inch))
    story.append(Paragraph(f"Landlord: {spec.landlord}", styles["cover"]))
    story.append(Paragraph(f"Tenant: {spec.tenant}", styles["cover"]))
    story.append(Spacer(1, 0.35 * inch))
    story.append(Paragraph("Effective Date: February 1, 2026", styles["cover"]))
    story.append(Spacer(1, 1.6 * inch))
    story.append(
        Paragraph(
            "This is a synthetic document generated for the Paperproof demo corpus.",
            styles["small"],
        )
    )
    story.append(PageBreak())

    story.append(Paragraph("Contents", styles["toc_title"]))
    toc = TableOfContents()
    toc.levelStyles = [
        ParagraphStyle(
            "TOC1",
            fontName="Times-Roman",
            fontSize=10,
            leading=15,
            leftIndent=0,
            firstLineIndent=0,
        )
    ]
    toc.dotsMinLevel = 0
    story.append(toc)
    story.append(PageBreak())

    story.append(Paragraph("1. Parties and Premises", styles["h1"]))
    story.append(
        Paragraph(
            f"This Agreement is made by and between {spec.landlord} (Landlord) and {spec.tenant} (Tenant).",
            styles["body"],
        )
    )
    story.append(
        Paragraph(
            f"Landlord leases to Tenant the premises located at {spec.address} (the Premises).",
            styles["body"],
        )
    )
    story.append(Paragraph(BODY_TEXT, styles["body"]))

    story.append(Paragraph("2. Term", styles["h2"]))
    start_year = 2026
    end_year = start_year + (spec.term_months // 12)
    story.append(
        Paragraph(
            f"The term of this Lease is {spec.term_words}, commencing on February 1, "
            f"{start_year}, and expiring on January 31, {end_year}, unless sooner "
            "terminated as provided herein (the Term).",
            styles["body"],
        )
    )
    story.append(
        Paragraph(
            "Tenant shall not occupy the Premises before the commencement date or "
            "after the expiration or earlier termination of the Term without "
            "Landlord's written approval.",
            styles["body"],
        )
    )

    story.append(Paragraph("3. Rent", styles["h1"]))
    story.append(
        Paragraph(
            f"Tenant shall pay monthly rent of ${spec.rent}, due on the first day of "
            "each calendar month, without demand, deduction, or offset. Rent for any "
            "partial month shall be prorated on a per-diem basis.",
            styles["body"],
        )
    )
    table_data = [
        ["Period", "Monthly Rent", "Due Date"],
        ["Months 1-12", f"${spec.rent}", "First of each month"],
    ]
    if not spec.silent_renewal and not spec.renewal.lower().startswith("no "):
        table_data.append(["Renewal term", f"${spec.rent}", "First of each month"])
    table = Table(table_data, colWidths=[1.8 * inch, 1.6 * inch, 1.8 * inch])
    table.setStyle(
        TableStyle(
            [
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("FONTNAME", (0, 1), (-1, -1), "Times-Roman"),
                ("FONTSIZE", (0, 0), (-1, -1), 9),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.HexColor("#3d3a34")),
                ("LINEBELOW", (0, 0), (-1, 0), 0.6, colors.HexColor("#b9b2a6")),
                ("LINEBELOW", (0, 1), (-1, -2), 0.25, colors.HexColor("#ddd6ca")),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
                ("TOPPADDING", (0, 0), (-1, -1), 6),
            ]
        )
    )
    story.append(table)
    story.append(Spacer(1, 8))
    story.append(
        Paragraph(
            "Rent shall be paid by electronic funds transfer or another method "
            "reasonably designated by Landlord. Tenant shall pay a returned payment "
            "fee of $35.00 for any dishonored payment instrument.",
            styles["body"],
        )
    )

    story.append(Paragraph("4. Security Deposit", styles["h2"]))
    story.append(
        Paragraph(
            f"Tenant shall pay a security deposit of ${spec.deposit} upon execution "
            "of this Lease. The security deposit shall be held by Landlord as security "
            "for the faithful performance of Tenant's obligations.",
            styles["body"],
        )
    )
    story.append(
        Paragraph(
            "Landlord shall return the security deposit, less any lawful deductions, "
            "within thirty days after the later of the expiration of the Term or "
            "Tenant's surrender of possession, together with an itemized statement "
            "of deductions.",
            styles["body"],
        )
    )

    story.append(Paragraph("5. Use and Occupancy", styles["h1"]))
    story.append(
        Paragraph(
            "The Premises shall be used solely as a private residential dwelling. "
            "Tenant shall not use the Premises for any commercial, manufacturing, or "
            "unlawful purpose, and shall comply with all applicable laws, ordinances, "
            "and building rules.",
            styles["body"],
        )
    )
    story.append(Paragraph(UTILITIES, styles["body"]))

    story.append(Paragraph("6. Maintenance and Repairs", styles["h2"]))
    story.append(Paragraph(BOILERPLATE, styles["body"]))
    story.append(
        Paragraph(
            "Tenant shall promptly report any leak, electrical fault, heating failure, "
            "or other condition that could damage the Premises. Landlord may enter the "
            "Premises upon reasonable notice to make repairs or show the Premises to "
            "prospective tenants or purchasers.",
            styles["body"],
        )
    )

    if not spec.silent_sublet:
        story.append(Paragraph("7. Subletting and Assignment", styles["h1"]))
        story.append(Paragraph(_sublet_paragraph(spec), styles["body"]))
        story.append(
            Paragraph(
                "A consent to one sublease or assignment shall not constitute consent "
                "to any subsequent sublease or assignment. Tenant shall pay Landlord's "
                "reasonable review costs for any requested consent.",
                styles["body"],
            )
        )

    if spec.silent_notice:
        story.append(Paragraph("8. Notices", styles["h1"]))
        story.append(
            Paragraph(
                "Any notice required under this Agreement shall be in writing and "
                "delivered by hand, certified mail, or nationally recognized overnight "
                "courier to the address set forth on the cover page, or by email to "
                "the address designated by the receiving party.",
                styles["body"],
            )
        )
    else:
        story.append(Paragraph("8. Notices and Termination", styles["h1"]))
        story.append(
            Paragraph(
                "Either party may terminate this Lease at the end of the initial term "
                f"by giving {spec.notice_words}' prior written notice to the other "
                "party. Notice given by email shall be effective only if acknowledged "
                "in writing by the receiving party.",
                styles["body"],
            )
        )
        story.append(
            Paragraph(
                "Notices of default, lease violations, or proposed rent changes shall "
                "be delivered in the manner required by applicable law and shall state "
                "the grounds for the notice with reasonable specificity.",
                styles["body"],
            )
        )

    if not spec.silent_renewal:
        story.append(Paragraph("9. Renewal Option", styles["h2"]))
        story.append(Paragraph(spec.renewal, styles["body"]))
        story.append(
            Paragraph(
                "The renewal option is personal to the named Tenant and may not be "
                "assigned or exercised by a subtenant. Time is of the essence with "
                "respect to the delivery of the renewal notice.",
                styles["body"],
            )
        )

    story.append(Paragraph("10. Late Charges", styles["h1"]))
    story.append(
        Paragraph(
            "If any installment of rent is not received within five (5) days after its "
            f"due date, Tenant shall pay a late fee of ${spec.late_fee}. The parties "
            "agree that this amount is a reasonable estimate of the administrative "
            "costs caused by late payment and is not a penalty.",
            styles["body"],
        )
    )

    story.append(Paragraph("11. Default and Remedies", styles["h1"]))
    story.append(Paragraph(DEFAULT, styles["body"]))
    story.append(
        Paragraph(
            "Landlord's remedies are cumulative and not exclusive. Tenant shall be "
            "responsible for reasonable attorneys' fees and costs incurred by Landlord "
            "in enforcing this Agreement, to the extent permitted by law.",
            styles["body"],
        )
    )

    story.append(Paragraph("12. Miscellaneous", styles["h2"]))
    story.append(Paragraph(MISC, styles["body"]))
    story.append(
        Paragraph(
            "This Agreement may be executed in counterparts, each of which shall be "
            "deemed an original and all of which together shall constitute one "
            "instrument. Electronic signatures shall have the same effect as originals.",
            styles["body"],
        )
    )

    story.append(Paragraph("13. Signatures", styles["h1"]))
    story.append(Spacer(1, 0.4 * inch))
    signature_data = [
        ["LANDLORD", "TENANT"],
        [spec.landlord, spec.tenant],
        ["By: ______________________", "By: ______________________"],
        ["Date: ____________________", "Date: ____________________"],
    ]
    signature_table = Table(signature_data, colWidths=[2.8 * inch, 2.8 * inch])
    signature_table.setStyle(
        TableStyle(
            [
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("FONTNAME", (0, 1), (-1, -1), "Times-Roman"),
                ("FONTSIZE", (0, 0), (-1, -1), 9),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 10),
            ]
        )
    )
    story.append(signature_table)
    return story


def _build_lease(path: Path, spec: LeaseSpec) -> None:
    styles = _styles()
    document = LeaseTemplate(str(path), spec)
    document.multiBuild(_story(spec, styles), canvasmaker=NumberedCanvas)


def _scan_pdf(path: Path, spec: LeaseSpec) -> None:
    from PIL import Image, ImageDraw, ImageFont

    width, height = 1275, 1650
    margin = 110
    font_path = "/usr/share/fonts/TTF/DejaVuSans.ttf"
    bold_path = "/usr/share/fonts/TTF/DejaVuSans-Bold.ttf"
    try:
        body_font = ImageFont.truetype(font_path, 25)
        title_font = ImageFont.truetype(bold_path, 44)
        small_font = ImageFont.truetype(font_path, 20)
    except OSError:
        body_font = ImageFont.load_default(size=25)
        title_font = ImageFont.load_default(size=44)
        small_font = ImageFont.load_default(size=20)

    paragraphs = [
        spec.title.upper(),
        "",
        f"Premises: {spec.address}",
        f"Landlord: {spec.landlord}",
        f"Tenant: {spec.tenant}",
        "",
        f"1. TERM. The term of this Lease is {spec.term_words}, commencing on "
        "February 1, 2026, and expiring on January 31, 2027, unless sooner terminated.",
        "",
        f"2. RENT. Tenant shall pay monthly rent of ${spec.rent}, due on the first "
        "day of each calendar month.",
        "",
        f"3. SECURITY DEPOSIT. Tenant shall pay a security deposit of ${spec.deposit} "
        "upon execution of this Lease.",
        "",
        "4. SUBLETTING. Tenant shall not sublet, assign, or otherwise transfer the "
        "Premises or any portion thereof without Landlord's prior written consent.",
        "",
        f"5. NOTICE. Either party may terminate this Lease at the end of the initial "
        f"term by giving {spec.notice_words}' prior written notice to the other party.",
        "",
        f"6. LATE FEE. Tenant shall pay a late fee of ${spec.late_fee} if rent is not "
        "received within five days after its due date.",
        "",
        "7. RENEWAL. Tenant shall have no option to renew or extend the Term.",
        "",
        "8. MAINTENANCE. Tenant shall keep the Premises clean and in good repair, "
        "ordinary wear and tear excepted.",
        "",
        "9. SIGNATURES. The parties have executed this Agreement as of the Effective Date.",
        "",
        f"Landlord: {spec.landlord}",
        "By: ______________________________",
        "",
        f"Tenant: {spec.tenant}",
        "By: ______________________________",
    ]

    wrapped: list[str] = []
    for paragraph in paragraphs:
        if not paragraph:
            wrapped.append("")
            continue
        wrapped.extend(textwrap.wrap(paragraph, width=78) or [""])

    lines_per_page = 26
    pages = [
        wrapped[index : index + lines_per_page] for index in range(0, len(wrapped), lines_per_page)
    ]
    total_pages = len(pages)

    import tempfile

    with tempfile.TemporaryDirectory(dir=path.parent) as temp_dir:
        images: list[Path] = []
        for page_index, page_lines in enumerate(pages, start=1):
            image = Image.new("RGB", (width, height), "white")
            draw = ImageDraw.Draw(image)
            y = margin
            for line in page_lines:
                font = title_font if line == spec.title.upper() else body_font
                draw.text((margin, y), line, font=font, fill="#1d1d1d")
                y += 40 if font is title_font else 31
            draw.text(
                (margin, height - 70),
                f"Page {page_index} of {total_pages}",
                font=small_font,
                fill="#555555",
            )
            image_path = Path(temp_dir) / f"page_{page_index}.png"
            image.save(image_path)
            images.append(image_path)

        pdf = canvas.Canvas(str(path), pagesize=letter)
        pdf.setTitle(spec.title)
        pdf.setAuthor(spec.landlord)
        for image_path in images:
            pdf.drawImage(
                str(image_path),
                0,
                0,
                width=PAGE_WIDTH,
                height=PAGE_HEIGHT,
                preserveAspectRatio=False,
            )
            pdf.showPage()
        pdf.save()


def generate_samples(settings: Settings, force: bool = False) -> list[Path]:
    settings.sample_dir.mkdir(parents=True, exist_ok=True)
    paths = [settings.sample_dir / f"{spec.slug}.pdf" for spec in SPECS]
    if not force and all(path.exists() for path in paths):
        return paths
    for old in settings.sample_dir.glob("*.pdf"):
        old.unlink(missing_ok=True)
    for spec, path in zip(SPECS, paths, strict=True):
        if spec.scanned:
            _scan_pdf(path, spec)
        else:
            _build_lease(path, spec)
    return paths
