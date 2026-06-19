import re
import time

from deep_translator import GoogleTranslator
from deep_translator.exceptions import RequestError, TranslationNotFound

MAX_PARCA = 4500
CEVIRI_DENEME = 3
CEVIRI_BEKLEME_SN = 1.5
PARCA_ARASI_BEKLEME_SN = 3
CEVIRI_PARCA_BEKLEME_SN = 3

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

    if metin_turkce_mi(metin):
        return metin

    cevirici = GoogleTranslator(source="auto", target="tr")
    cevrilmis = []

    parcalar = _metin_parcala(metin)
    for parca_no, parca in enumerate(parcalar):
        if parca_no > 0:
            time.sleep(CEVIRI_PARCA_BEKLEME_SN)

        son_hata = None
        for deneme in range(1, CEVIRI_DENEME + 1):
            try:
                cevrilmis.append(cevirici.translate(parca))
                son_hata = None
                break
            except (RequestError, TranslationNotFound, Exception) as e:
                son_hata = e
                if deneme < CEVIRI_DENEME:
                    time.sleep(CEVIRI_BEKLEME_SN * deneme)
        if son_hata is not None:
            raise son_hata

    return "\n".join(cevrilmis)
