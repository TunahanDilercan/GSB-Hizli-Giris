# GSB Hızlı Giriş

Bu repo, GSB WiFi portalına **hızlı giriş / hızlı çıkış** için masaüstü uygulamasının kaynak kodunu içerir.

## Repo içeriği
- `src/`: Python kaynak kodları
- `assets/icons/`: ikonlar (`.ico`) ve `favicon.png`

## Kurulum (geliştirme)
```bash
pip install -r requirements.txt
pip install -r requirements-dev.txt
```

## Build (Windows / PyInstaller)
Aşağıdaki komutlar örnektir; kendi ortamınıza göre `python`/`pip` yolu değişebilir.

```powershell
# Proje kökünde
python -m PyInstaller --clean --onefile --noconsole --icon="assets/icons/GSB_Giris.ico" --name="GSB_Giris" --distpath="dist/Uygulama" "src/GSB_Giriş.py"
python -m PyInstaller --clean --onefile --noconsole --icon="assets/icons/GSB_Giris2.ico" --name="GSB_Giris2" --distpath="dist/Uygulama" "src/GSB_Giriş2.py"
python -m PyInstaller --clean --onefile --noconsole --icon="assets/icons/GSB_Cikis.ico" --name="GSB_Cikis" --distpath="dist/Uygulama" "src/gsb_cikis.py"
python -m PyInstaller --clean --onefile --noconsole --icon="assets/icons/GSB_Giris.ico" --name="GSB" --distpath="dist" "src/gsb_ayar_gui.py"
```

## Önemli
- `config_giris*.json` dosyaları **TC/şifre** içerir; repoya konmaz.
- `.exe` dosyaları repoya konmaz; GitHub Releases üzerinden yayınlanır.
