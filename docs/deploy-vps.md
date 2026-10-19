# النشر على سيرفر VPS يشغّل موقعاً آخر (Nginx)

السكربت `deploy/install-vps.sh` يثبّت المنصة بجانب الموقع الموجود دون المساس به:

- تعمل المنصة كخدمة مستقلة (`nus`) بمستخدم نظام خاص، وتستمع على `127.0.0.1:8010` فقط.
- الكود في `/opt/nus`، والبيانات في `/var/lib/nus`، والأسرار في `/etc/nus/nus.env` (تُولَّد تلقائياً).
- يضيف ملف موقع واحداً جديداً في Nginx للدومين الجديد، ويختبر إعداد Nginx كاملاً قبل إعادة التحميل؛
  إن فشل الاختبار يحذف ملفه ولا يعيد تحميل شيء.
- يطلب شهادة HTTPS للدومين الجديد فقط، ويضيف نسخاً احتياطياً يومياً (14 يوماً).
- قاعدة البيانات SQLite لتوفير الذاكرة (مناسبة للعرض والتجربة).

## الخطوات

1. عند مزوّد الدومين: أضف سجل **A** للدومين الجديد يشير إلى IP السيرفر، وانتظر بضع دقائق.
2. على السيرفر:
   ```bash
   cd /opt && git clone -b ccr-d7646c50-13whrv https://github.com/abademq/Nalut-university-system nus-src
   cd nus-src
   sudo bash deploy/install-vps.sh portal.example.ly you@example.com
   ```
   إذا كان المستودع خاصاً سيطلب Git اسم المستخدم ورمز وصول (Personal Access Token) بدل كلمة المرور.

## بعد التثبيت

| المهمة | الأمر |
|---|---|
| حالة الخدمة | `systemctl status nus` |
| السجلات المباشرة | `journalctl -u nus -f` |
| إعادة التشغيل | `sudo systemctl restart nus` |
| تحديث الكود | `cd /opt/nus-src && git pull && sudo bash deploy/install-vps.sh portal.example.ly` |
| إعادة البيانات التجريبية | `sudo bash deploy/install-vps.sh portal.example.ly --reset-demo` |
| إزالة المنصة بالكامل | `sudo systemctl disable --now nus && sudo rm /etc/nginx/sites-enabled/zz-portal.example.ly && sudo systemctl reload nginx` |

إذا كان المنفذ 8010 مستخدماً: `NUS_PORT=8020 sudo -E bash deploy/install-vps.sh ...`
