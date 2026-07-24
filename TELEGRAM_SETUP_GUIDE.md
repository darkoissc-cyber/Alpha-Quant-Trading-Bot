# 🤖 دليل إنشاء Telegram Bot - 3 دقائق فقط

## الخطوة 1: افتح @BotFather
- افتح Telegram
- ابحث عن `@BotFather` (الأصلي بعلامة التوثيق الزرقاء ✓)
- اضغط Start

## الخطوة 2: أرسل /newbot
```
/newbot
```
سيطلب منك اسمين:

**الاسم (Name)**: أي اسم تريده
```
Alpha Quant Bot
```

**المعرّف (Username)**: يجب أن ينتهي بـ `bot`
```
alpha_quant_yourname_bot
```

## الخطوة 3: ستحصل على Token
سيعطيك BotFather رسالة مثل:
```
Done! Congratulations on your new bot. You will find it at t.me/alpha_quant_yourname_bot

Use this token to access the HTTP API:
7123456789:AAHfiqksKZ8WmR2zMnCj3e2dSwE3TgR4XYZ

Keep your token secure and store it safely.
```
**Token** = `7123456789:AAHfiqksKZ8WmR2zMnCj3e2dSwE3TgR4XYZ`

## الخطوة 4: احصل على Chat ID
1. أرسل أي رسالة للبوت الجديد (افتح حساب البوت واضغط Start)
2. افتح المتصفح على:
```
https://api.telegram.org/bot<YOUR_TOKEN>/getUpdates
```
3. ستجد JSON فيه:
```json
{
  "result": [{
    "message": {
      "from": {"id": 123456789, ...},
      "chat": {"id": 123456789, ...}
    }
  }]
}
```
4. **Chat ID** = `123456789`

## ⚠️ ملاحظات أمنية
- لا ترسل الـ Token لأحد (يعطي صلاحية كاملة للبوت)
- إذا تسرّب، استخدم `/revoke` في BotFather
- لا تشاركه في الأماكن العامة

## 📤 أرسل لي القيم بشكل آمن
بعد ما تجهزهم، أرسلهم لي بهذه الطريقة:
```
TELEGRAM_BOT_TOKEN: 7123...XYZ
TELEGRAM_CHAT_ID: 123456789
```

وأنا سأضيفهم لـ Render Environment Variables مشفّرين خلال ثوانٍ.
