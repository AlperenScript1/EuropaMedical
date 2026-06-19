import ctypes
import shutil
import sys
import traceback
from datetime import datetime
from pathlib import Path

from colorama import Fore, Style, init

init(autoreset=True)

HATA_GUNLUK_KLASORU = Path(__file__).resolve().parent / "hata günlükleri"
UST_BANNER_METNI = "CTRL+C ile uygulamayı kapatabilirsiniz"

YESIL = Fore.GREEN
KIRMIZI = Fore.RED
SARI = Fore.YELLOW
MAVI = Fore.CYAN
RESET = Style.RESET_ALL


def _vt_modu_ac() -> None:
    if sys.platform != "win32":
        return
    try:
        kernel32 = ctypes.windll.kernel32
        handle = kernel32.GetStdHandle(-11)
        mode = ctypes.c_uint32()
        kernel32.GetConsoleMode(handle, ctypes.byref(mode))
        kernel32.SetConsoleMode(handle, mode.value | 0x0004)
    except Exception:
        pass


def _terminal_genisligi() -> int:
    try:
        return shutil.get_terminal_size((120, 30)).columns
    except OSError:
        return 120


def ust_banner_goster() -> None:
    """Ust satirda sabit kirmizi uyari; asagidaki loglar kaydirilir."""
    _vt_modu_ac()
    _banner_satirini_koru()
    sys.stdout.write("\033[2;999;r")
    sys.stdout.write("\033[2;1H")
    sys.stdout.flush()


def _banner_satirini_koru() -> None:
    if not sys.stdout.isatty():
        return
    genislik = _terminal_genisligi()
    metin = UST_BANNER_METNI.center(genislik)
    sys.stdout.write("\033[s")
    sys.stdout.write("\033[1;1H")
    sys.stdout.write(f"{KIRMIZI}{metin.ljust(genislik)[:genislik]}{RESET}")
    sys.stdout.write("\033[u")
    sys.stdout.flush()


class TerminalLog:
    def __init__(self):
        self.kayitlar: list[str] = []
        self.hata_var = False

    def _ekle(self, etiket: str, mesaj: str, renk: str) -> None:
        satir = f"[{etiket}] {mesaj}"
        self.kayitlar.append(satir)
        print(f"{renk}{satir}{RESET}", flush=True)
        _banner_satirini_koru()

    def bilgi(self, mesaj: str) -> None:
        self._ekle("BİLGİ", mesaj, YESIL)

    def bilgi_mavi(self, mesaj: str) -> None:
        self._ekle("BİLGİ", mesaj, MAVI)

    def basarili(self, mesaj: str) -> None:
        self._ekle("OK", mesaj, YESIL)

    def uyari(self, mesaj: str) -> None:
        self._ekle("UYARI", mesaj, SARI)

    def hata(self, mesaj: str) -> None:
        self.hata_var = True
        self._ekle("HATA", mesaj, KIRMIZI)

    def hata_kaydet(self, exc: Exception | None = None) -> Path | None:
        if not self.hata_var:
            return None

        HATA_GUNLUK_KLASORU.mkdir(exist_ok=True)
        simdi = datetime.now()
        dosya_adi = f"{simdi.strftime('%d.%m.%Y')}_{simdi.strftime('%H-%M-%S')}.log"
        dosya_yolu = HATA_GUNLUK_KLASORU / dosya_adi

        icerik = "\n".join(self.kayitlar)
        if exc is not None:
            icerik += "\n\n--- TEKNİK DETAY ---\n"
            icerik += "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))

        dosya_yolu.write_text(icerik, encoding="utf-8")
        print(f"{KIRMIZI}[HATA] Günlük kaydedildi: {dosya_yolu}{RESET}", flush=True)
        _banner_satirini_koru()
        return dosya_yolu


def konsol_hazirla() -> None:
    if sys.platform == "win32":
        try:
            sys.stdout.reconfigure(encoding="utf-8")
            sys.stderr.reconfigure(encoding="utf-8")
        except Exception:
            pass
    ust_banner_goster()
