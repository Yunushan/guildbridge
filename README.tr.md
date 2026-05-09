<div align="center">

<img src="docs/assets/guildbridge-icon.svg" alt="GuildBridge simgesi" width="96" height="96">

# GuildBridge

**Discord, Stoat, Fluxer, Spacebar, Daccord, Matrix/Element, Rocket.Chat, Mumble, Mattermost ve Zulip icin gizlilik odakli sunucu/topluluk sablonu ice-disa aktarma araci.**

Uyeleri, mesajlari, DM'leri, token'lari veya ham kullanici kimliklerini acik kaynak sablonlara koymadan topluluk yapisini ice aktarir, disa aktarir, redakte eder, dogrular ve tasir.

![python](https://img.shields.io/badge/python-3.10%2B-blue) ![license](https://img.shields.io/badge/license-MIT-blue) ![build](https://img.shields.io/badge/build-ready-brightgreen) ![privacy](https://img.shields.io/badge/privacy-redacted_by_default-success)

**dil** [English](README.md) · [Turkce](README.tr.md)

**saglayicilar** Discord · Fluxer · Stoat · Spacebar · Daccord · Matrix/Element · Rocket.Chat · Mumble · Mattermost · Zulip  
**arayuzler** CLI · masaustu GUI · web/mobil GUI  
**islemler** export · import · migrate · validate · redact · dry-run · apply

[Hizli Baslangic](#hizli-baslangic) • [GUI](#gui) • [Desteklenen Platformlar](#desteklenen-platformlar) • [Desteklenen Yollar](#desteklenen-yollar) • [Gizlilik Modeli](#gizlilik-modeli) • [Kurtarma Rehberi](#kurtarma-rehberi) • [Yayin Hijyeni](#yayin-hijyeni) • [Yapilandirma](#yapilandirma) • [Ornekler](#ornekler) • [Saglayici Notlari](#saglayici-notlari) • [Katki](#katki) • [Lisans](#lisans)

</div>

---

## GuildBridge nedir?

GuildBridge topluluk/sunucu duzenini tarafsiz bir JSON formatina donusturur ve sonra bu yapiyi baska bir platforma aktarir.

Odak noktasi **tasinabilir yapi**dir; gozetim veya veri klonlama degildir:

- roller ve guvenli rol izinleri
- kategoriler / kanal gruplari / Matrix space yapilari
- hedef platform destekliyorsa metin, ses, duyuru, forum, stage ve baglanti benzeri kanallar
- guvenli kanal konulari ve temel kanal ayarlari
- mumkun oldugu kadar rol/everyone izin overwrite kayitlari
- herhangi bir yazma isleminden once dry-run planlari

Bilerek **disa aktarilmayan** veriler:

- mesajlar veya mesaj gecmisi
- uyeler, uye listeleri, DM'ler, arkadas listeleri, presence bilgisi, e-postalar, IP'ler veya kisisel profiller
- bot token'lari, access token'lari, oturum token'lari veya cookie'ler
- uretilen sablonlarda ham saglayici ID'leri; kaynak ID'ler hash'lenir/yerellestirilir
- kullanici/uyeye ozel izin overwrite kayitlari; diagnostics istense bile guvensiz kullanici hedefleri dusurulur

## En iyi proje adi

Onerilen ad: **GuildBridge**.

Neden uygun:

- "Guild", Discord benzeri topluluklar ve oyun/sohbet platformlari tarafindan kolay anlasilir.
- "Bridge", ice/disa aktarma amacini netlestirir.
- CLI komutu ve paket adi icin yeterince kisadir: `guildbridge`.
- Projeyi tek bir platforma kilitlemez.

Alternatif adlar:

- **ServerPort** - anlasilir, fakat daha cok altyapi/ag izlenimi verir.
- **CommunityBridge** - daha genis, fakat daha uzun.
- **ChanFerry** - akilda kalici, fakat daha az profesyonel.
- **SpaceBridge** - Matrix/Element icin iyi, Discord/Fluxer/Stoat icin daha az acik.

## Hizli Baslangic

### 1. Yerel kurulum

```bash
git clone https://github.com/Yunushan/guildbridge.git
cd guildbridge
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\\Scripts\\activate
python -m pip install -e ".[dev]"
```

### 2. Token'lari commit etmeden yapilandir

```bash
cp .env.example .env
$EDITOR .env
```

`.env` dosyasini asla commit etmeyin. Depodaki `.gitignore` bunu dislar.

### 3. Saglayicilari gor

```bash
guildbridge providers
```

### 4. Platform destegini kontrol et

```bash
guildbridge platforms --check
```

### 5. GUI'yi baslat

```bash
guildbridge-gui
```

Tarayici ve mobil erisim icin:

```bash
guildbridge-web
```

### 6. Discord sunucu sablonunu tarafsiz JSON'a aktar

```bash
guildbridge export \
  --from discord \
  --template "https://discord.new/your-template-code" \
  --out community.template.json
```

### 7. Fluxer'a ice aktarma dry-run'i olustur

```bash
guildbridge import \
  --to fluxer \
  --file community.template.json \
  --target-name "Imported Community" \
  --plan-out fluxer.plan.json
```

### 8. Plani inceledikten sonra uygula

```bash
guildbridge import \
  --to fluxer \
  --file community.template.json \
  --target-name "Imported Community" \
  --plan-out fluxer.result.json \
  --plan-in fluxer.plan.json \
  --apply \
  --confirm-apply APPLY
```

Onayli apply calistirmalari `--plan-in` ile incelenmis bir dry-run plani gerektirir. GuildBridge yazma yapmadan once aday plani yeniden hesaplar; komut, hedef, sablon parmak izi, islem sayisi ve islem hash'i incelenmis dosya ile ayni degilse yazmayi reddeder. Apply calistirmalari, saglayici yazmalari baslamadan once yerel bir journal da yazar. Varsayilan journal konumu `.guildbridge/journals/` altidir; belirli bir yol icin `--journal-out path/to/journal.json` kullanin. Bir calistirma yarida kalirsa yeniden denemeden once journal'i inceleyin ve GuildBridge'in ayni komut, hedef, saglayici, sablon parmak izi ve incelenmis plan hash'ini dogrulamasi icin `--resume-journal path/to/journal.json` gecin.

Import ve migrate tek bir incelenmis planda birden fazla hedefe yazabilir. `--to` tekrar edilebilir veya hedefler virgulle ayrilabilir; hedef ID veya adlari hedefe gore degisiyorsa `provider=value` kullanin:

```bash
guildbridge migrate \
  --from discord \
  --to stoat \
  --to fluxer \
  --template "https://discord.new/your-template-code" \
  --target-name stoat="Stoat Copy" \
  --target-name fluxer="Fluxer Copy" \
  --plan-out multi-target.plan.json
```

Coklu hedef dry-run'i, her hedef saglayici icin ayri dogrulanmis sonuc iceren `guildbridge.batch-result.v1` plani yazar. Uygulamak icin ayni komut sekline `--plan-in multi-target.plan.json --apply --confirm-apply APPLY` eklenir. Birden fazla hedefte `--journal-out journal.json` kullanilirsa GuildBridge `journal.stoat.json` ve `journal.fluxer.json` gibi saglayiciya ozel journal dosyalari yazar.

## GUI

GuildBridge, CLI ile ayni export, import, migrate, validate ve redact komutlarini saran iki GUI modu icerir.

Masaustu GUI:

```bash
guildbridge-gui
```

Tarayici/mobil GUI:

```bash
guildbridge-web
```

Windows release build'lerinde kullanicilar Python kurmadan ayni arayuzleri calistirabilir:

```text
guildbridge-gui.exe
guildbridge-web.exe
```

### Masaustu GUI akisi

1. GUI'yi acmadan once saglayici token'larini `.env` icinde yapilandirin.
2. `guildbridge-gui` veya `guildbridge-gui.exe` acin.
3. Once **Platforms** sekmesini kullanarak CLI, masaustu GUI ve web GUI hazirligini kontrol edin.
4. Kaynak saglayicidan tarafsiz template olusturmak icin **Export** kullanin. Source ID veya provider template URL/code girin, sonra output JSON yolu secin.
5. Mevcut template'i bir veya daha fazla hedef saglayiciya aktarmak icin **Import**, tek export ile bir veya daha fazla hedefe import icin **Migrate** kullanin.
6. Acik ve koyu mod arasinda gecmek icin **Theme** secicisini kullanin.
7. Ilk calistirmada **Apply writes** isaretli olmasin. Bu, provider'a yazmadan **Plan/result JSON** icinde dry-run plan olusturur.
8. Olusturulan plan JSON dosyasini inceleyin.
9. Gercek yazma yapmak icin incelenmis plani **Reviewed plan JSON** alaninda secin, **Apply writes** isaretleyin ve onay penceresi istediginde `APPLY` yazin.
10. Apply calistirmalarinda **Journal output JSON** kullanin ki yarida kalan yazmalar denetlenebilsin. **Resume journal JSON** yalnizca ayni komut, hedef, template ve incelenmis planla yarida kalmis apply'i tekrar denerken kullanin.
11. Template paylasmadan once **Validate / Redact** kullanin.

Output paneli GUI'nin calistirdigi tam `guildbridge ...` komutunu, stdout/stderr ciktisini, exit code'u ve sureyi gosterir.

Tarayici GUI varsayilan olarak `http://127.0.0.1:8765` adresinde baslar. Telefon ve tablet tarayicilari icin dokunmaya uygun kontroller, sabit gezinme, acik/koyu tema secimi, sonuc durum panelleri ve kaydirma guvenli platform tablolari olan responsive bir duzen kullanir. Ayrica her sunucu icin CSRF token'i kullanir, POST govde boyutunu sinirlar, temel tarayici guvenlik basliklari ekler ve tarayicidan tetiklenen yazma islemlerinin `--apply` ile calismasi icin `APPLY` yazilmasini zorunlu tutar.

Her iki GUI modu da import ve migrate icin CLI ile ayni apply guvenligi kontrollerini sunar: incelenmis plan girdisi, journal ciktisi, resume journal, inceleme sonrasi gecersiz sablonu zorlama ve yazmalari uygulama. Apply islemleri incelenmis plan yolu ve yazilmis `APPLY` ister; GuildBridge saglayici yazmalari baslamadan once incelenmis plani yine dogrular.

Ayni agdaki telefon veya tabletlerin baglanmasini sadece guvenilir aglarda istiyorsaniz `--host 0.0.0.0 --allow-lan --auth-token "uzun-rastgele-bir-token-secin"` kullanin. LAN modu her istekte auth token'i ister; `--auth-token` vermediginizde GuildBridge bir token uretir ve baslangicta bir kez yazdirir.

### Tarayici ve mobil akis

1. Yerel web GUI'yi baslatin:

```bash
guildbridge-web
```

2. Tarayicida `http://127.0.0.1:8765` acin.
3. Masaustu GUI ile ayni **Migrate**, **Export**, **Import**, **Validate**, **Redact**, **Runtime** ve **Platforms** bolumlerini kullanin.
4. Ayni guvenilir agdaki telefon veya tabletten erisim icin sunucuyu LAN modunda baslatin:

```bash
guildbridge-web --host 0.0.0.0 --port 8765 --allow-lan --auth-token "uzun-rastgele-bir-token-secin"
```

5. Yazdirilan LAN URL'sini mobil tarayicida acin ve auth token'i ekleyin. Bu token'i gizli tutun; web GUI onaydan sonra provider yazma islemleri calistirabilir.

Alternatif baslatma komutlari:

```bash
python -m guildbridge.gui
python -m guildbridge.web
```

Masaustu GUI, Tkinter kurulu ve masaustu oturumu olan platformlarda calisir. Android ve iOS, `guildbridge-web` icin tarayici istemcisi hedefleridir; cihaz uzerinde CLI kullanimi deneyseldir cunku mobil Python calisma zamanlari degiskenlik gosterir.

## Desteklenen Platformlar

GuildBridge destegi kademelidir; boylece platform iddialari durust kalir:

- CI ile test edilen CLI/runtime: Windows, Ubuntu, macOS ve GitLab Python imaji uzerinden Debian.
- GitHub Actions, zorunlu hosted matrix uzerinde Python 3.10, 3.11, 3.12, 3.13 ve 3.14 test eder.
- Hosted compatibility job'lari Windows Server 2022 ve macOS 26 kapsar. Windows 10/11, Windows Server 2019/2026 ve Ubuntu 26.04 icin kesin kontroller manuel self-hosted workflow ile calisir; GitHub bu hedefler icin normal hosted label saglamaz.
- Kurulum betigi destekli: Windows Server, Linux Mint, RHEL, AlmaLinux, Rocky Linux, Oracle Linux, Fedora, CentOS, CentOS Stream, Arch Linux, Manjaro Linux, Gentoo, FreeBSD, NetBSD ve OpenBSD.
- Tarayici istemcisi destekli: Android ve Apple iOS, mobil tarayicidan `guildbridge-web` kullanabilir. Cihaz uzerinde CLI destegi deneyseldir ve Python runtime'a baglidir.

Masaustu GUI destegi Tkinter ve masaustu oturumu gerektirir. Headless sunucular CLI veya tarayici GUI kullanabilir.

Platform bagimliliklarini kurmak veya kontrol etmek:

```bash
./scripts/install-system-deps.sh
./scripts/install-system-deps.sh --dry-run --require dev
guildbridge platforms --check
python scripts/check-platform.py --require cli --format json
```

Windows:

```powershell
.\scripts\check-platform.ps1
.\scripts\check-platform.ps1 -Require desktop-gui
```

Varsayilan kontrol yalnizca CLI hazirligini zorunlu tutar. Bu yetenekleri katı gereksinim yapmak icin `--require desktop-gui`, `--require web-gui` veya `--require dev` kullanin.

Paket adlari ve platforma ozel notlar icin [docs/PLATFORMS.md](docs/PLATFORMS.md) dosyasina bakin.

## Desteklenen Yollar

Tum saglayicilar ayni tarafsiz semaya export yapar; migration yolu sudur:

```text
source provider -> neutral community.template.json -> target provider
```

### Enterprise chat ve voice yollari

- **Discord/Fluxer/Stoat/Spacebar/Daccord/Matrix -> Rocket.Chat**: destekli. Rocket.Chat rolleri ve odalari olusturur; odaya ozel izin semantigi best-effort'tur.
- **Rocket.Chat -> Discord/Fluxer/Stoat/Spacebar/Daccord/Matrix**: destekli. Odalari ve workspace rollerini export eder; mesajlar, kullanicilar, abonelikler ve DM'ler disarida tutulur.
- **Discord/Fluxer/Stoat/Spacebar/Daccord/Matrix/Rocket.Chat/Mattermost/Zulip -> Mumble**: admin bridge ile destekli. Yapilandirilmis admin API bridge uzerinden Mumble gruplari ve ses kanallari olusturur.
- **Mumble -> Discord/Fluxer/Stoat/Spacebar/Daccord/Matrix/Rocket.Chat/Mattermost/Zulip**: admin bridge ile destekli. Mumble gruplarini, kanallarini ve ACL benzeri izinleri export eder; canli ses durumu ve kayitlar disarida tutulur.
- **Mattermost -> Discord/Fluxer/Stoat/Spacebar/Daccord/Matrix/Rocket.Chat/Mumble/Zulip**: destekli. Team kanallarini ve tasinabilir rol ipuclarini export eder; post'lar, kullanicilar, DM'ler ve kullaniciya ozel sidebar kategorileri disarida tutulur.
- **Discord/Fluxer/Stoat/Spacebar/Daccord/Matrix/Rocket.Chat/Mumble/Zulip -> Mattermost**: destekli. Team ve metin benzeri kanal olusturur; keyfi rol olusturma ve permission scheme'leri Mattermost yonetiminde best-effort kalir.
- **Zulip -> Discord/Fluxer/Stoat/Spacebar/Daccord/Matrix/Rocket.Chat/Mumble/Mattermost**: destekli. Zulip kanallarini ve user group'lari export eder; topic'ler, mesajlar, abonelikler, kullanicilar ve DM'ler disarida tutulur.
- **Discord/Fluxer/Stoat/Spacebar/Daccord/Matrix/Rocket.Chat/Mumble/Mattermost -> Zulip**: destekli. Subscription uzerinden kanal olusturur ve rolleri user group'a map eder; kategori ve overwrite semantigi best-effort'tur.

### Temel saglayici yollari

- **Discord -> Fluxer**: destekli. Yapısal uyum iyidir; kanal/rol izinleri best-effort map edilir.
- **Discord -> Stoat**: destekli. Yapilandirilabilir Stoat/Revolt tarzı API endpoint'leri kullanir.
- **Discord -> Spacebar**: destekli. Spacebar Discord uyumludur; GuildBridge Discord tarzı guild, rol, kanal ve izin payload'lari kullanir.
- **Discord -> Daccord**: destekli. Daccord space/kanal/rol olusturur ve rol permission overwrite'larini Daccord admin API uzerinden uygular.
- **Discord -> Matrix/Element**: destekli. Matrix spaces ve rooms olusturur; roller birebir map edilemez.
- **Fluxer -> Discord**: destekli. Mevcut bir Discord guild hedefi gerektirir.
- **Fluxer -> Stoat**: destekli. Best-effort rol/kanal mapping.
- **Fluxer/Stoat/Spacebar/Daccord cross-migration**: destekli. Discord benzeri yapilar iyi map edilir; saglayiciya ozel bayraklar best-effort kalir.
- **Fluxer -> Matrix/Element**: destekli. Kategoriler nested space olur.
- **Stoat -> Discord**: destekli. Best-effort rol/kanal mapping.
- **Stoat -> Fluxer**: destekli. Best-effort rol/kanal mapping.
- **Stoat -> Matrix/Element**: destekli. Kategoriler space olur.
- **Matrix/Element -> Discord/Fluxer/Stoat/Spacebar/Daccord/Rocket.Chat/Mumble/Mattermost/Zulip**: destekli. Matrix space hiyerarsisini kanal olarak export eder; Matrix'te global sunucu rolleri yoktur.

## Yapilandirma

GuildBridge ortam degiskenlerini okur. Kaynak dosya olarak `.env.example` kullanin.

### Discord

```bash
DISCORD_BOT_TOKEN="..."
DISCORD_API_BASE="https://discord.com/api/v10"
```

Discord botunun guild rollerini/kanallarini okuyacak ve hedef guild'e ice aktarim sirasinda rol/kanal olusturacak yeterli izne ihtiyaci vardir.

### Fluxer

```bash
FLUXER_BOT_TOKEN="..."
FLUXER_API_BASE="https://api.fluxer.app/v1"
```

Gerekiyorsa `FLUXER_API_BASE` degerini self-hosted instance'iniza ayarlayin.

### Stoat

```bash
STOAT_BOT_TOKEN="..."
STOAT_API_BASE="https://api.stoat.chat"
```

Stoat uyumlu endpoint'ler ve authentication zamanla degisebilir. Kendi instance'iniz icin base URL ve saglayici implementasyonunu duzenlenebilir tutun.

### Spacebar

```bash
SPACEBAR_BOT_TOKEN="..."
SPACEBAR_API_BASE="https://api.spacebar.chat/api/v9"
```

Spacebar Discord uyumludur. GuildBridge yapilandirilmis Spacebar instance'ina karsi Discord tarzi guild, rol, kanal ve izin endpoint'lerini kullanir.

### Daccord

```bash
DACCORD_API_BASE="https://daccord.example.org/api/v1"
DACCORD_BOT_TOKEN="..."
DACCORD_AUTH_SCHEME="Bot"
```

Daccord `Bot` ve `Bearer` authorization scheme'lerini destekler. Instance'iniz bot token yerine user bearer token veriyorsa `DACCORD_AUTH_SCHEME=Bearer` kullanin.

### Matrix/Element

```bash
MATRIX_ACCESS_TOKEN="..."
MATRIX_BASE_URL="https://matrix.example.org"
MATRIX_SERVER_NAME="example.org"
```

Element bir Matrix istemcisidir; bu nedenle GuildBridge Matrix Client-Server API'sini kullanir.

### Rocket.Chat

```bash
ROCKET_CHAT_API_BASE="https://chat.example.org/api/v1"
ROCKET_CHAT_AUTH_TOKEN="..."
ROCKET_CHAT_USER_ID="..."
```

Rocket.Chat odalari/kanallari ve workspace rollerini export eder. Mesajlari, kullanicilari, abonelikleri, direkt mesajlari veya ozel kullanici metadata'sini export etmez.

### Mumble

```bash
MUMBLE_API_BASE="https://mumble-admin.example.org/api/v1"
MUMBLE_API_TOKEN="..."
```

Mumble/Murmur ses portu uzerinde evrensel bir HTTP yonetim API'si sunmaz. GuildBridge, `MUMBLE_API_BASE` degerinin sunucu, grup, kanal ve ACL route'lari saglayan bir Murmur/Ice/gRPC yonetim admin API bridge'ine isaret etmesini bekler.

### Mattermost

```bash
MATTERMOST_API_BASE="https://mattermost.example.org/api/v4"
MATTERMOST_TOKEN="..."
```

Mattermost import'u team ve metin benzeri kanal olusturur. Mattermost rolleri ve permission scheme'leri keyfi Discord tarzi roller degildir; bu nedenle GuildBridge tasinamayan rol ve overwrite niyetini uyari/metadata olarak korur.

### Zulip

```bash
ZULIP_API_BASE="https://zulip.example.org/api/v1"
ZULIP_EMAIL="bot@example.org"
ZULIP_API_KEY="..."
```

Zulip import'u kanallari subscription uzerinden olusturur ve everyone disi rolleri user group'a map eder. Zulip topic'leri, mesaj gecmisi, abonelikler, kullanicilar ve private DM'ler bilerek export edilmez.

## Ornekler

### Discord sablonu -> Fluxer sunucusu

```bash
guildbridge migrate \
  --from discord \
  --to fluxer \
  --template "https://discord.new/abc123" \
  --target-name "Fluxer Copy" \
  --template-out exported.template.json \
  --plan-out fluxer.plan.json

# fluxer.plan.json incelendikten sonra:
guildbridge migrate \
  --from discord \
  --to fluxer \
  --template "https://discord.new/abc123" \
  --target-name "Fluxer Copy" \
  --plan-out fluxer.result.json \
  --plan-in fluxer.plan.json \
  --apply \
  --confirm-apply APPLY
```

### Canli Discord guild -> mevcut Discord guild

```bash
guildbridge export --from discord --source-id "SOURCE_GUILD_ID" --out source.template.json

guildbridge import \
  --to discord \
  --file source.template.json \
  --target-id "TARGET_GUILD_ID" \
  --plan-out discord.plan.json
```

### Fluxer -> Stoat

```bash
guildbridge migrate \
  --from fluxer \
  --to stoat \
  --source-id "FLUXER_GUILD_ID" \
  --target-name "Stoat Copy" \
  --plan-out stoat.plan.json
```

### Tek kaynak -> birden fazla hedef

```bash
guildbridge migrate \
  --from discord \
  --to stoat,fluxer \
  --template "https://discord.new/abc123" \
  --target-name stoat="Stoat Copy" \
  --target-name fluxer="Fluxer Copy" \
  --plan-out discord-to-many.plan.json
```

### Element/Matrix space -> Discord

```bash
guildbridge export \
  --from element \
  --source-id '!spaceid:matrix.example.org' \
  --out matrix-space.template.json

guildbridge import \
  --to discord \
  --file matrix-space.template.json \
  --target-id "DISCORD_TARGET_GUILD_ID" \
  --plan-out discord.plan.json
```

### Dogrula ve redakte et

```bash
guildbridge validate community.template.json

guildbridge redact community.template.json --out safe.template.json
```

## Tarafsiz sema

Tarafsiz JSON semasi:

```text
schema/community-template.schema.json
```

Bir sablon sunlari icerir:

```json
{
  "schema": "guildbridge.community.v1",
  "version": "1.0",
  "name": "Example Community",
  "privacy": {
    "exports_members": false,
    "exports_messages": false,
    "stores_tokens": false
  },
  "roles": [],
  "categories": [],
  "channels": []
}
```

## Gizlilik Modeli

GuildBridge, herkese acik sablon dosyalarinin guvenle yayinlanabilmesi icin tasarlanmistir.

### Katı kurallar

1. **Mesaj yok.** Mesaj gecmisi semanin parcasi degildir.
2. **Uye yok.** Uye listeleri ve kullanici profilleri semanin parcasi degildir.
3. **DM yok.** Direkt/ozel konusmalar asla export edilmez.
4. **Sir yok.** Token ve oturum degerleri yalnizca ortam degiskenlerinden okunur.
5. **Kararlı incelenmis planlar.** `--apply --confirm-apply APPLY --plan-in <reviewed-plan.json>` ayarlanmadikca import hicbir sey yazmaz. GuildBridge mevcut aday plan incelenmis dry-run planindan farkliysa yazmayi reddeder.
6. **Apply journal'lari.** Onayli apply calistirmalari, kesintiye ugrayan yazmalarin yeniden denemeden once denetlenebilmesi icin baslayan, basarili ve basarisiz islem kayitlari olan yerel bir journal yazar.
7. **Redaksiyon mevcut.** `guildbridge redact`, elle duzenlenmis sablonlardan guvensiz metadata anahtarlarini, token benzeri degerleri, ham kaynak ID'leri ve guvensiz overwrite placeholder'larini kaldirir.

## Kurtarma Rehberi

Komut hatalari, asıl hata ile birlikte yaygin operator sorunlari icin kurtarma ipuclari icerir: eksik dosyalar, gecersiz JSON, eksik saglayici token'lari, HTTP authentication/rate-limit/saglayici hatalari, incelenmis plan drift'i, gecersiz sablonlar ve journal resume uyumsuzluklari.

Kesintiye ugrayan apply calistirmalari icin once journal'i inceleyin. Yalnizca ayni komut, hedef, sablon ve incelenmis plan ile yeniden deneyin; yazmadan once GuildBridge'in yeniden denemeyi dogrulamasi icin `--resume-journal path/to/journal.json` gecin.

### Kaynak ID'ler

Saglayici ID'leri su sekilde yerel ID'lere donusturulur:

```text
role_discord_2f1a4c...
chan_fluxer_91bb20...
```

Bu, orijinal ham ID'leri aciga cikarmadan sablonu kararlı tutar.

## Saglayici Notlari

### Discord

- Bot token'i ile canli guild'den export yapabilir.
- Discord sunucu sablonu URL/kodu ile export yapabilir.
- `--target-id` kullanarak mevcut Discord guild'e import eder.
- Discord sunucu sablonlari kategorileri, kanallari, rolleri ve izinleri klonlayabilir; ancak Discord'un kendisi bazi community kanal turlerini sablona dahil etmez.

### Fluxer

- Discord'a benzeyen fakat ayri bir API yuzeyi kullanir.
- `--target-id` verilmezse hedef guild/sunucu olusturabilir.
- Self-hosted deployment'lar icin yapilandirilabilir base URL kullanir.

### Stoat

- Yapilandirilabilir Stoat/Revolt tarzi HTTP endpoint'leri kullanir.
- `--target-id` verilmezse hedef sunucu olusturabilir.
- Izin mapping'i best-effort'tur ve `src/guildbridge/permissions.py` icinde kolay duzenlenebilir olacak sekilde tutulur.

### Spacebar

- `SPACEBAR_API_BASE` altindaki Spacebar Discord uyumlu HTTP API'sini kullanir.
- `--target-id` kullanarak mevcut guild/sunucuya import eder.
- Spacebar Discord API uyumlulugunu hedefledigi icin Discord tarzi permission bitset'leri kullanir.

### Daccord

- Daccord `/api/v1` space, rol, kanal ve permission route'larini kullanir.
- `--target-id` verilmezse hedef space olusturabilir.
- `manage_space`, `view_channel` ve `send_messages` gibi Daccord rol permission adlarini destekler.

### Matrix/Element

- Element Matrix uzerinde calisir; bu nedenle saglayici Matrix Client-Server endpoint'lerini kullanir.
- Kategoriler nested Matrix space olarak import edilir.
- Kanallar Matrix room olarak import edilir.
- Discord/Fluxer/Stoat tarzi global roller, GuildBridge'in bilerek kullanmadigi uye ID'leri olmadan dogru temsil edilemez.

### Rocket.Chat

- Rocket.Chat REST API kimlik bilgilerini kullanir: `ROCKET_CHAT_AUTH_TOKEN` ve `ROCKET_CHAT_USER_ID`.
- Workspace odalarini/kanallarini ve rolleri export eder.
- Metin benzeri kanallari Rocket.Chat channel veya private group olarak import eder.
- Room-specific rol semantigi best-effort'tur; cunku Rocket.Chat izinleri cogunlukla workspace rol ayarlaridir.

### Mumble

- `MUMBLE_API_BASE` uzerinden yapilandirilmis Mumble/Murmur admin API bridge kullanir.
- Gruplari, kanal agacini ve ACL tarzı allow/deny kayitlarini export eder.
- Yapısal kanallari Mumble ses kanali olarak import eder.
- Canli kullanicilari, kayitlari, sertifikalari, ses durumunu veya text/chat gecmisini export etmez.

### Mattermost

- Mattermost API v4 ve bearer token kullanir.
- Team kanallarini ve tasinabilir team rol ipuclarini export eder.
- Team ve public/private metin benzeri kanallari import eder.
- Keyfi Discord tarzi roller, channel scheme'leri ve kullaniciya ozel sidebar kategorileri otomatik olusturulmaz.

### Zulip

- `ZULIP_EMAIL` ve `ZULIP_API_KEY` ile Zulip API v1 Basic authentication kullanir.
- Kanallari ve user group'lari export eder.
- Kanallari `users/me/subscriptions`, rolleri user group uzerinden import eder.
- Topic'ler, mesajlar, abonelikler, kullanicilar ve private DM'ler bilerek disarida tutulur.

## Yayin Hijyeni

Yayin adimlari [docs/RELEASE.md](docs/RELEASE.md) dosyasinda belgelenmistir. Kisa yerel kontrol:

```bash
make release-check
```

GitHub release workflow'u `v*` tag'leri ve manuel calistirmalar icin artifact olusturup yukler; PyPI'ye otomatik yayin yapmaz. Windows release calistirmalari ayrica `guildbridge.exe`, `guildbridge-gui.exe`, `guildbridge-web.exe` iceren portable ZIP ve WiX varsa MSI installer uretir.

Release artifact olusturma yalnizca `Release Artifacts` workflow'unda calisir; her normal push'ta calismaz. GitHub Actions uzerinden manuel baslatin veya bir surum tag'i push edin:

```bash
git tag v0.1.0
git push origin v0.1.0
```

Beklenen workflow artifact'leri:

- `guildbridge-dist`: Python wheel ve source distribution.
- `guildbridge-windows`: Windows portable ZIP ve MSI installer.

Windows artifact build ayrintilari [docs/WINDOWS_RELEASE.md](docs/WINDOWS_RELEASE.md) dosyasinda belgelenmistir.

## Gelistirme

```bash
python -m pip install -e ".[dev]"
python -m ruff check src tests scripts/check-platform.py scripts/verify-dist.py
python -m mypy src
python -m pytest -q
python scripts/check-platform.py --require cli --format json
python -m build
python -m twine check dist/*
python scripts/verify-dist.py
```

CLI'yi dogrudan calistirma:

```bash
python -m guildbridge providers
```

GUI'yi dogrudan calistirma:

```bash
python -m guildbridge.gui
```

## GitHub ve GitLab CI

Bu repo ikisini de icerir:

```text
.github/workflows/ci.yml
.gitlab-ci.yml
```

Iki pipeline da kurulum, lint, type check, testler, platform kontrolleri, package build, dagitim metadata kontrolleri ve wheel kurulum dogrulamasini calistirir.

GitHub Actions ayrica `v*` tag'leri ve manuel calistirmalar icin `Release Artifacts` workflow'una sahiptir. Normal CI wheel/sdist package'lari build edip dogrular ama indirilebilir artifact yuklemez. Release workflow wheel/sdist, Windows ZIP ve Windows MSI yeniden olusturur, workflow artifact'i olarak yukler ve tag build'lerinde GitHub Release asset'i olarak ekler; PyPI'ye otomatik yayin yapmaz.

Versiyonu guncelleyen, kontrolleri calistiran, `dist/` ciktisini build edip dogrulayan, commit atan ve push yapmadan annotated tag olusturan yerel release hazirligi icin:

```powershell
.\scripts\release.ps1 -Version 1.0.0
```

Linux, BSD, macOS, Android terminal ortamlari ve `sh`, `git`, Python sunan iOS terminal ortamlari icin:

```bash
scripts/release.sh 1.0.0
```

## Proje yapisi

```text
guildbridge/
  src/guildbridge/
    cli.py
    models.py
    permissions.py
    privacy.py
    providers/
      discord.py
      fluxer.py
      stoat.py
      spacebar.py
      daccord.py
      matrix.py
      rocket_chat.py
      mumble.py
      mattermost.py
      zulip.py
  schema/community-template.schema.json
  examples/template.example.json
  tests/
  docs/
```

## Guvenlik

- `.env` commit etmeyin.
- Token'lari issue raporlarina yapistirmayin.
- `--apply --confirm-apply APPLY --plan-in <reviewed-plan.json>` calistirmadan once dry-run yapin.
- Olusturulan planlari uygulamadan once inceleyin.
- Minimum gerekli izinlere sahip bir bot/application tercih edin.

[SECURITY.md](SECURITY.md) dosyasina bakin.

## Katki

Pull request'ler memnuniyetle karsilanir. Saglayiciya ozel API farkliliklarini provider adapter'lari icinde tutun ve tarafsiz semayi gizlilik acisindan guvenli tutun.

[CONTRIBUTING.md](CONTRIBUTING.md) dosyasina bakin.

## Lisans

MIT. [LICENSE](LICENSE) dosyasina bakin.
