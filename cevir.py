import re
import time
from concurrent.futures import ThreadPoolExecutor

from deep_translator import GoogleTranslator
from deep_translator.exceptions import RequestError, TranslationNotFound

MAX_PARCA = 3500
CEVIRI_DENEME = 4
CEVIRI_TAM_TUR = 2
CEVIRI_BEKLEME_SN = 2
PARCA_ARASI_BEKLEME_SN = 0.4
# Google Translate'in ücretsiz ucunda IP bazlı hız sınırlamasına takılmamak için
# çeviri isteklerini sırayla gönder.
PARCA_PARALEL_ISCI = 1

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
        return True

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
    parcalar = _metin_parcala(metin)
    if not parcalar:
        return ""

    if len(parcalar) == 1:
        cevirici = GoogleTranslator(source=kaynak, target="tr")
        return _parca_cevir(cevirici, parcalar[0])

    def _parca_isle(idx_parca: tuple[int, str]) -> tuple[int, str]:
        idx, parca = idx_parca
        if idx > 0 and PARCA_ARASI_BEKLEME_SN:
            time.sleep(PARCA_ARASI_BEKLEME_SN * idx)
        cevirici = GoogleTranslator(source=kaynak, target="tr")
        return idx, _parca_cevir(cevirici, parca)

    isci = min(PARCA_PARALEL_ISCI, len(parcalar))
    with ThreadPoolExecutor(max_workers=isci) as havuz:
        sonuclar = list(havuz.map(_parca_isle, enumerate(parcalar)))

    sonuclar.sort(key=lambda x: x[0])
    return "\n".join(metin for _, metin in sonuclar)


def metinleri_turkceye_cevir(*metinler: str) -> list[str]:
    """Birden fazla metni paralel cevirir."""
    if not metinler:
        return []

    def _cevir(metin: str) -> str:
        return metni_turkceye_cevir(metin) if metin.strip() else ""

    isci = min(PARCA_PARALEL_ISCI, max(1, sum(1 for m in metinler if m.strip())))
    with ThreadPoolExecutor(max_workers=isci) as havuz:
        return list(havuz.map(_cevir, metinler))


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
            if sonuc and sonuc.strip():
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
