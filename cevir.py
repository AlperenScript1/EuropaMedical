import re
import time

from deep_translator import GoogleTranslator
from deep_translator.exceptions import RequestError, TranslationNotFound

MAX_PARCA = 2200
CEVIRI_DENEME = 5
CEVIRI_TAM_TUR = 3
CEVIRI_BEKLEME_SN = 3
PARCA_ARASI_BEKLEME_SN = 5

CUMLE_AYIRICI = re.compile(r"(?<=[.!?;])\s+")

TURKCE_ISARETLER = [
    "Alıcı", "Sonuç", "Tedarik", "Başlık", "E-posta", "Süre", "İhale",
    "Kazanan", "Değer", "Açıklama", "Bildirim", "Resmi adı", "KDV",
    "hariç", "tahmini", "İşlem", "Sözleşme", "Ülke", "Yayınlanma",
    "Son teklif", "Miktar", "Form türü",
]
INGILIZCE_ISARETLER = [
    "Buyer", "Result", "Supplies", "Estimated value", "Type of procedure",
    "Winner", "Description", "Notice information", "Official name",
    "Contract", "Publication", "Deadline", "Country", "Procedure",
    "Lot-", "CPV", "Estimated total",
]
KIRIL_PATTERN = re.compile(r"[а-яА-ЯёЁ]")


class CeviriBasarisizError(Exception):
    """Metin yeterince Türkçe'ye çevrilemedi."""


def metin_turkce_mi(metin: str) -> bool:
    """Metnin TED ilanı için yeterince Türkçe olup olmadığını kontrol eder."""
    metin = metin or ""
    if not metin.strip():
        return True

    kiril_say = len(KIRIL_PATTERN.findall(metin))
    if kiril_say >= 8:
        return False

    tr_say = sum(1 for k in TURKCE_ISARETLER if k in metin)
    en_say = sum(1 for k in INGILIZCE_ISARETLER if k in metin)
    has_tr_chars = bool(re.search(r"[ğüşıöçĞÜŞİÖÇ]", metin))

    if has_tr_chars:
        if en_say >= 2 and en_say > tr_say:
            return False
        return tr_say >= 1

    if kiril_say > 0:
        return False

    return tr_say >= 3 and tr_say > en_say


def _kaynak_dil(metin: str) -> str:
    """Rusça (Kiril) metinlerde kaynak dili açıkça belirt."""
    kiril = len(KIRIL_PATTERN.findall(metin))
    latin = len(re.findall(r"[a-zA-Z]", metin))
    if kiril >= 15 and kiril >= latin * 0.15:
        return "ru"
    return "auto"


def _uzun_blok_bol(blok: str, max_uzunluk: int) -> list[str]:
    """Tek bloğu cümle, kelime ve son çare karakter sınırında parçalar."""
    if len(blok) <= max_uzunluk:
        return [blok]

    parcalar: list[str] = []
    cumleler = CUMLE_AYIRICI.split(blok)
    if len(cumleler) == 1:
        mevcut = ""
        for kelime in blok.split():
            ek = kelime if not mevcut else f" {kelime}"
            if len(mevcut) + len(ek) > max_uzunluk:
                if mevcut:
                    parcalar.append(mevcut)
                if len(kelime) > max_uzunluk:
                    for baslangic in range(0, len(kelime), max_uzunluk):
                        parcalar.append(kelime[baslangic : baslangic + max_uzunluk])
                    mevcut = ""
                else:
                    mevcut = kelime
            else:
                mevcut += ek
        if mevcut:
            parcalar.append(mevcut)
        return parcalar

    mevcut = ""
    for cumle in cumleler:
        if len(cumle) > max_uzunluk:
            if mevcut:
                parcalar.append(mevcut)
                mevcut = ""
            parcalar.extend(_uzun_blok_bol(cumle, max_uzunluk))
            continue

        ek = cumle if not mevcut else f" {cumle}"
        if len(mevcut) + len(ek) > max_uzunluk:
            parcalar.append(mevcut)
            mevcut = cumle
        else:
            mevcut += ek

    if mevcut:
        parcalar.append(mevcut)
    return parcalar


def _metin_parcala(metin: str, max_uzunluk: int = MAX_PARCA) -> list[str]:
    segmentler: list[str] = []
    for satir in metin.splitlines():
        if len(satir) <= max_uzunluk:
            segmentler.append(satir)
        else:
            segmentler.extend(_uzun_blok_bol(satir, max_uzunluk))

    parcalar: list[str] = []
    mevcut = ""
    for segment in segmentler:
        eklenecek = segment if not mevcut else f"\n{segment}"
        if len(mevcut) + len(eklenecek) > max_uzunluk:
            parcalar.append(mevcut)
            mevcut = segment
        else:
            mevcut += eklenecek

    if mevcut:
        parcalar.append(mevcut)

    return parcalar


def _parca_cevir(cevirici: GoogleTranslator, parca: str) -> str:
    son_hata: Exception | None = None
    for deneme in range(1, CEVIRI_DENEME + 1):
        try:
            sonuc = cevirici.translate(parca)
            if sonuc and sonuc.strip():
                return sonuc
            son_hata = CeviriBasarisizError("Boş çeviri sonucu")
        except (RequestError, TranslationNotFound, Exception) as e:
            son_hata = e
        if deneme < CEVIRI_DENEME:
            time.sleep(CEVIRI_BEKLEME_SN * deneme)
    raise CeviriBasarisizError(str(son_hata or "Parça çevrilemedi"))


def _ham_metni_cevir(metin: str) -> str:
    kaynak = _kaynak_dil(metin)
    cevirici = GoogleTranslator(source=kaynak, target="tr")
    cevrilmis: list[str] = []

    parcalar = _metin_parcala(metin)
    for parca_no, parca in enumerate(parcalar):
        if parca_no > 0:
            time.sleep(PARCA_ARASI_BEKLEME_SN)
        cevrilmis.append(_parca_cevir(cevirici, parca))

    return "\n".join(cevrilmis)


def metni_turkceye_cevir(metin: str) -> str:
    metin = (metin or "").strip()
    if not metin:
        return metin

    if metin_turkce_mi(metin):
        return metin

    son_hata: Exception | None = None
    for tur in range(1, CEVIRI_TAM_TUR + 1):
        try:
            sonuc = _ham_metni_cevir(metin)
            if metin_turkce_mi(sonuc):
                return sonuc
            son_hata = CeviriBasarisizError(
                f"Çeviri sonrası Türkçe kontrolü geçmedi (deneme {tur}/{CEVIRI_TAM_TUR})"
            )
        except CeviriBasarisizError as e:
            son_hata = e
        except Exception as e:
            son_hata = CeviriBasarisizError(str(e))

        if tur < CEVIRI_TAM_TUR:
            time.sleep(CEVIRI_BEKLEME_SN * tur * 2)

    raise CeviriBasarisizError(
        str(son_hata or "Metin Türkçe'ye çevrilemedi")
    )
