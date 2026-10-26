#!/usr/bin/env python3
"""Format the retained settling methods as a searchable, rich-text PDF.

Run from the repository root: python clemson_amp/scripts/settling_methods_pdf.py
Requires ReportLab (rendered with version 4.4.9); no model or plot is rerun.
The October 20 source text is preserved. Equations use mathematical typography.
"""
from __future__ import annotations

import argparse
from hashlib import sha256
from html import escape
from pathlib import Path
import re

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import ParagraphStyle
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle


def rich(text):
    """Apply typographic substitutions without rewriting source paragraphs."""
    text = escape(" ".join(text.split()))
    terms = {"rho_particle": "ρ<sub>particle</sub>", "rho_air": "ρ<sub>air</sub>",
             "d_ve": "d<sub>ve</sub>", "chi": "χ", "mu": "μ", "lambda": "λ",
             "Cc": "C<sub>c</sub>"}
    for word, markup in terms.items():
        text = re.sub(r"\b" + word + r"\b", lambda _: markup, text)
    text = text.replace("*", " × ").replace("kg/m3", "kg/m³")
    text = re.sub(r"doi:(10\.[0-9]+/[A-Za-z0-9.]+)",
                  lambda m: f'<link href="https://doi.org/{m[1]}" color="#005A91">doi:{m[1]}</link>', text)
    return text


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=Path("clemson_amp/revisions/2026-10-20/settling_figures_methods.txt"))
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    source = args.source.read_text()
    blocks = source.strip().split("\n\n")
    if len(blocks) != 14 or blocks[0] != "METHODS: theoretical_settling_v2 and settling_velocity_vs_chi\nRevision: 2026-10-20":
        raise ValueError("Source structure changed; review the document layout before converting")
    output = args.output or args.source.with_suffix(".pdf")
    output.parent.mkdir(parents=True, exist_ok=True)

    font_dir = Path("/usr/share/fonts/truetype/dejavu")
    for name, filename in [("Methods", "DejaVuSans.ttf"), ("MethodsBold", "DejaVuSans-Bold.ttf")]:
        pdfmetrics.registerFont(TTFont(name, str(font_dir / filename)))
    pdfmetrics.registerFontFamily("Methods", normal="Methods", bold="MethodsBold", italic="Methods", boldItalic="MethodsBold")
    navy, teal = colors.HexColor("#18354B"), colors.HexColor("#006C80")
    styles = {
        "body": ParagraphStyle("Body", fontName="Methods", fontSize=10.1, leading=14.3, spaceAfter=7, textColor=colors.HexColor("#222B33")),
        "heading": ParagraphStyle("Heading", fontName="MethodsBold", fontSize=13.3, leading=18, textColor=navy, spaceBefore=9, spaceAfter=8, keepWithNext=True),
        "title": ParagraphStyle("Title", fontName="MethodsBold", fontSize=25, leading=30, textColor=navy, spaceAfter=8),
        "subtitle": ParagraphStyle("Subtitle", fontName="Methods", fontSize=9, leading=13, textColor=teal, spaceAfter=12),
        "equation": ParagraphStyle("Equation", fontName="Methods", fontSize=11.2, leading=23, alignment=TA_CENTER),
        "cell": ParagraphStyle("Cell", fontName="Methods", fontSize=9.2, leading=13),
        "cellhead": ParagraphStyle("CellHead", fontName="MethodsBold", fontSize=9.2, leading=13, textColor=colors.white),
    }
    def para(text, style="body"):
        return Paragraph(rich(text), styles[style])

    def section(block):
        title, body = block.split("\n", 1)
        story.extend([para(title, "heading"), para(body)])

    def table(rows, widths):
        cells = [[para(value, "cellhead" if i == 0 else "cell") for value in row] for i, row in enumerate(rows)]
        t = Table(cells, colWidths=widths, repeatRows=1, hAlign="LEFT")
        t.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), navy),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.HexColor("#F0F5F7"), colors.white]),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("LEFTPADDING", (0, 0), (-1, -1), 9), ("RIGHTPADDING", (0, 0), (-1, -1), 9),
            ("TOPPADDING", (0, 0), (-1, -1), 5), ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
            ("LINEBELOW", (0, -1), (-1, -1), .5, colors.HexColor("#CEDCE3")),
        ]))
        return t

    story = [para("Settling figure methods", "title"),
             Paragraph("theoretical_settling_v2 · settling_velocity_vs_chi<br/>Original methods revision: 20 October 2026", styles["subtitle"])]
    story.append(para(blocks[1]))
    section(blocks[2])

    equation_lines = blocks[3].splitlines()
    expected_equations = [
        "v = (rho_particle - rho_air) * g * d_ve^2 * Cc(d_ve) / (18 * mu * chi)",
        "Cc = 1 + (2*lambda/d_ve) * [1.257 + 0.4*exp(-0.55*d_ve/lambda)]",
    ]
    if [s.strip() for s in equation_lines[1:3]] != expected_equations:
        raise ValueError("Equations changed; review mathematical typesetting")
    story.append(para(equation_lines[0]))
    eq = [Paragraph("v = (ρ<sub>particle</sub> − ρ<sub>air</sub>) g d<sub>ve</sub><super>2</super> C<sub>c</sub>(d<sub>ve</sub>) / (18 μ χ)", styles["equation"]),
          Paragraph("C<sub>c</sub> = 1 + (2 λ / d<sub>ve</sub>) [1.257 + 0.4 exp(−0.55 d<sub>ve</sub> / λ)]", styles["equation"])]
    box = Table([[e] for e in eq], colWidths=[504], hAlign="LEFT")
    box.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#EDF4F7")),
                            ("TOPPADDING", (0, 0), (-1, -1), 4), ("BOTTOMPADDING", (0, 0), (-1, -1), 4)]))
    story.extend([box, Spacer(1, 8), para("\n".join(equation_lines[3:]))])

    const_lines = blocks[4].splitlines()
    story.append(para(const_lines[0]))
    expected_constants = ["gravitational acceleration g = 9.80616 m/s2", "air dynamic viscosity mu = 1.81e-5 Pa s",
                          "air density rho_air = 1.2 kg/m3", "air mean free path lambda = 65e-9 m"]
    if [s.strip() for s in const_lines[1:5]] != expected_constants:
        raise ValueError("Constants changed; review table")
    rows = [["Fixed property", "Value"], ["Gravitational acceleration, g", "9.80616 m/s²"],
            ["Air dynamic viscosity, mu", "1.81 × 10⁻⁵ Pa s"], ["Air density, rho_air", "1.2 kg/m³"],
            ["Air mean free path, lambda", "65 × 10⁻⁹ m"]]
    story.extend([table(rows, [294, 210]), Spacer(1, 9), para("\n".join(const_lines[5:])), para(blocks[5]), PageBreak()])

    section(blocks[6])
    section(blocks[7])
    section(blocks[8])
    geometry_rows = [re.split(r"\s{2,}", s.strip()) for s in blocks[9].splitlines()]
    if len(geometry_rows) != 8:
        raise ValueError("Geometry table changed")
    geometry_rows = [row + [""] * (3 - len(row)) for row in geometry_rows]
    story.extend([table(geometry_rows, [234, 90, 180]), PageBreak(),
                  para("MORPHOTYPE EVIDENCE AND CAVEATS — CONTINUED", "heading")])
    story.extend(para(blocks[i]) for i in (10, 11, 12))
    section(blocks[13])

    def page_furniture(canvas, doc):
        canvas.saveState()
        canvas.setStrokeColor(teal)
        canvas.setLineWidth(.8)
        canvas.line(54, 753, 558, 753)
        canvas.setFont("Methods", 8)
        canvas.setFillColor(colors.HexColor("#526370"))
        canvas.drawString(54, 765, "CLEMSON AMP POSTER  /  ANALYTICAL SETTLING METHODS")
        canvas.line(54, 42, 558, 42)
        canvas.drawString(54, 27, "Methods revision: 2026-10-20")
        canvas.drawRightString(558, 27, f"{doc.page}")
        canvas.restoreState()

    doc = SimpleDocTemplate(str(output), pagesize=letter, leftMargin=54, rightMargin=54,
                            topMargin=52, bottomMargin=48, title="Settling figure methods",
                            subject="Formatted edition of settling_figures_methods.txt; analytical calculations separate from AERMOD outputs")
    doc.build(story, onFirstPage=page_furniture, onLaterPages=page_furniture)
    print(f"Saved {output}; source SHA-256: {sha256(args.source.read_bytes()).hexdigest()}")


if __name__ == "__main__":
    main()
