"""Generate a larger synthetic lease corpus with known labels.

This corpus is for robustness and regression testing. It is not evidence of
real-world accuracy. Every document is fictional and generated locally.
"""

from __future__ import annotations

import json
import random
import shutil
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pypdfium2 as pdfium
from reportlab.lib import colors
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.pdfgen import canvas
from reportlab.platypus import (
    PageBreak,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

from paperproof.config import Settings
from paperproof.ingest.ocr import get_ocr_engine, tesseract_available
from paperproof.ingest.pdf import parse_pdf
from paperproof.samples import NumberedCanvas

PAGE_WIDTH, PAGE_HEIGHT = letter
TERM_WORDS = {
    6: "six (6) months",
    12: "twelve (12) months",
    18: "eighteen (18) months",
    24: "twenty-four (24) months",
    36: "thirty-six (36) months",
}
NOTICE_WORDS = {
    30: "thirty (30) days",
    45: "forty-five (45) days",
    60: "sixty (60) days",
    90: "ninety (90) days",
}
STREETS = (
    "Alder Court",
    "Beacon Street",
    "Juniper Way",
    "Marlowe Terrace",
    "Harbor Lane",
    "Chestnut Row",
    "Willow Bend",
    "Sparrow Hill",
    "Maple Crossing",
    "Birch Landing",
)
CITIES = ("Brookline", "Boston", "Somerville", "Cambridge", "Salem", "Quincy")
LANDLORDS = (
    "Alder Court Holdings LLC",
    "Beacon Street Partners LP",
    "Juniper Way Trust",
    "Marlowe Terrace LLC",
    "Harbor Lane Properties",
    "Northline Rentals",
)
TENANTS = (
    "Maya R. Chen",
    "Daniel Okafor",
    "Priya N. Raman",
    "Elena V. Petrova",
    "Jonah M. Fields",
    "Samira A. Haddad",
    "Marcus T. Reed",
)
TITLES = ("Residential Lease Agreement", "Apartment Lease", "Studio Lease", "Residential Lease")
LAYOUTS = ("standard", "compact", "letterhead", "table_heavy")


@dataclass(frozen=True)
class SyntheticLease:
    index: int
    slug: str
    title: str
    address: str
    landlord: str
    tenant: str
    term_months: int
    rent: float
    deposit: float
    notice_days: int
    sublet: str
    renewal: str
    late_fee: float
    layout: str
    scanned: bool
    amendment: bool
    silent: frozenset[str] = field(default_factory=frozenset)

    @property
    def filename(self) -> str:
        return f"{self.slug}.pdf"


@dataclass(frozen=True)
class SyntheticCorpusResult:
    path: Path
    cases_path: Path
    documents: int
    cases: int
    scanned: int
    amendments: int
    silent_cases: int
    elapsed_seconds: float


def _money(value: float) -> str:
    return f"{value:,.2f}"


def _styles(layout: str) -> dict[str, ParagraphStyle]:
    base = getSampleStyleSheet()
    compact = layout == "compact"
    body_size = 9.4 if compact else 10.5
    leading = 13.6 if compact else 16.0
    heading_size = 13 if compact else 15
    title_size = 23 if compact else 28
    return {
        "title": ParagraphStyle(
            "CoverTitle",
            parent=base["Title"],
            fontName="Times-Bold",
            fontSize=title_size,
            leading=title_size + 6,
            spaceAfter=16,
            textColor=colors.HexColor("#1c1a17"),
        ),
        "cover": ParagraphStyle(
            "CoverBody",
            parent=base["BodyText"],
            fontName="Helvetica",
            fontSize=10.5 if compact else 11,
            leading=17,
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
            fontSize=heading_size,
            leading=heading_size + 5,
            spaceBefore=14,
            spaceAfter=7,
            textColor=colors.HexColor("#1c1a17"),
        ),
        "body": ParagraphStyle(
            "Body",
            parent=base["BodyText"],
            fontName="Times-Roman",
            fontSize=body_size,
            leading=leading,
            spaceAfter=8,
            textColor=colors.HexColor("#22201c"),
        ),
    }


def _specs(count: int, seed: int, scan_rate: float) -> list[SyntheticLease]:
    rng = random.Random(seed)  # noqa: S311 - deterministic synthetic data
    leases: list[SyntheticLease] = []
    for index in range(1, count + 1):
        street = rng.choice(STREETS)
        city = rng.choice(CITIES)
        address = f"{rng.randint(2, 480)} {street}, {city}, MA 0{rng.randint(1000, 2999)}"
        term_months = rng.choice((6, 12, 12, 18, 24, 24, 36))
        rent = float(rng.choice(range(1200, 4201, 50)))
        deposit = round(rent * rng.choice((1, 1, 1.5, 2)), 2)
        notice_days = rng.choice((30, 30, 45, 60, 60, 90))
        sublet = rng.choice(
            ("prohibited", "allowed_with_consent", "allowed", "allowed_with_consent", "silent")
        )
        renewal = rng.choice(("none", "one", "two", "silent"))
        late_fee = float(rng.choice((50, 75, 90, 100, 125, 150, 175, 200)))
        layout = rng.choices(LAYOUTS, weights=(48, 20, 15, 17), k=1)[0]
        scanned = rng.random() < scan_rate
        amendment = rng.random() < 0.15

        silent: set[str] = set()
        if sublet == "silent":
            silent.add("subletting")
        if renewal == "silent":
            silent.add("renewal_option")
        if rng.random() < 0.12:
            silent.add("notice_days")
        if rng.random() < 0.08:
            silent.add("late_fee")

        leases.append(
            SyntheticLease(
                index=index,
                slug=f"synthetic_{index:04d}",
                title=rng.choice(TITLES),
                address=address,
                landlord=rng.choice(LANDLORDS),
                tenant=rng.choice(TENANTS),
                term_months=term_months,
                rent=rent,
                deposit=deposit,
                notice_days=notice_days,
                sublet="prohibited" if sublet == "silent" else sublet,
                renewal="none" if renewal == "silent" else renewal,
                late_fee=late_fee,
                layout=layout,
                scanned=scanned,
                amendment=amendment,
                silent=frozenset(silent),
            )
        )
    return leases


def _sublet_text(lease: SyntheticLease) -> str:
    if lease.sublet == "prohibited":
        return (
            "Tenant shall not sublet, assign, or otherwise transfer the Premises or any "
            "portion thereof without Landlord's prior written consent. Any attempted "
            "sublease without such consent shall be void."
        )
    if lease.sublet == "allowed":
        return (
            "Tenant may sublet the Premises without Landlord's prior written consent, "
            "provided that Tenant gives Landlord prompt written notice of the sublease "
            "and the identity of the proposed subtenant."
        )
    return (
        "Tenant may sublet the Premises only with Landlord's prior written consent, "
        "which consent shall not be unreasonably withheld, conditioned, or delayed."
    )


def _renewal_text(lease: SyntheticLease) -> str:
    if lease.renewal == "none":
        return "Tenant shall have no option to renew or extend the Term."
    if lease.renewal == "two":
        return (
            "Tenant shall have two (2) consecutive options to renew the Term for twelve "
            "(12) months each, exercisable by written notice delivered at least ninety "
            "(90) days before the end of the then-current Term."
        )
    return (
        "Tenant shall have one (1) option to renew the Term for an additional twelve "
        "(12) months by delivering written notice to Landlord no later than sixty (60) "
        "days before the expiration of the then-current Term."
    )


def _story(lease: SyntheticLease, styles: dict[str, ParagraphStyle]) -> list[Any]:
    story: list[Any] = []
    if lease.layout == "letterhead":
        story.append(Paragraph("NORTHLINE PROPERTY MANAGEMENT", styles["small"]))
        story.append(Spacer(1, 24))
    else:
        story.append(Paragraph("SYNTHETIC SAMPLE - NOT LEGAL ADVICE", styles["small"]))
        story.append(Spacer(1, 0.9 * inch))
    story.append(Paragraph(lease.title, styles["title"]))
    story.append(Spacer(1, 18))
    story.append(Paragraph(lease.address, styles["cover"]))
    story.append(Spacer(1, 30))
    story.append(Paragraph(f"Landlord: {lease.landlord}", styles["cover"]))
    story.append(Paragraph(f"Tenant: {lease.tenant}", styles["cover"]))
    story.append(Spacer(1, 18))
    story.append(Paragraph("Effective Date: February 1, 2026", styles["cover"]))
    story.append(Spacer(1, 1.2 * inch))
    story.append(
        Paragraph(
            "This document is generated for the Paperproof synthetic corpus.",
            styles["small"],
        )
    )
    story.append(PageBreak())

    story.append(Paragraph("1. Parties and Premises", styles["h1"]))
    story.append(
        Paragraph(
            f"This Agreement is made by and between {lease.landlord} (Landlord) and "
            f"{lease.tenant} (Tenant). Landlord leases to Tenant the premises located "
            f"at {lease.address} (the Premises), together with the appurtenances and "
            "fixtures belonging to the Premises.",
            styles["body"],
        )
    )
    story.append(
        Paragraph(
            "Tenant shall use the Premises only as a private residential dwelling and "
            "shall comply with all applicable laws, ordinances, and building rules.",
            styles["body"],
        )
    )

    story.append(Paragraph("2. Term", styles["h1"]))
    story.append(
        Paragraph(
            f"The term of this Lease is {TERM_WORDS[lease.term_months]}, commencing on "
            "February 1, 2026, and expiring on the last day of the final month of the "
            "Term, unless sooner terminated as provided herein.",
            styles["body"],
        )
    )
    story.append(
        Paragraph(
            "Tenant shall not occupy the Premises before the commencement date or after "
            "the expiration or earlier termination of the Term without written approval.",
            styles["body"],
        )
    )

    story.append(Paragraph("3. Rent", styles["h1"]))
    story.append(
        Paragraph(
            f"Tenant shall pay monthly rent of ${_money(lease.rent)}, due on the first "
            "day of each calendar month, without demand, deduction, or offset. Rent for "
            "any partial month shall be prorated on a per-diem basis.",
            styles["body"],
        )
    )
    if lease.layout == "table_heavy":
        table_data = [
            ["Period", "Monthly Rent", "Due Date"],
            ["Months 1-12", f"${_money(lease.rent)}", "First of each month"],
            ["Renewal term", f"${_money(lease.rent)}", "First of each month"],
        ]
        table = Table(table_data, colWidths=[1.8 * inch, 1.6 * inch, 1.8 * inch])
        table.setStyle(
            TableStyle(
                [
                    ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                    ("FONTNAME", (0, 1), (-1, -1), "Times-Roman"),
                    ("FONTSIZE", (0, 0), (-1, -1), 9),
                    ("LINEBELOW", (0, 0), (-1, 0), 0.6, colors.HexColor("#b9b2a6")),
                    ("LINEBELOW", (0, 1), (-1, -2), 0.25, colors.HexColor("#ddd6ca")),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
                    ("TOPPADDING", (0, 0), (-1, -1), 6),
                ]
            )
        )
        story.append(table)
        story.append(Spacer(1, 8))

    story.append(Paragraph("4. Security Deposit", styles["h1"]))
    story.append(
        Paragraph(
            f"Tenant shall pay a security deposit of ${_money(lease.deposit)} upon "
            "execution of this Lease. The deposit shall be held as security for the "
            "faithful performance of Tenant's obligations and returned less lawful "
            "deductions within thirty days after surrender.",
            styles["body"],
        )
    )

    story.append(Paragraph("5. Maintenance and Repairs", styles["h1"]))
    story.append(
        Paragraph(
            "Tenant shall keep the Premises clean, safe, and in good repair, ordinary "
            "wear and tear excepted, and shall promptly report any leak, electrical "
            "fault, heating failure, or other condition that could damage the Premises.",
            styles["body"],
        )
    )
    story.append(
        Paragraph(
            "Landlord shall repair the structural elements, roof, and building systems, "
            "except where the need for repair arises from Tenant's negligence. Landlord "
            "may enter upon reasonable notice to make repairs or show the Premises.",
            styles["body"],
        )
    )

    if "subletting" not in lease.silent:
        story.append(Paragraph("6. Subletting and Assignment", styles["h1"]))
        story.append(Paragraph(_sublet_text(lease), styles["body"]))
        story.append(
            Paragraph(
                "A consent to one sublease or assignment shall not constitute consent "
                "to any subsequent sublease or assignment.",
                styles["body"],
            )
        )

    if "notice_days" not in lease.silent:
        story.append(Paragraph("7. Notices and Termination", styles["h1"]))
        story.append(
            Paragraph(
                "Either party may terminate this Lease at the end of the initial term "
                f"by giving {NOTICE_WORDS[lease.notice_days]}' prior written notice to "
                "the other party. Notice by email is effective only if acknowledged in "
                "writing by the receiving party.",
                styles["body"],
            )
        )
    else:
        story.append(Paragraph("7. Notices", styles["h1"]))
        story.append(
            Paragraph(
                "Any notice required under this Agreement shall be in writing and "
                "delivered by hand, certified mail, or overnight courier to the address "
                "set forth on the cover page.",
                styles["body"],
            )
        )

    if "renewal_option" not in lease.silent:
        story.append(Paragraph("8. Renewal Option", styles["h1"]))
        story.append(Paragraph(_renewal_text(lease), styles["body"]))
    else:
        story.append(Paragraph("8. Holding Over", styles["h1"]))
        story.append(
            Paragraph(
                "Any holding over after the expiration of the Term shall be a "
                "month-to-month tenancy at the rent then in effect.",
                styles["body"],
            )
        )

    if "late_fee" not in lease.silent:
        story.append(Paragraph("9. Late Charges", styles["h1"]))
        story.append(
            Paragraph(
                "If any installment of rent is not received within five (5) days after "
                f"its due date, Tenant shall pay a late fee of ${_money(lease.late_fee)}. "
                "The parties agree this is a reasonable estimate of administrative cost.",
                styles["body"],
            )
        )

    story.append(Paragraph("10. Default and Remedies", styles["h1"]))
    story.append(
        Paragraph(
            "If Tenant fails to pay rent when due or breaches a material term, Landlord "
            "may provide written notice and pursue any remedy available at law or in "
            "equity, including termination and recovery of possession.",
            styles["body"],
        )
    )

    if lease.amendment:
        story.append(Paragraph("11. Amendment No. 1", styles["h1"]))
        story.append(
            Paragraph(
                "The parties confirm that the Term remains "
                f"{TERM_WORDS[lease.term_months]} and that monthly rent remains "
                f"${_money(lease.rent)}. This Amendment does not change any other term "
                "of the Lease and is incorporated by reference.",
                styles["body"],
            )
        )

    story.append(Paragraph("12. Signatures", styles["h1"]))
    story.append(Spacer(1, 0.35 * inch))
    signatures = [
        ["LANDLORD", "TENANT"],
        [lease.landlord, lease.tenant],
        ["By: ______________________", "By: ______________________"],
        ["Date: ____________________", "Date: ____________________"],
    ]
    signature_table = Table(signatures, colWidths=[2.8 * inch, 2.8 * inch])
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


def _build_text_pdf(path: Path, lease: SyntheticLease) -> None:
    styles = _styles(lease.layout)
    margin = 0.7 * inch if lease.layout == "compact" else 1.0 * inch
    document = SimpleDocTemplate(
        str(path),
        pagesize=letter,
        leftMargin=margin,
        rightMargin=margin,
        topMargin=0.8 * inch,
        bottomMargin=0.8 * inch,
        title=f"{lease.title} - {lease.address}",
        author=lease.landlord,
        subject="Synthetic sample for Paperproof",
    )
    document.build(_story(lease, styles), canvasmaker=NumberedCanvas)


def _build_scan_pdf(source: Path, target: Path, dpi: int = 150) -> None:
    document = pdfium.PdfDocument(str(source))
    images: list[Any] = []
    try:
        for index in range(len(document)):
            bitmap = document[index].render(scale=dpi / 72.0)  # pyright: ignore[reportArgumentType]
            try:
                images.append(bitmap.to_pil().convert("RGB"))
            finally:
                bitmap.close()
    finally:
        document.close()

    pdf = canvas.Canvas(str(target), pagesize=letter)
    with tempfile.TemporaryDirectory() as temp_dir:
        for index, image in enumerate(images):
            image_path = Path(temp_dir) / f"page_{index}.jpg"
            image.save(image_path, format="JPEG", quality=88)
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


def _phrase_for(field: str, lease: SyntheticLease) -> str | None:
    if field == "term_months":
        return f"({lease.term_months}) months"
    if field == "monthly_rent":
        return f"${_money(lease.rent)}"
    if field == "security_deposit":
        return f"${_money(lease.deposit)}"
    if field == "notice_days":
        return f"({lease.notice_days}) days"
    if field == "subletting":
        return "sublet"
    if field == "renewal_option":
        if lease.renewal == "none":
            return "no option to renew"
        if lease.renewal == "two":
            return "options to renew"
        return "option to renew"
    if field == "late_fee":
        return f"${_money(lease.late_fee)}"
    return None


def _case_for(
    lease: SyntheticLease,
    field: str,
    pages: list[Any],
) -> dict[str, Any]:
    if field in lease.silent:
        return {"doc": lease.filename, "field": field, "abstain": True}
    phrase = _phrase_for(field, lease)
    page = None
    if phrase:
        needle = " ".join(phrase.split()).casefold()
        matches = [
            record.pdf_page
            for record in pages
            if needle in " ".join(record.text.split()).casefold()
        ]
        if len(matches) == 1:
            page = matches[0]
    case: dict[str, Any] = {"doc": lease.filename, "field": field, "support": True}
    if field == "term_months":
        case["value"] = lease.term_months
    elif field == "monthly_rent":
        case["value"] = lease.rent
    elif field == "security_deposit":
        case["value"] = lease.deposit
    elif field == "notice_days":
        case["value"] = lease.notice_days
    elif field == "subletting":
        case["value"] = lease.sublet
    elif field == "renewal_option":
        if lease.renewal == "none":
            case["contains"] = "No renewal option"
        elif lease.renewal == "two":
            case["contains"] = "two (2) consecutive options"
        else:
            case["contains"] = "one (1) option to renew"
    elif field == "late_fee":
        case["value"] = lease.late_fee
    if phrase:
        case["quote_contains"] = phrase
    if page is not None:
        case["page"] = page
    return case


def generate_synthetic_corpus(
    settings: Settings,
    out_dir: Path,
    count: int = 100,
    seed: int = 7,
    scan_rate: float = 0.1,
    force: bool = False,
) -> SyntheticCorpusResult:
    if count < 1 or count > 500:
        raise ValueError("Count must be between 1 and 500.")
    if not 0.0 <= scan_rate <= 1.0:
        raise ValueError("scan_rate must be between 0 and 1.")
    if scan_rate > 0 and not tesseract_available():
        raise ValueError(
            "Tesseract is required to label scanned synthetic documents. "
            "Set scan_rate=0 or install tesseract-ocr."
        )

    out = Path(out_dir)
    data_root = settings.data_dir.resolve()
    if out.resolve() == data_root or out.resolve() in data_root.parents:
        raise ValueError("Output directory must not be the data directory or one of its parents.")
    if out.exists() and any(out.iterdir()):
        if not force:
            raise ValueError("Output directory is not empty. Use --force to replace it.")
        shutil.rmtree(out)
    out.mkdir(parents=True, exist_ok=True)
    build_dir = out / ".build"
    build_dir.mkdir()

    started = time.perf_counter()
    leases = _specs(count, seed, scan_rate)
    fields = (
        "term_months",
        "monthly_rent",
        "security_deposit",
        "notice_days",
        "subletting",
        "renewal_option",
        "late_fee",
    )
    cases: list[dict[str, Any]] = []
    ocr_engine = get_ocr_engine(settings)

    try:
        for lease in leases:
            target = out / lease.filename
            if lease.scanned:
                source = build_dir / lease.filename
                _build_text_pdf(source, lease)
                _build_scan_pdf(source, target)
                source.unlink(missing_ok=True)
            else:
                _build_text_pdf(target, lease)

            parsed = parse_pdf(target, ocr_engine=ocr_engine if lease.scanned else None)
            for field_name in fields:
                cases.append(_case_for(lease, field_name, parsed.pages))
    finally:
        shutil.rmtree(build_dir, ignore_errors=True)

    cases_path = out / "cases.jsonl"
    cases_path.write_text("\n".join(json.dumps(case) for case in cases) + "\n", encoding="utf-8")
    manifest = {
        "format": "paperproof-synthetic-corpus",
        "version": 1,
        "seed": seed,
        "count": count,
        "scan_rate": scan_rate,
        "documents": count,
        "cases": len(cases),
        "scanned": sum(1 for lease in leases if lease.scanned),
        "amendments": sum(1 for lease in leases if lease.amendment),
        "silent_cases": sum(1 for case in cases if case.get("abstain")),
        "layouts": {
            layout: sum(1 for lease in leases if lease.layout == layout) for layout in LAYOUTS
        },
    }
    (out / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return SyntheticCorpusResult(
        path=out,
        cases_path=cases_path,
        documents=count,
        cases=len(cases),
        scanned=int(manifest["scanned"]),
        amendments=int(manifest["amendments"]),
        silent_cases=int(manifest["silent_cases"]),
        elapsed_seconds=round(time.perf_counter() - started, 1),
    )
