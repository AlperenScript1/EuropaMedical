import re

from deep_translator import GoogleTranslator

MAX_PARCA = 4500

TURKCE_ISARETLER = [
    "Alıcı", "Sonuç", "Tedarik", "Başlık", "E-posta", "Süre", "İhale",
    "Kazanan", "Değer", "Açıklama", "Bildirim", "Resmi adı", "KDV",
    "hariç", "tahmini", "İşlem", "Sözleşme",
]
INGILIZCE_ISARETLER = [
    "Buyer", "Result", "Supplies", "Estimated value", "Type of procedure",
    "Winner", "Description", "Notice information", "Official name",
]


def metin_turkce_mi(metin: str) -> bool:
    metin = metin or ""
    if re.search(r"[ğüşıöçĞÜŞİÖÇ]", metin):
        return True
    tr_say = sum(1 for k in TURKCE_ISARETLER if k in metin)
    en_say = sum(1 for k in INGILIZCE_ISARETLER if k in metin)
    return tr_say >= 2 and tr_say > en_say


def metni_turkceye_cevir(metin: str) -> str:
    metin = (metin or "").strip()
    if not metin:
        return metin

    cevirici = GoogleTranslator(source="auto", target="tr")
    parcalar = []
    mevcut = ""

    for satir in metin.splitlines():
        eklenecek = satir if not mevcut else f"\n{satir}"
        if len(mevcut) + len(eklenecek) > MAX_PARCA:
            parcalar.append(cevirici.translate(mevcut))
            mevcut = satir
        else:
            mevcut += eklenecek

    if mevcut:
        parcalar.append(cevirici.translate(mevcut))

    return "\n".join(parcalar)
