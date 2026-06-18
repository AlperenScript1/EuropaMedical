import re
import time

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


def _metin_parcala(metin: str, max_uzunluk: int = MAX_PARCA) -> list[str]:
    parcalar = []
    mevcut = ""

    for satir in metin.splitlines():
        if len(satir) > max_uzunluk:
            if mevcut:
                parcalar.append(mevcut)
                mevcut = ""
            for baslangic in range(0, len(satir), max_uzunluk):
                parcalar.append(satir[baslangic : baslangic + max_uzunluk])
            continue

        eklenecek = satir if not mevcut else f"\n{satir}"
        if len(mevcut) + len(eklenecek) > max_uzunluk:
            parcalar.append(mevcut)
            mevcut = satir
        else:
            mevcut += eklenecek

    if mevcut:
        parcalar.append(mevcut)

    return parcalar


def metni_turkceye_cevir(metin: str) -> str:
    metin = (metin or "").strip()
    if not metin:
        return metin

    cevirici = GoogleTranslator(source="auto", target="tr")
    cevrilmis = []

    for parca in _metin_parcala(metin):
        cevrilmis.append(cevirici.translate(parca))
        time.sleep(0.2)

    return "\n".join(cevrilmis)
