# GSB Hızlı Giriş

Bu proje, GSB WiFi portalına **hızlı giriş / hızlı çıkış** için masaüstü uygulamasıdır.

## Kullanım (Önerilen)
1) GitHub sayfasından **Releases** bölümüne gir
2) En güncel `GSB-Release-....zip` dosyasını indir
3) Zip’i aç ve `GSB\GSB.exe` çalıştır
4) TC / şifreyi kaydet (masaüstüne kısayollar otomatik oluşur)

## Kaynak Kod
Bu repo kaynak kodu içerir:
- `src/`: Python kaynak kodları
- `assets/icons/`: ikonlar

Geliştirici olarak build almak istersen bağımlılıkları `pip` ile kurup PyInstaller ile derleyebilirsin.

## Güvenlik
- `config_giris*.json` dosyaları **TC/şifre** içerir; repoya konulmaz.
- `.exe` dosyaları repoya konulmaz; Release üzerinden yayınlanır.
