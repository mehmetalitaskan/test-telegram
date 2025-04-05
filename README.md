# Telegram Group Manager API

Bu proje, Telegram grupları oluşturmak, davet bağlantıları göndermek ve gruplar içerisinde mesajlar göndermek için bir REST API sunar. Telethon kütüphanesi kullanılarak geliştirilmiştir.

## Özellikler

- Telegram grupları oluşturma
- Gruplara davet bağlantıları oluşturma ve gönderme
- Belirli kullanıcılardan gönderilmiş gibi görünen mesajlar gönderme
- REST API aracılığıyla tüm işlemleri otomatikleştirme

## Kurulum

1. Gerekli kütüphaneleri yükleyin:
```bash
pip install -r requirements.txt
```

2. Telegram API kimlik bilgilerinizi almanız gerekiyor:
   - [https://my.telegram.org](https://my.telegram.org) adresine gidin
   - "API Development Tools" bölümüne giriş yapın
   - Bir uygulama oluşturun ve API_ID ve API_HASH bilgilerini alın

3. `.env` dosyasını düzenleyin:
   - `API_ID` değerini Telegram'dan aldığınız API ID ile değiştirin
   - `API_HASH` değerini Telegram'dan aldığınız API Hash ile değiştirin
   - `PHONE_NUMBER` değerini ülke kodu dahil telefon numaranızla değiştirin (örn. +905551112233)

## REST API Kullanımı

API'yi çalıştırmak için:

```bash
python telegram_api.py
```

API, varsayılan olarak `http://127.0.0.1:5000` adresinde çalışır ve şu endpoint'leri sunar:

### 1. Grup Oluşturma API

**Endpoint:** `/create-telegram-group`

**Method:** POST

**Body:**
```json
{
  "group_name": "Grup Adı",
  "group_description": "Grup Açıklaması",
  "phones": ["+905551112233", "+905551112244"],
  "invite_message": "Grubumuza davetlisiniz!"
}
```

**Cevap:**
```json
{
  "success": true,
  "group": {
    "name": "Grup Adı",
    "invite_link": "https://t.me/+abcdef123456"
  },
  "invitations": [
    {
      "phone": "+905551112233",
      "status": "success",
      "message": "Invitation sent successfully"
    }
  ]
}
```

### 2. Grup Mesajı Gönderme API

**Endpoint:** `/send-telegram-group-message`

**Method:** POST

**Body:**
```json
{
  "group_link": "https://t.me/+abcdef123456",
  "sender_name": "Ahmet Yılmaz",
  "sender_phone": "+905551112233",
  "message": "Merhaba, bu bir test mesajıdır!"
}
```

**Cevap:**
```json
{
  "success": true,
  "group_link": "https://t.me/+abcdef123456",
  "message": "Message sent successfully"
}
```

## İlk Kimlik Doğrulama

API'yi ilk kez çalıştırdığınızda, session oluşturmak için kimlik doğrulama yapmanız gerekir:

```bash
python telegram_api.py
```

Eğer `telegram_session.session` dosyası mevcut değilse, konsol üzerinden Telegram'a giriş yapmanız ve telefonunuza gelen kodu girmeniz istenecektir.

## Notlar

- Telethon, Telegram'ın API sınırlamalarına tabidir. Çok fazla mesaj gönderirseniz hesabınız geçici olarak kısıtlanabilir.
- İlk çalıştırmada, Telegram hesabınıza giriş yapmanız ve doğrulama kodunu girmeniz gerekecektir.
- Kullanıcı gizlilik ayarları nedeniyle bazı kullanıcılara mesaj göndermek mümkün olmayabilir.

## Lisans

Bu proje MIT lisansı altında lisanslanmıştır.