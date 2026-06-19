import re
from pathlib import Path

from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.shared import Pt, RGBColor

FONT_ADI = "Times New Roman"
FONT_BOYUT = Pt(12)

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

FORM_TURLERI = {
    "SONUÇ",
    "REKABET",
    "KONKUR",
    "İLAN",
    "COMPETITION",
    "RESULT",
    "CONTRACT",
    "CONTRACT NOTICE",
    "CONTRACT AWARD",
}

REKABET_FORM_TURLERI = {"REKABET", "KONKUR", "COMPETITION", "CONTRACT NOTICE", "İLAN"}

KALIN_TARIH_ETIKETLERI = [
    "Son teklif tarihi",
    "Son başvuru tarihi",
    "Tekliflerin son teslim tarihi",
    "Sözleşmenin imzalanma tarihi",
    "Bildirimin gönderilme tarihi",
    "Yayınlanma tarihi",
    "Son tarih",
]

TARIH_KALIN_PARCA = re.compile(
    r"\d{2}/\d{2}/\d{4}|\d{2}:\d{2}(?::\d{2})?|\+\d{2}:\d{2}"
)


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


def _tr_kucuk(metin: str) -> str:
    return metin.replace("I", "ı").replace("İ", "i").lower()


def _tr_baslik_kelime(kelime: str) -> str:
    kelime = _tr_kucuk(kelime)
    if not kelime:
        return kelime
    ilk = kelime[0]
    if ilk == "i":
        ilk = "İ"
    elif ilk == "ı":
        ilk = "I"
    else:
        ilk = ilk.upper()
    return ilk + kelime[1:]


def _bas_harf_buyuk(metin: str) -> str:
    return " ".join(_tr_baslik_kelime(kelime) for kelime in metin.split())


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


def _ihale_basligi_bul(summary: str, notice: str) -> str:
    metin = f"{summary}\n{notice}"
    lot = _alan_bul(r"LOT-0001\s*:\s*(.+)", metin)
    if lot:
        return _bas_harf_buyuk(lot)

    for ham in summary.splitlines():
        satir = _normalize_satir(ham)
        if not satir or _haric_mi(satir):
            continue
        if re.match(r"^[\wğüşıöçĞÜŞİÖÇ]+\s*[:\–-]\s*", satir):
            continue
        if re.fullmatch(r"\d+\.\s+[^:\.]+", satir):
            continue
        if len(satir) >= 15:
            return _bas_harf_buyuk(satir)

    return ""


def _alt_baslik_metni(form_turu: str, ihale_basligi: str) -> str:
    """Form türü (REKABET, SONUÇ vb.) yerine gerçek ihale adını göster."""
    if not ihale_basligi:
        return ""
    form = form_turu.upper().strip()
    if form in FORM_TURLERI:
        if any(rekabet in form for rekabet in REKABET_FORM_TURLERI):
            return ihale_basligi
        return ""
    return ihale_basligi


def _ozet_satirlari(summary: str, form_turu: str, ihale_basligi: str) -> list[str]:
    satirlar = []
    for ham in summary.splitlines():
        satir = _normalize_satir(ham)
        if _haric_mi(satir):
            continue
        if satir.upper() == form_turu.upper():
            continue
        if ihale_basligi and satir.upper() == ihale_basligi.upper():
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


def _tablo_satirlari(summary: str, notice: str, ihale_basligi: str) -> list[tuple[str, str, str, str]]:
    if ihale_basligi:
        return [("1", ihale_basligi, "", "")]

    metin = f"{summary}\n{notice}"
    for kod, aciklama in re.findall(
        r"(?:cpv\)|CPV\)|sınıflandırma\s*\(\s*cpv\s*\))\s*:\s*(\d{8})\s+(.+)",
        metin,
        re.IGNORECASE,
    ):
        return [("1", _bas_harf_buyuk(aciklama.strip()), "", "")]

    return []


def _varsayilan_yazi_tipi_ayarla(doc: Document):
    normal = doc.styles["Normal"]
    normal.font.name = FONT_ADI
    normal.font.size = FONT_BOYUT
    normal.font.color.rgb = RGBColor(0, 0, 0)


def _run_ekle(paragraf, metin: str, kalin: bool = False):
    run = paragraf.add_run(metin)
    run.font.name = FONT_ADI
    run.font.size = FONT_BOYUT
    run.font.bold = kalin
    run.font.color.rgb = RGBColor(0, 0, 0)
    return run


def _tarih_degeri_parcala(deger: str) -> list[tuple[str, bool]]:
    parcalar: list[tuple[str, bool]] = []
    son = 0
    for match in TARIH_KALIN_PARCA.finditer(deger):
        if match.start() > son:
            parcalar.append((deger[son : match.start()], False))
        parcalar.append((match.group(0), True))
        son = match.end()
    if son < len(deger):
        parcalar.append((deger[son:], False))
    return parcalar or [(deger, True)]


def _kalin_etiket_mi(etiket: str) -> bool:
    etiket = etiket.strip()
    return any(
        etiket.lower() == t.lower() or etiket.lower().startswith(t.lower())
        for t in KALIN_TARIH_ETIKETLERI
    )


def _paragraf_ekle(doc: Document, satir: str, ortala: bool = False):
    paragraf = doc.add_paragraph()
    paragraf.style = doc.styles["Normal"]
    if ortala:
        paragraf.alignment = WD_ALIGN_PARAGRAPH.CENTER

    if ":" in satir:
        etiket, deger = satir.split(":", 1)
        etiket = etiket.strip()
        deger = deger.strip()
        _run_ekle(paragraf, f"{etiket}:")
        if _kalin_etiket_mi(etiket):
            for parca, kalin in _tarih_degeri_parcala(deger):
                _run_ekle(paragraf, parca, kalin=kalin)
        else:
            _run_ekle(paragraf, deger)
    else:
        _run_ekle(paragraf, satir)

    return paragraf


def _hucre_yaz(hucre, metin: str):
    hucre.text = ""
    paragraf = hucre.paragraphs[0]
    run = paragraf.add_run(metin)
    run.font.name = FONT_ADI
    run.font.size = FONT_BOYUT
    run.font.color.rgb = RGBColor(0, 0, 0)


def docx_olustur(
    summary: str,
    notice: str,
    ilan_no: str,
    url: str,
    cikti_yolu: Path,
) -> Path:
    ulke = _ulke_bul(summary, notice)
    form_turu = _form_turu_bul(summary, notice)
    ihale_basligi = _ihale_basligi_bul(summary, notice)
    alt_baslik = _alt_baslik_metni(form_turu, ihale_basligi)

    govde_satirlari = _ozet_satirlari(summary, form_turu, ihale_basligi)
    govde_satirlari.extend(_org_ve_bildirim_satirlari(notice))
    if url:
        govde_satirlari.append(url)

    tablo_satirlari = _tablo_satirlari(summary, notice, ihale_basligi)

    doc = Document()
    _varsayilan_yazi_tipi_ayarla(doc)

    _paragraf_ekle(doc, f"YURT DIŞINDAN SATINALMA TALEBİ/ {ulke}", ortala=True)
    doc.add_paragraph()

    if alt_baslik:
        _paragraf_ekle(doc, alt_baslik, ortala=True)
        doc.add_paragraph()

    for satir in govde_satirlari:
        _paragraf_ekle(doc, satir)

    if tablo_satirlari:
        tablo = doc.add_table(rows=1 + len(tablo_satirlari), cols=4)
        baslik_hucreleri = ["Sıra No", "Cinsi", "Miktarı", "Birim"]
        for i, baslik in enumerate(baslik_hucreleri):
            _hucre_yaz(tablo.rows[0].cells[i], baslik)
        for row_idx, row_data in enumerate(tablo_satirlari, start=1):
            for col_idx, deger in enumerate(row_data):
                _hucre_yaz(tablo.rows[row_idx].cells[col_idx], deger)

    doc.save(str(cikti_yolu))
    return cikti_yolu
