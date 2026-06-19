"""
Word Makro1 (Ctrl+1) temizlik kurallarinin Python karsiligi.
TED Europa Word ciktisi kaydedilmeden once metne uygulanir.
"""
import re

# Makro1 + Makro15 ozel karakter haritasi
_KARAKTER_DEGISIMLERI: dict[str, str] = {
    "µ": "u",
    "à": "a", "á": "a", "â": "a", "ã": "a", "ä": "a", "å": "a",
    "è": "e", "é": "e", "ê": "e", "ë": "e",
    "ì": "i", "í": "i", "î": "i", "ï": "i",
    "ò": "o", "ó": "o", "ô": "o", "õ": "o",
    "ù": "u", "ú": "u", "û": "u",
    "×": "x", "±": "+-", "Ø": "", "²": "2", "³": "3", "¹": "1",
    "®": "", "™": "", "©": "", "º": "",
    "¼": "1/4", "½": "1/2", "¾": "3/4",
    "~": "", "^": "",
    "«": " ", "»": " ", "ƒ": "f", "<": " ", ">": " ", "#": " ",
    "ß": "b", "ñ": "n",
    "\u221e": " ",
    "\u2265": "", "\u2264": "",
    "\u03b1": "a",
    # Avrupa dillerinden kalan aksanli harfler (Turkce harflere dokunma)
    "ą": "a", "ć": "c", "ę": "e", "ł": "l", "ń": "n",
    "ś": "s", "ź": "z", "ż": "z", "š": "s", "č": "c",
    "ř": "r", "ž": "z", "æ": "ae", "ø": "o", "ð": "o",
    "þ": "p",
}

_SILINECEK_IFADELER = [
    "Doğrudan Temin Birimi - Temin Görüntülendi",
    "Şartname Şartnameyi İndir",
    "Bu İhaleyi İzlemeye Al",
    "Bu İhaleye Ait İtirazen Şikayet Başvuru Bedeli için tıklayınız.",
    "Bir Bakışta İhale",
    "Db Server'a Bağlanamadınız",
    "SATIN ALMA SÜREÇLERİ TAKİBİ",
    "İhale Durumu Sonuçlanmamış",
    "Adı - SOYADI / Ticaret unvanı",
    "BİRİM FİYAT TEKLİF CETVELİ",
    "Kaşe ve İmza",
    " Yazdır",
]

_METIN_DEGISIMLERI: list[tuple[str, str]] = [
    ("cevaplamayanfirmaların", "cevaplamayan firmaların"),
    (" kdv ", " KDV "),
    (" Kdv ", " KDV "),
    (" k.d.v ", " KDV "),
    (" K.d.v ", " KDV "),
    (" Tl ", " TL "),
    (" tl ", " TL "),
    (" :tl ", " :TL "),
    ("tl ", "TL "),
    ("Tl ", "TL "),
    (" :Tl ", " :TL "),
    ("adet", "Adet"),
    ("ADET ", "Adet"),
    ("ADET", "Adet"),
    ("(AD.)", "Adet"),
    ("kg.", " KG "),
    ("Kg.", " KG "),
    (" kg", " KG "),
    ("kg ", "KG "),
    (" kg ", " KG "),
    ("konu:", "Konu:"),
    ("KONU:", "Konu:"),
    ("KONU :", "Konu:"),
    ("konu :", "Konu:"),
    ("sayı:", "Sayı:"),
    ("SAYI:", "Sayı:"),
    ("SAYI :", "Sayı:"),
    ("sayı :", "Sayı:"),
    ("tarih :", "Tarih:"),
    ("TARİH :", "Tarih:"),
    ("TARİH:", "Tarih:"),
    ("tarih:", "Tarih:"),
    ("usül :", "Usül:"),
    ("USÜL :", "Usül:"),
    ("USÜL:", "Usül:"),
    ("usül:", "Usül:"),
    ("usûl", "usül"),
    ("hasta :", "Hasta:"),
    ("HASTA :", "Hasta:"),
    ("HASTA:", "Hasta:"),
    ("hasta:", "Hasta:"),
    (" : ", ":"),
    (" / ", "/"),
    ("TALEBİ/", "TALEBİ/ "),
]


def _karakterleri_duzelt(metin: str) -> str:
    for eski, yeni in _KARAKTER_DEGISIMLERI.items():
        metin = metin.replace(eski, yeni)
    return metin


def _bosluklari_duzelt(metin: str) -> str:
    metin = re.sub(r"[ \t]+\n", "\n", metin)
    metin = re.sub(r"\n[ \t]+", "\n", metin)
    metin = re.sub(r"\.{2,}", " ", metin)
    metin = re.sub(r"_{2,}", "", metin)
    metin = re.sub(r"-{2,}", " ", metin)
    metin = re.sub(r"[ \t]{2,}", " ", metin)
    metin = re.sub(r"\n{3,}", "\n\n", metin)
    metin = re.sub(r" *\n *\n+", "\n", metin)
    return metin


def makro1_temizle(metin: str) -> str:
    """Ctrl+1 Makro1 ile ayni metin temizligi."""
    if not metin:
        return metin

    metin = metin.replace("\t", " ")
    metin = metin.replace("\x0b", "\n")
    metin = metin.replace("\r\n", "\n").replace("\r", "\n")

    metin = _karakterleri_duzelt(metin)

    for ifade in _SILINECEK_IFADELER:
        metin = metin.replace(ifade, "")

    for eski, yeni in _METIN_DEGISIMLERI:
        metin = metin.replace(eski, yeni)

    metin = _bosluklari_duzelt(metin)

    satirlar = [s.strip() for s in metin.split("\n")]
    satirlar = [s for s in satirlar if s]
    return "\n".join(satirlar)
