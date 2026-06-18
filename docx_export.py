import re
from pathlib import Path

from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH

HARIC_TUTULACAKLAR = [
    r"^Resmi dil\s*\(",
    r"^Pdf",
    r"^İmzalı pdf",
    r"^Makine çevirisi",
    r"^BG$|^CS$|^DA$|^DE$|^EL$|^ES$|^EN$|^ET$|^FI$|^FR$",
    r"^GA$|^HR$|^HU$|^IT$|^LT$|^LV$|^MT$|^NL$|^PL$|^PT$|^RO$|^SK$|^SL$|^SV$",
    r"^eTranslation",
    r"^Avrupa Komisyonu doğruluğu",
]


def _normalize_satir(satir: str) -> str:
    satir = re.sub(r"\s*:\s*", ":", satir.strip())
    satir = re.sub(r"\s+", " ", satir)
    return satir


def _haric_mi(satir: str) -> bool:
    if not satir.strip():
        return True
    if satir.strip() in {"=== ÖZET ===", "=== İLAN ==="}:
        return True
    if re.fullmatch(r"\d+\.\d*\.?", satir.strip()):
        return True
    for pattern in HARIC_TUTULACAKLAR:
        if re.search(pattern, satir.strip(), re.IGNORECASE):
            return True
    return False


def _alan_bul(pattern: str, metin: str, default: str = "") -> str:
    match = re.search(pattern, metin, re.IGNORECASE | re.MULTILINE)
    return match.group(1).strip() if match else default


def _ulke_bul(summary: str, notice: str) -> str:
    for kaynak in (summary, notice):
        match = re.search(
            r"^([\wğüşıöçĞÜŞİÖÇ]+)\s*[:\–-]\s*",
            kaynak,
            re.MULTILINE | re.IGNORECASE,
        )
        if match:
            return match.group(1).strip().upper()
        match = re.search(r"Ülke\s*:\s*(.+)", kaynak, re.IGNORECASE)
        if match:
            return match.group(1).strip().upper()
    return "BİLİNMEYEN"


def _form_turu_bul(summary: str, notice: str) -> str:
    form = _alan_bul(r"Form türü\s*:\s*(.+)", notice)
    if form:
        return form.upper()
    ilk = summary.splitlines()[0].strip() if summary else ""
    if ilk:
        return ilk.upper()
    return "İLAN"


def _ozet_satirlari(summary: str, form_turu: str) -> list[str]:
    satirlar = []
    for ham in summary.splitlines():
        satir = _normalize_satir(ham)
        if _haric_mi(satir):
            continue
        if satir.upper() == form_turu.upper():
            continue
        if re.fullmatch(r"\d+\.\s+[^:\.]+", satir):
            continue
        satirlar.append(satir)
    return satirlar


def _org_ve_bildirim_satirlari(notice: str) -> list[str]:
    degisim_satirlari = []
    bildirim_satirlari = []
    org_satirlari = []
    mod = None

    for ham in notice.splitlines():
        satir = _normalize_satir(ham)
        if not satir:
            continue

        if satir.startswith("10. Change") or satir.startswith("10. Değiştirmek"):
            mod = "degisim"
            degisim_satirlari.append(satir)
            continue
        if satir.startswith("Bildirim bilgileri"):
            mod = "bildirim"
            bildirim_satirlari.append(satir)
            continue
        if satir.startswith("ORG-"):
            mod = "org"
            org_satirlari.append(satir)
            continue
        if re.fullmatch(r"8\.\s*Kuruluşlar", satir):
            mod = "org"
            continue

        if mod == "degisim" and not satir.startswith(("8.", "Bildirim")):
            if not _haric_mi(satir) and not re.fullmatch(r"\d+\.\s+[^:\.]+", satir):
                degisim_satirlari.append(satir)
            continue

        if mod == "org":
            if satir.startswith("Bildirim bilgileri"):
                mod = "bildirim"
                bildirim_satirlari.append(satir)
                continue
            if _haric_mi(satir) or re.fullmatch(r"8\.1\.", satir):
                continue
            org_satirlari.append(satir)
            continue

        if mod == "bildirim":
            if not _haric_mi(satir):
                bildirim_satirlari.append(satir)

    sonuc = []
    if org_satirlari:
        sonuc.append("Resmi dil (İmzalı PDF)")
        sonuc.extend(org_satirlari)
    if degisim_satirlari:
        sonuc.extend(degisim_satirlari)
    if bildirim_satirlari:
        sonuc.extend(bildirim_satirlari)
    return sonuc


def _cpv_tablosu(summary: str, notice: str) -> list[tuple[str, str, str, str]]:
    metin = f"{summary}\n{notice}"
    bulunan = []
    gorulen = set()

    for kod, aciklama in re.findall(
        r"(?:cpv\)|CPV\)|sınıflandırma\s*\(\s*cpv\s*\))\s*:\s*(\d{8})\s+(.+)",
        metin,
        re.IGNORECASE,
    ):
        anahtar = (kod, aciklama.strip())
        if anahtar in gorulen:
            continue
        gorulen.add(anahtar)
        bulunan.append((str(len(bulunan) + 1), f"{kod} {aciklama.strip()}", aciklama.strip(), ""))

    if not bulunan:
        for kod, aciklama in re.findall(r"(\d{8})\s+([A-Za-zğüşıöçĞÜŞİÖÇ][^\n]{2,80})", metin):
            anahtar = (kod, aciklama.strip())
            if anahtar in gorulen:
                continue
            gorulen.add(anahtar)
            bulunan.append((str(len(bulunan) + 1), f"{kod} {aciklama.strip()}", aciklama.strip(), ""))

    return bulunan[:10]


def docx_olustur(
    summary: str,
    notice: str,
    ilan_no: str,
    url: str,
    cikti_yolu: Path,
) -> Path:
    ulke = _ulke_bul(summary, notice)
    form_turu = _form_turu_bul(summary, notice)

    govde_satirlari = _ozet_satirlari(summary, form_turu)
    govde_satirlari.extend(_org_ve_bildirim_satirlari(notice))
    if url:
        govde_satirlari.append(url)

    tablo_satirlari = _cpv_tablosu(summary, notice)

    doc = Document()
    baslik1 = doc.add_paragraph(f"YURT DIŞINDAN SATINALMA TALEBİ/ {ulke}")
    baslik1.alignment = WD_ALIGN_PARAGRAPH.CENTER
    baslik2 = doc.add_paragraph(form_turu)
    baslik2.alignment = WD_ALIGN_PARAGRAPH.CENTER

    for satir in govde_satirlari:
        doc.add_paragraph(satir)

    if tablo_satirlari:
        tablo = doc.add_table(rows=1 + len(tablo_satirlari), cols=4)
        baslik_hucreleri = ["Sıra No", "Cinsi", "Miktarı", "Birim"]
        for i, baslik in enumerate(baslik_hucreleri):
            tablo.rows[0].cells[i].text = baslik
        for row_idx, row_data in enumerate(tablo_satirlari, start=1):
            for col_idx, deger in enumerate(row_data):
                tablo.rows[row_idx].cells[col_idx].text = deger

    doc.save(str(cikti_yolu))
    return cikti_yolu
