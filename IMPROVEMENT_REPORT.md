# تقرير تحسين المنصة المؤسسية - تحليل معمّق

## 1. ملخص تنفيذي
تم فحص **40 ملف Python / MQL5** يغطي **15 وحدة** (Risk, Strategy, AI, Data, Execution, Validation, Operations).
تم تحديد **42 مشكلة** موزعة على:
- 🐛 **أخطاء منطقية حرجة**: 12 (تمنع العمل الصحيح في الإنتاج)
- ⚠️ **مخاطر أمنية**: 4
- 🔧 **ضعف معالجة الأخطاء**: 11
- 📉 **ضعف الأداء/المنطق**: 8
- 📊 **تحسينات موثوقية**: 7

---

## 2. الأخطاء الحرجة المُحددة (12 خطأ)

### 🔴 الخطأ 1: حلقة الذكاء الاصطناعي مفصولة
**الملف**: `strategy_lifecycle/strategy_runner.py:232`
**المشكلة**: يتم تمرير `ai_calibrated_prob=0.60` كثابت مُرمّز إلى `SelfCriticValidator` بدلاً من استدعاء `trainer.predict_trade_quality()`.
**التأثير**: بوابة الذكاء الاصطناعي بأكملها لا تعمل في الإنتاج.
**الإصلاح**: حقن كائن `MetaLabelModelTrainer` في `StrategyRunner` واستدعاء `predict_trade_quality` فعلياً.

### 🔴 الخطأ 2: محاكاة وهمية لـ Telegram في إغلاق المراكز
**الملف**: `execution_engine/mt5_bridge.py:223-225`
**المشكلة**: في وضع المحاكاة، `close_position` يرجع `profit=0.0` ثابتاً، مما يلوث نظام المحاسبة.
**التأثير**: ربح/خسارة وهمي في التقارير.
**الإصلاح**: حساب PnL من سعر الدخول والسعر الحالي في وضع المحاكاة.

### 🔴 الخطأ 3: `current_equity` مجمّد في تقييم المخاطر
**الملف**: `strategy_lifecycle/strategy_runner.py:109`
**المشكلة**: `getattr(self.risk_engine, "peak_equity", 10000.0) or 10000.0` يمرر ذروة الأسهم، ليس الأسهم الحالية.
**التأثير**: مفتاح القتل عند 3.5% لن يُطلق.
**الإصلاح**: استبدال بمصدر equity حقيقي أو استخدام peak_equity عند توفره.

### 🔴 الخطأ 4: معامل STOP خاطئ للـ SELL
**الملف**: `execution_engine/mt5_bridge.py:130-132`
**المشكلة**: في SELL، `tp_r = min(tp_r, fill_price_r - (min_sl_dist * 1.5))` - هذا يحدد سقفاً أدنى لـ TP. لكن إذا كان TP الأصلي `fill + 30` لصفقة BUY، فإن الكود الحالي يحدّده بشكل صحيح. لكن منطق SELL `min` هنا يستخدم نقطة بداية خاطئة عندما TP > fill.
**الإصلاح**: مراجعة وضبط منطق SELL TP.

### 🔴 الخطأ 5: ختم الوقت UTC في `ExecutionAuditLogger`
**الملف**: `execution_engine/advanced_execution.py:93`
**المشكلة**: استخدام `datetime.utcnow()` (مُهمل في Python 3.12+) بدلاً من `datetime.now(timezone.utc)`.
**التأثير**: تحذير DeprecationWarning وعدم الاتساق مع باقي الكود.
**الإصلاح**: استبدال بـ `datetime.now(timezone.utc).isoformat()`.

### 🔴 الخطأ 6: Brier score مُفبرك في التسجيل
**الملف**: `meta_labeling/advanced_ai.py:143-154`
**المشكلة**: عند تسجيل النموذج، `pbo_score=0.04` و `dsr_score=2.15` مُرمّزان ولا يعكسان الأداء الفعلي.
**التأثير**: تزييف مقاييس الجودة.
**الإصلاح**: حساب PBO وDSR من نتائج التدريب الفعلية.

### 🔴 الخطأ 7: `time` غير مستورد
**الملف**: `meta_labeling/advanced_ai.py:143`
**المشكلة**: `f"v{int(time.time())}"` لكن `time` غير مستورد. يستخدم `'time' in globals()` كحيلة.
**التأثير**: لن يعمل في الإنتاج.
**الإصلاح**: استيراد `import time`.

### 🔴 الخطأ 8: نظافة الأخبار عند إعادة التحميل القسري
**الملف**: `market_data/news_filter.py:257-281`
**المشكلة**: `refresh_events_if_needed` يستخدم `force=False` افتراضياً. إذا فشلت الـ HTTP في دورة، يتم تعيين `provider_failed=True` ولكن `_last_refresh` يُحدّث. لن يتم المحاولة لمدة 15 دقيقة.
**التأثير**: إذا فشلت الـ fetch، يبقى النظام بدون حماية أخبار لمدة 15 دقيقة.
**الإصلاح**: عند الفشل، لا نُحدّث `_last_refresh` لإعادة المحاولة قريباً.

### 🔴 الخطأ 9: قاعدة بيانات WAL قد تتراكم بدون حدود
**الملف**: `feature_store/time_series_db.py`
**المشكلة**: لا يوجد `VACUUM` دوري أو حدود لحجم الـ WAL. قاعدة البيانات تنمو بلا حدود.
**التأثير**: امتلاء القرص.
**الإصلاح**: إضافة pruning يومي وإغلاق WAL بعد الإدراج.

### 🔴 الخطأ 10: منطق HRP يكسر مع مصفوفة singular
**الملف**: `portfolio_management/hrp.py:38`
**المشكلة**: `linkage(condensed_dist, method="single")` قد يفشل إذا كانت المصفوفة singular أو تحتوي على NaN.
**التأثير**: انهيار غير متوقع.
**الإصلاح**: إضافة try/except ومعالجة NaN.

### 🔴 الخطأ 11: `correlate` يُرجع NaN لأصل واحد
**الملف**: `risk_engine/advanced_risk.py:34`
**المشكلة**: `price_returns_df.corr()` يُرجع NaN إذا كان أحد الأعمدة ثابتاً.
**التأثير**: انهيار في `is_exposure_allowed`.
**الإصلاح**: تنظيف NaN قبل الارتباط.

### 🔴 الخطأ 12: `ExecutionRetryQueue.pop_ready_orders` فارغ
**الملف**: `execution_engine/advanced_execution.py:63-64`
**المشكلة**: `def pop_ready_orders() -> List[Dict[str, Any]]: pass` (وظيفة فارغة).
**التأثير**: منطق إعادة المحاولة مكسور.
**الإصلاح**: تنفيذ أو إزالة.

---

## 3. المخاطر الأمنية (4)

### 🔒 1. CORS مفتوح
**الملف**: `api/app.py:229-235`
**المشكلة**: `allow_origins=["*"]` و `allow_credentials=True` معاً.
**التأثير**: ثغرة CSRF معتمدة.
**الإصلاح**: تقييد Origins.

### 🔒 2. بيانات اعتماد مكشوفة في `.env`
**الملف**: `alpha_platform/.env`
**المشكلة**: كلمات مرور MT5 مخزنة بنص صريح.
**الإصلاح**: استخدام `SecretsVault` (موجود) لتشفيرها.

### 🔒 3. لا يوجد rate limit على API
**الإصلاح**: إضافة حد طلبات أساسي.

### 🔒 4. كلمات المرور في السجلات
**الملف**: `execution_engine/mt5_bridge.py:165-167`
**المشكلة**: رسائل الخطأ قد تكشف بيانات حساسة.
**الإصلاح**: تنظيف رسائل الخطأ.

---

## 4. خطة التنفيذ (10 دفعات)

| # | الهدف | الملف | الخطورة |
|---|---|---|---|
| 1 | إصلاح AI المقطوع | strategy_runner.py | 🔴 حرج |
| 2 | إصلاح equity المجمّد | strategy_runner.py | 🔴 حرج |
| 3 | إصلاح PnL الوهمي | mt5_bridge.py | 🔴 حرج |
| 4 | إصلاح SELL TP logic | mt5_bridge.py | 🟠 عالٍ |
| 5 | إصلاح utcnow + time import | advanced_execution.py, advanced_ai.py | 🟡 متوسط |
| 6 | إصلاح PBO/DSR المزيف | advanced_ai.py | 🔴 حرج |
| 7 | إصلاح news filter refresh | news_filter.py | 🟠 عالٍ |
| 8 | إصلاح DB WAL pruning | time_series_db.py | 🟡 متوسط |
| 9 | إصلاح HRP NaN handling | hrp.py | 🟡 متوسط |
| 10 | إصلاح CORS + security | app.py, mt5_bridge.py | 🟠 عالٍ |

كل دفعة ستتضمن: ما تم تغييره، لماذا، التحسين المتوقع، المخاطر المحتملة.
