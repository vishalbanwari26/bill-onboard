"""Invented UK electricity bills: consistent data, planted faults, drawn as images. No real customers or suppliers."""

import io
import json
import random
from datetime import date, timedelta
from pathlib import Path

from PIL import Image, ImageChops, ImageDraw, ImageEnhance, ImageFilter, ImageFont

from bill_onboard.checks import billed_days, check_bill, mpan_check_digit
from bill_onboard.models import Bill

SUPPLIERS = ("Northwind Energy", "Brightwater Power", "Kestrel Utilities")  # invented names


def make_mpan(rng: random.Random) -> str:
    """A random 13-digit MPAN core with a correct check digit."""
    first12 = "".join(str(rng.randint(0, 9)) for _ in range(12))
    return first12 + str(mpan_check_digit(first12))


def make_bill(rng: random.Random, supplier: str) -> Bill:
    """An invented bill whose numbers add up, rounded the way a bill prints them."""
    start = date(2026, rng.randint(1, 9), 1)
    end = start + timedelta(days=rng.randint(27, 92))  # monthly up to quarterly
    usage = rng.randint(80, 1400)
    rate = round(rng.uniform(20.0, 32.0), 2)  # p/kWh
    standing = round(rng.uniform(45.0, 65.0), 2)  # p/day
    energy = round(usage * rate / 100, 2)
    draft = Bill(supplier=supplier, account_number=f"A-{rng.randint(100000, 999999)}",
                 mpan_core=make_mpan(rng), period_start=start, period_end=end,
                 usage_kwh=usage, unit_rate_p_per_kwh=rate, energy_charge_gbp=energy,
                 standing_charge_p_per_day=standing, total_gbp=0)
    total = round((energy + round(standing * billed_days(draft) / 100, 2)) * 1.05, 2)
    return draft.model_copy(update={"total_gbp": total})


FAULTS = ("bad_check_digit", "usage_digits_swapped", "total_off", "dates_reversed")


def plant_fault(bill: Bill, fault: str, rng: random.Random) -> Bill:
    """The same bill with one known error printed on it."""
    if fault == "bad_check_digit":
        last = (int(bill.mpan_core[-1]) + rng.randint(1, 9)) % 10  # any other digit
        return bill.model_copy(update={"mpan_core": bill.mpan_core[:-1] + str(last)})
    if fault == "usage_digits_swapped":
        digits = str(int(bill.usage_kwh))
        swapped = digits[1] + digits[0] + digits[2:]
        if swapped == digits:  # e.g. 1100: swapping changes nothing
            swapped = str(int(digits) + 100)
        return bill.model_copy(update={"usage_kwh": int(swapped)})
    if fault == "total_off":
        return bill.model_copy(update={"total_gbp": round(bill.total_gbp + rng.uniform(3, 30), 2)})
    if fault == "dates_reversed":
        return bill.model_copy(update={"period_start": bill.period_end, "period_end": bill.period_start})
    raise ValueError(f"unknown fault: {fault}")


FONTS = Path(__file__).resolve().parents[2] / "fonts"  # DejaVu Sans, shipped in the repo (has the £ sign)


def font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(str(FONTS / ("DejaVuSans-Bold.ttf" if bold else "DejaVuSans.ttf")), size)


def fmt_mpan(core: str) -> str:
    """Print the core the way bills group it: 19 0000 0000 013."""
    return f"{core[:2]} {core[2:6]} {core[6:10]} {core[10:]}"


def draw_rows(draw: ImageDraw.ImageDraw, x: int, y: int, rows: list[tuple[str, str]],
              size: int = 22, gap: int = 40, value_x: int = 380) -> int:
    """Draw label/value rows from (x, y); return the y below the last row."""
    for label, value in rows:
        draw.text((x, y), label, fill="#333", font=font(size))
        draw.text((x + value_x, y), value, fill="black", font=font(size))
        y += gap
    return y


def layout_a(bill: Bill) -> Image.Image:
    """Classic statement: header bar, account box, one table. Dates as 01/09/2026, rates in pence."""
    img = Image.new("RGB", (1240, 1754), "white")  # A4 at 150 dpi
    d = ImageDraw.Draw(img)
    d.rectangle((0, 0, 1240, 140), fill="#1f4e79")
    d.text((60, 45), bill.supplier, fill="white", font=font(44))
    d.text((60, 190), "Your electricity bill", font=font(34), fill="black")
    draw_rows(d, 760, 190, [("Account", bill.account_number)], size=22, value_x=140)
    rows = [
        ("Supply number (MPAN)", fmt_mpan(bill.mpan_core)),
        ("Billing period", f"{bill.period_start:%d/%m/%Y} to {bill.period_end:%d/%m/%Y}"),
        ("Electricity used", f"{bill.usage_kwh:g} kWh"),
        ("Unit rate", f"{bill.unit_rate_p_per_kwh:.2f}p per kWh"),
        ("Energy charge", f"£{bill.energy_charge_gbp:,.2f}"),
        ("Standing charge", f"{bill.standing_charge_p_per_day:.2f}p per day"),
        ("Total including VAT at 5%", f"£{bill.total_gbp:,.2f}"),
    ]
    draw_rows(d, 60, 320, rows)
    return img


def layout_b(bill: Bill) -> Image.Image:
    """Amount due shown big at the top, two columns, dates as '1 Jun 2026', MPAN without spaces."""
    img = Image.new("RGB", (1240, 1754), "white")
    d = ImageDraw.Draw(img)
    d.text((60, 50), bill.supplier.upper(), fill="#0b7a5c", font=font(40, bold=True))
    d.rounded_rectangle((60, 150, 1180, 320), radius=18, fill="#e8f5f0")
    d.text((100, 180), "Amount due", fill="#333", font=font(26))
    d.text((100, 225), f"£{bill.total_gbp:,.2f}", fill="black", font=font(56, bold=True))
    left = [("Account no.", bill.account_number),
            ("MPAN", bill.mpan_core),
            ("From", f"{bill.period_start:%-d %b %Y}"),
            ("To", f"{bill.period_end:%-d %b %Y}")]
    right = [("kWh used", f"{bill.usage_kwh:g}"),
             ("Price", f"{bill.unit_rate_p_per_kwh:.2f} p/kWh"),
             ("Energy", f"£{bill.energy_charge_gbp:,.2f}"),
             ("Daily charge", f"{bill.standing_charge_p_per_day:.2f} p/day")]
    draw_rows(d, 60, 380, left, value_x=200)
    draw_rows(d, 640, 380, right, value_x=220)
    d.text((60, 600), "Amount due includes VAT at 5%.", fill="#555", font=font(20))
    return img


FILLER = ["Prices are fixed until the end of your tariff. You can switch at any time without exit fees.",
          "Meter readings marked E are estimates. Send a reading in the app to keep your bill accurate.",
          "If you are struggling to pay, contact us. We can set up a payment plan that works for you."]


def layout_c(bill: Bill) -> Image.Image:
    """Dense statement with traps: rates in POUNDS, ISO dates, and a previous-bill total nearby."""
    img = Image.new("RGB", (1240, 1754), "white")
    d = ImageDraw.Draw(img)
    d.text((60, 40), f"{bill.supplier} | Electricity statement", fill="black", font=font(30, bold=True))
    d.text((60, 100), f"Ref {bill.account_number}    Supply {fmt_mpan(bill.mpan_core)}", fill="#222", font=font(20))
    rows = [("Period", f"{bill.period_start:%Y-%m-%d} - {bill.period_end:%Y-%m-%d}"),
            ("Consumption", f"{bill.usage_kwh:g} kWh @ £{bill.unit_rate_p_per_kwh / 100:.4f} per kWh"),
            ("Consumption charge", f"£{bill.energy_charge_gbp:,.2f}"),
            ("Standing charge", f"£{bill.standing_charge_p_per_day / 100:.4f} per day"),
            ("Your last bill", f"£{round(bill.total_gbp * 0.83, 2):,.2f}"),  # distractor
            ("Total this period (incl. VAT 5%)", f"£{bill.total_gbp:,.2f}")]
    draw_rows(d, 60, 170, rows, size=19, gap=32, value_x=420)
    for i, line in enumerate(FILLER):  # small print to read past
        d.text((60, 420 + i * 26), line, fill="#666", font=font(16))
    return img


LAYOUTS = {"a": layout_a, "b": layout_b, "c": layout_c}


DAMAGE = ("clean", "clean", "faded", "blurred", "tilted")  # about 40% clean, the rest one kind of damage each


def damage(img: Image.Image, kind: str, rng: random.Random) -> Image.Image:
    """Make the image look like a poor phone photo or scan."""
    if kind == "clean":
        return img
    if kind == "faded":
        return ImageEnhance.Contrast(img).enhance(0.35)
    if kind == "blurred":
        return img.filter(ImageFilter.GaussianBlur(radius=1.8))
    if kind == "tilted":
        return img.rotate(rng.uniform(-4, 4), expand=True, fillcolor="white")
    raise ValueError(f"unknown damage: {kind}")


def build_dataset(out: Path, per_layout: int = 20, fault_share: float = 0.25, seed: int = 7) -> None:
    """Write bills/<id>.png and bills/<id>.json with the printed values and which checks should fire."""
    rng = random.Random(seed)
    out.mkdir(parents=True, exist_ok=True)
    for (key, draw), supplier in zip(LAYOUTS.items(), SUPPLIERS):
        for i in range(per_layout):
            bill = make_bill(rng, supplier)
            fault = rng.choice(FAULTS) if rng.random() < fault_share else None
            if fault:
                bill = plant_fault(bill, fault, rng)
            kind = rng.choice(DAMAGE)
            bill_id = f"{key}{i:02d}"
            damage(draw(bill), kind, rng).save(out / f"{bill_id}.png")
            record = {"id": bill_id, "layout": key, "fault": fault, "damage": kind,
                      "truth": bill.model_dump(mode="json"), "expected_flags": check_bill(bill)}
            (out / f"{bill_id}.json").write_text(json.dumps(record, indent=2))


# Harder tier: every bill a bad phone photo, half with one value under a stain.
# Only fields printed once on every layout, so the stain covers one value, not half the page.
COVERABLE = ("usage_kwh", "unit_rate_p_per_kwh", "standing_charge_p_per_day", "mpan_core")
COVER_ALT = {"usage_kwh": lambda v: v + 111, "unit_rate_p_per_kwh": lambda v: v + 1.11,
             "standing_charge_p_per_day": lambda v: v + 1.11, "mpan_core": lambda v: "1" * 13}


def field_box(draw, bill: Bill, field: str) -> tuple[int, int, int, int]:
    """Where a field is printed: draw the bill twice with that field changed, and diff the images."""
    changed = bill.model_copy(update={field: COVER_ALT[field](getattr(bill, field))})
    return ImageChops.difference(draw(bill), draw(changed)).getbbox()


def cover(img: Image.Image, box: tuple[int, int, int, int], rng: random.Random) -> Image.Image:
    """Paint an opaque brown stain a little larger than the box, so the value cannot be read."""
    x0, y0, x1, y1 = box
    pad = rng.randint(8, 16)
    ImageDraw.Draw(img).ellipse((x0 - pad, y0 - pad, x1 + pad, y1 + pad), fill="#8b6a4f")
    return img


def harsh(img: Image.Image, rng: random.Random) -> Image.Image:
    """A bad phone photo: faded, blurred, tilted up to 8 degrees and saved as low-quality JPEG."""
    img = ImageEnhance.Contrast(img).enhance(0.25).filter(ImageFilter.GaussianBlur(2.2))
    img = img.rotate(rng.uniform(-8, 8), expand=True, fillcolor="white")
    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=25)
    return Image.open(buf).convert("RGB")


def build_hard_dataset(out: Path, per_layout: int = 10, seed: int = 11) -> None:
    """Like build_dataset, but no planted faults: this tier tests reading, and 'never guess'."""
    rng = random.Random(seed)
    out.mkdir(parents=True, exist_ok=True)
    for (key, draw), supplier in zip(LAYOUTS.items(), SUPPLIERS):
        for i in range(per_layout):
            bill = make_bill(rng, supplier)
            img, covered = draw(bill), None
            if i % 2:  # every other bill gets a stain
                field = rng.choice(COVERABLE)
                img = cover(img, field_box(draw, bill, field), rng)
                covered = {"field": field, "value": getattr(bill, field)}
                bill = bill.model_copy(update={field: None})  # not readable, so the right answer is null
            bill_id = f"h{key}{i:02d}"
            harsh(img, rng).save(out / f"{bill_id}.png")
            record = {"id": bill_id, "layout": key, "fault": None, "damage": "harsh", "covered": covered,
                      "truth": bill.model_dump(mode="json"), "expected_flags": check_bill(bill)}
            (out / f"{bill_id}.json").write_text(json.dumps(record, indent=2))


if __name__ == "__main__":
    build_dataset(Path("bills"))
    build_hard_dataset(Path("bills_hard"))
