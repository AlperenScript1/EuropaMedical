import time
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

driver = webdriver.Chrome()
driver.maximize_window()

url = "https://ted.europa.eu/en/browse-by-business-sector"
driver.get(url)

MEDICAL_SATIR_JS = """
const rows = [...document.querySelectorAll('table tr')].filter(
    row => row.querySelectorAll('td').length > 0
);
for (const row of rows) {
    if (!/medical/i.test(row.innerText)) continue;
    const rect = row.getBoundingClientRect();
    const gorunur = rect.top >= 0 && rect.bottom <= window.innerHeight;
    if (!gorunur) continue;

    const link = row.querySelector('a[href*="/notice/-/detail/"]');
    return {
        rowText: row.innerText.trim().slice(0, 150),
        noticeNumber: link ? link.textContent.trim() : null,
    };
}
return null;
"""

try:
    arama_kutusu = WebDriverWait(driver, 10).until(
        EC.element_to_be_clickable((By.XPATH, "//input[@id='ted-search-input-text']"))
    )
    arama_kutusu.click()
    arama_kutusu.send_keys("medical")
    print("[OK] Arama kutusuna 'medical' yazıldı.")

    ara_butonu = WebDriverWait(driver, 10).until(
        EC.element_to_be_clickable((By.XPATH, "(//button[@id='ted-search-submit'])[1]"))
    )
    ara_butonu.click()
    print("[OK] Ara butonuna tıklandı. Sonuçlar bekleniyor...")

    WebDriverWait(driver, 15).until(lambda d: "search/result" in d.current_url)
    print("[OK] Arama sonuç sayfasına geçildi.")

    print("[BİLGİ] 'Medical' görünene kadar sayfa yavaşça aşağı kaydırılacak...")

    medical_bulundu = False
    bulunan_ilan_no = None
    for kaydirma_sayisi in range(40):
        medical_satir = driver.execute_script(MEDICAL_SATIR_JS)
        if medical_satir:
            print(
                f"[BAŞARILI] 'Medical' ekranda göründü! Kaydırma durduruldu. "
                f"(Adım: {kaydirma_sayisi + 1})"
            )
            print(f"[BİLGİ] Bulunan satır: {medical_satir['rowText']}")
            bulunan_ilan_no = medical_satir.get("noticeNumber")
            medical_bulundu = True
            break

        satir_sayisi = len(driver.find_elements(By.XPATH, "//table//tr[td]"))
        print(
            f"-> Henüz ekranda görünmedi, aşağı kaydırılıyor... "
            f"(Adım {kaydirma_sayisi + 1}, yüklenen satır: {satir_sayisi})"
        )
        driver.execute_script("window.scrollBy(0, 250);")
        time.sleep(1.5)

    if not medical_bulundu:
        print("[HATA] Sayfa kaydırılmasına rağmen ekranda 'Medical' içeren satır bulunamadı.")
    elif not bulunan_ilan_no:
        print("[HATA] Bulunan satırda ilan numarası linki tespit edilemedi.")
    else:
        print(f"[BİLGİ] İlan linkine tıklanıyor: {bulunan_ilan_no}")
        ilan_linki = WebDriverWait(driver, 10).until(
            EC.presence_of_element_located(
                (By.XPATH, f"//table//tr[td]//a[normalize-space()='{bulunan_ilan_no}']")
            )
        )
        driver.execute_script(
            "arguments[0].scrollIntoView({block: 'center'}); arguments[0].click();",
            ilan_linki,
        )

        WebDriverWait(driver, 15).until(
            lambda d: "/notice/-/detail/" in d.current_url
        )
        print(f"[OK] İlan detay sayfasına girildi: {driver.current_url}")
        print("[OK] İşlem tamamlandı. 5 saniye sonra kapanacak.")
        time.sleep(5)

except Exception as e:
    print(f"Bir hata oluştu: {e}")

finally:
    driver.quit()
    print("[BİTTİ] Test sonlandırıldı.")
